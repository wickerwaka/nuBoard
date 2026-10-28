"""Freeze the fitted chain model (docs/v35s-hdl-plan.md, Phase A1).

    python -m validation.v35s.chains.freeze [--out DIR]   # write sim/frozen/ (default)
    python -m validation.v35s.chains.freeze --check       # regenerate, diff with sim/frozen/; exit 1 on drift
    python -m validation.v35s.chains.freeze --report      # sizes, unfolded fields
    python -m validation.v35s.chains.freeze --verify [--family F..] [--jobs N]

The generator reads the tracked fit (fit.json) and the model's sources (sim/*.py) and writes
`sim/frozen/`: the same modules with every structural field of the fit a constant. Each read
of a structural field through a Config object (`cfg.<field>`, `self.cfg.<field>`) becomes its
fitted value; every test that becomes a comparison or boolean of literals is folded, the dead
branches of if/elif/else and conditional expressions are removed, statements after a return
or raise are dropped and so are private functions nothing calls any more. The class integers
(`cfg.c(cls, name)`) and the EA table (`cfg.ea`) stay parameters: the frozen package still
takes a Config and reads only those; its Machine rejects a Config whose structure is not the
fit's (`frozen.config.check_structure`).

Two propagations beyond the field reads, both exact: a local name every binding of which is a
structural constant (`mode = self.cfg.request_eval`), and an instance attribute every store of
which, anywhere in the package, is the same constant (`self.timer = cfg.refresh_timer`,
`self.refresh_whole = False`), read as `self.<attr>` in its class.

The rewrite works on the AST and renders the result from the original text: a statement or
expression the fold left alone is copied verbatim (comments, line breaks and all), a changed
one is the original text with its changed parts replaced, and only a node built from nothing
(a folded literal) is printed by ast.unparse. Every place a structural field was read gets a
comment line `# <field> = <value> (fit)`. The generator checks its own output: the generated
text must parse to exactly the folded AST (else it stops), so the text is the transformation.

--verify runs every corpus run of every modelled family through sim/ and sim/frozen/ under
the fitted Config with a clock log requested (which turns the quiet-clock fast-forward off in
both; FAST_FORWARD is also cleared in both) and requires identical Normalized results (events,
pre list, alignment) and identical per-clock state rows (Machine._clock_row).
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import io
import json
import operator
import sys
import tempfile
import time
import tokenize
from dataclasses import fields
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE / "sim"
FIT = HERE / "fit.json"
FROZEN = SIM / "frozen"
REL_FIT = "validation/v35s/chains/fit.json"
# sim/ modules in the frozen package, transformed (config.py is generated instead)
MODULES = ("__init__", "arbiter", "bus", "decoder", "eu", "machine", "queue", "refresh",
           "templates")
TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)
# calls the fold may drop with an operand it no longer needs (no side effects)
PURE_CALLS = frozenset(("len", "isinstance", "bool", "getattr", "min", "max", "abs", "int"))
SCALARS = (bool, int, str, float, type(None))
# values a local, an attribute or a parameter is propagated with (an integer keeps its name)
PROPAGATE = (bool, str, type(None))
ATOMS = (ast.Constant, ast.Name, ast.Attribute, ast.Call, ast.Subscript, ast.Tuple, ast.List,
         ast.Dict, ast.Set)
BODIES = ("body", "orelse", "handlers", "finalbody")
COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
           ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
           ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
           ast.Is: operator.is_, ast.IsNot: operator.is_not}
BINOP = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
         ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.LShift: operator.lshift,
         ast.RShift: operator.rshift, ast.BitOr: operator.or_, ast.BitAnd: operator.and_,
         ast.BitXor: operator.xor}


class FreezeError(RuntimeError):
    pass


# The fit --------------------------------------------------------------------------------

def load_fit(path: Path = FIT):
    """(sha256 of the file, {structural field: value} in Config's field order, Config)."""
    from .sim.config import Config

    data = path.read_bytes()
    cfg = Config.from_json(json.loads(data))
    names = [f.name for f in fields(Config) if f.name not in ("cost", "ea")]
    return hashlib.sha256(data).hexdigest(), {n: getattr(cfg, n) for n in names}, cfg


def note_line(label: str, value) -> str:
    if label.startswith("#"):
        return label                         # a note in its own words
    return f"# {label} = {value!r} (fit)"


# Source text ------------------------------------------------------------------------------

class Source:
    """One module's text with byte-offset helpers (the AST's columns are UTF-8 bytes)."""

    def __init__(self, name: str, text: str):
        self.name, self.text = name, text
        self.data = text.encode()
        self.lines = text.split("\n")
        self.bline = [ln.encode() for ln in self.lines]
        self.off = [0, 0]
        for b in self.bline:
            self.off.append(self.off[-1] + len(b) + 1)
        self.tree = ast.parse(text)
        self.comments: dict[int, str] = {}
        self.tokens = []
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                self.comments[tok.start[0]] = tok.string
            if tok.type in (tokenize.OP, tokenize.NAME, tokenize.NUMBER, tokenize.STRING):
                self.tokens.append((tok.string, self.bpos(*tok.start), self.bpos(*tok.end),
                                    tok.start[0], tok.end[0]))
        self.parens: dict[int, int] = {}       # byte pos of '(' -> byte pos of its ')'
        stack = []
        for s, a, b, _, _ in self.tokens:
            if s in "([{":
                stack.append((s, a))
            elif s in ")]}":
                o, p = stack.pop()
                if o == "(":
                    self.parens[p] = a
        self.tok_at = {a: k for k, (_, a, _, _, _) in enumerate(self.tokens)}
        self.tok_end = {b: k for k, (_, _, b, _, _) in enumerate(self.tokens)}

    def bpos(self, line: int, col_chars: int) -> int:
        return self.off[line] + len(self.lines[line - 1][:col_chars].encode())

    def start(self, n) -> int:
        return self.off[n.lineno] + n.col_offset

    def end(self, n) -> int:
        return self.off[n.end_lineno] + n.end_col_offset

    def seg(self, a: int, b: int) -> str:
        return self.data[a:b].decode()

    def ext_span(self, n) -> tuple[int, int]:
        """n's span with the grouping parentheses around it."""
        a, b = self.start(n), self.end(n)
        while True:
            i, j = self.tok_end_before(a), self.tok_after(b)
            if (i is None or j is None or self.tokens[i][0] != "("
                    or self.parens.get(self.tokens[i][1]) != self.tokens[j][1]):
                return a, b
            # a call's parentheses are not grouping ones
            if i > 0 and (self.tokens[i - 1][0] in (")", "]") or self.tokens[i - 1][0].isidentifier()
                          and self.tokens[i - 1][0] not in ("and", "or", "not", "in", "is", "if",
                                                             "else", "return", "elif", "while",
                                                             "assert", "lambda", "yield")):
                return a, b
            a, b = self.tokens[i][1], self.tokens[j][2]

    def tok_end_before(self, a: int):
        k = self._index_at_or_after(a)
        return k - 1 if k is not None and k > 0 else None

    def tok_after(self, b: int):
        return self._index_at_or_after(b)

    def _index_at_or_after(self, pos: int):
        lo, hi = 0, len(self.tokens)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.tokens[mid][1] < pos:
                lo = mid + 1
            else:
                hi = mid
        return lo if lo < len(self.tokens) else None

    def header_end_line(self, s) -> int:
        """The line of the ':' that ends compound statement s's header."""
        k = self._index_at_or_after(self.start(s))
        depth = 0
        while k < len(self.tokens):
            t = self.tokens[k][0]
            if t in "([{":
                depth += 1
            elif t in ")]}":
                depth -= 1
            elif t == ":" and depth == 0:
                return self.tokens[k][4]
            k += 1
        raise FreezeError(f"{self.name}: no header end for line {s.lineno}")

    def first_line(self, s) -> int:
        decos = getattr(s, "decorator_list", None)
        return min([s.lineno] + [d.lineno for d in decos]) if decos else s.lineno

    def indent_of(self, line: int) -> int:
        ln = self.lines[line - 1]
        return len(ln) - len(ln.lstrip(" "))


def is_original(n, orig_ids) -> bool:
    return id(n) in orig_ids


# The fold ------------------------------------------------------------------------------

class Note:
    """A comment-only pseudo statement in a folded body (never in the emitted AST)."""

    def __init__(self, lines: list[str], comments_of=None, header: bool = False):
        self.lines, self.comments_of, self.header = lines, comments_of, header


def real(stmts) -> list:
    return [s for s in stmts if not isinstance(s, Note)]


def const(n):
    """(True, value) for a literal (also -N and tuples/lists/sets of literals), else (False, None)."""
    if isinstance(n, ast.Constant):
        return True, n.value
    if (isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub)
            and isinstance(n.operand, ast.Constant) and type(n.operand.value) in (int, float)):
        return True, -n.operand.value
    if isinstance(n, (ast.Tuple, ast.List, ast.Set)) and isinstance(n.ctx if hasattr(n, "ctx")
                                                                    else ast.Load(), ast.Load):
        vals = [const(e) for e in n.elts]
        if all(c for c, _ in vals):
            v = [x for _, x in vals]
            return True, (tuple(v) if isinstance(n, ast.Tuple) else
                          v if isinstance(n, ast.List) else frozenset(v))
    return False, None


def mk(v, field_label=None, notes=None):
    """A literal node for v; field_label marks one standing for a structural read."""
    if type(v) in (int, float) and v < 0:
        n = ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=-v))
    else:
        n = ast.Constant(value=v)
    n._field = field_label
    n._notes = notes
    return n


def pure(n) -> bool:
    for x in ast.walk(n):
        if isinstance(x, (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr, ast.Lambda)):
            return False
        if isinstance(x, ast.Call) and not (isinstance(x.func, ast.Name)
                                            and x.func.id in PURE_CALLS):
            return False
    return True


def boolean(n) -> bool:
    """n's value is always a bool."""
    if isinstance(n, ast.Compare) or isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
        return True
    if isinstance(n, ast.Constant):
        return type(n.value) is bool
    if isinstance(n, ast.BoolOp):
        return all(boolean(v) for v in n.values)
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id in ("bool", "isinstance"))


def terminates(s) -> bool:
    if isinstance(s, TERMINAL):
        return True
    if isinstance(s, ast.If):
        b, o = real(s.body), real(s.orelse)
        return bool(b and o and terminates(b[-1]) and terminates(o[-1]))
    return False


def is_cfg(n) -> bool:
    return (isinstance(n, ast.Name) and n.id == "cfg") or (
        isinstance(n, ast.Attribute) and n.attr == "cfg")


def rebuild(n, **kw):
    new = copy.copy(n)
    for k, v in kw.items():
        setattr(new, k, v)
    new._orig = getattr(n, "_orig", n)
    return new


class Folder:
    def __init__(self, structure: dict, attr_consts: dict, module: str,
                 param_consts: dict | None = None, str_sets: dict | None = None,
                 str_base: dict | None = None):
        self.s = structure
        self.str_sets = str_sets or {}
        self.str_base = str_base or {}
        self.param_consts = param_consts or {}
        self.attr_consts = attr_consts       # attr -> (value, [(label, value)]) for self.<attr>
        self.module = module
        self.notes: list = []                # (label, value) read in the current statement
        self.local: dict = {}                # name -> (value, notes) in the current function
        self.self_name = None                # first parameter of the current method
        self.stmt_notes: dict = {}           # id(stmt) -> [(label, value)]
        self.raw: list = []                  # every read, in order (for a fold's provenance)
        self.dry = 0

    # expressions
    def note(self, label, value):
        self.raw.append((label, value))
        if (label, value) not in self.notes:
            self.notes.append((label, value))

    def expr(self, n, boolctx=False):
        at = len(self.raw)
        r = self._expr(n, boolctx)
        if r is not n and getattr(r, "_field", 0) is None and r._notes is None:
            r._notes = list(dict.fromkeys(self.raw[at:]))
        return r

    def _expr(self, n, boolctx=False):
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
            if n.attr in self.s and is_cfg(n.value):
                v = self.s[n.attr]
                self.note(n.attr, v)
                return mk(v, n.attr)
            if n.attr in self.attr_consts and pure(n.value):
                v, notes = self.attr_consts[n.attr]
                for x in notes:
                    self.note(*x)
                return mk(v, f".{n.attr}", notes)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in self.local:
            v, notes = self.local[n.id]
            for x in notes:
                self.note(*x)
            return mk(v, n.id, notes)
        if isinstance(n, ast.BoolOp):
            return self.boolop(n, boolctx)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            o = self.expr(n.operand, True)
            c, v = const(o)
            if c:
                return mk(not v)
            return n if o is n.operand else rebuild(n, operand=o)
        if isinstance(n, ast.Compare):
            return self.compare(n)
        if isinstance(n, ast.IfExp):
            test = self.expr(n.test, True)
            c, v = const(test)
            if c:
                return self.expr(n.body if v else n.orelse, boolctx)
            body, orelse = self.expr(n.body, boolctx), self.expr(n.orelse, boolctx)
            if test is n.test and body is n.body and orelse is n.orelse:
                return n
            return rebuild(n, test=test, body=body, orelse=orelse)
        if isinstance(n, ast.BinOp):
            left, right = self.expr(n.left), self.expr(n.right)
            (cl, vl), (cr, vr) = const(left), const(right)
            if (cl and cr and type(n.op) in BINOP and type(vl) is int and type(vr) is int):
                return mk(BINOP[type(n.op)](vl, vr))
            if isinstance(n.op, (ast.Add, ast.Sub)) and cr and type(vr) is int and vr == 0:
                return left                  # t + 0
            if isinstance(n.op, ast.Add) and cl and type(vl) is int and vl == 0:
                return right
            if left is n.left and right is n.right:
                return n
            return rebuild(n, left=left, right=right)
        if (isinstance(n, ast.Call) and not n.keywords and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("startswith", "endswith")):
            v = self.expr(n.func.value)
            args = [self.expr(a) for a in n.args]
            cs = [const(x) for x in [v] + args]
            if all(c for c, _ in cs) and type(cs[0][1]) is str:
                return mk(getattr(cs[0][1], n.func.attr)(*[x for _, x in cs[1:]]))
        if (isinstance(n, ast.Call) and not n.args and not n.keywords
                and isinstance(n.func, ast.Attribute) and n.func.attr == "bit_length"):
            v = self.expr(n.func.value)
            c, x = const(v)
            if c and type(x) is int:
                return mk(x.bit_length())
        return self.generic(n)

    def generic(self, n):
        changed = {}
        for name, value in ast.iter_fields(n):
            if isinstance(value, list):
                new = [self.child(x, n, name) for x in value]
                if any(a is not b for a, b in zip(new, value)):
                    changed[name] = new
            elif isinstance(value, ast.AST):
                new = self.child(value, n, name)
                if new is not value:
                    changed[name] = new
        return rebuild(n, **changed) if changed else n

    def child(self, x, parent, name):
        if isinstance(x, ast.expr):
            return self.expr(x, isinstance(parent, ast.comprehension) and name == "ifs")
        if isinstance(x, (ast.keyword, ast.comprehension, ast.arguments, ast.arg, ast.withitem,
                          ast.Slice)):
            return self.generic(x)
        return x

    def boolop(self, n, boolctx):
        is_and = isinstance(n.op, ast.And)
        vals = [self.expr(v, boolctx) for v in n.values]
        keep = []
        for i, v in enumerate(vals):
            c, x = const(v)
            last = i == len(vals) - 1
            if c and bool(x) == is_and and not last:
                continue                     # neutral operand
            keep.append((i, v))
            if c:
                break                        # short-circuits here (or is last)
        if len(keep) > 1 and (boolctx or all(boolean(v) for _, v in keep[:-1])):
            # in a test, or with bool operands: `A and True` is A, `A and False` is False
            c, x = const(keep[-1][1])
            if c and bool(x) == is_and:
                keep.pop()
            elif c and all(pure(v) for _, v in keep[:-1]):
                keep = [(keep[-1][0], mk(bool(x)))]
        if len(keep) == 1:
            return keep[0][1]
        if len(keep) == len(n.values) and all(v is o for (_, v), o in zip(keep, n.values)):
            return n
        new = rebuild(n, values=[v for _, v in keep])
        new._idx = [i for i, _ in keep]
        return new

    def compare(self, n):
        d = self._string_test(n)
        if d is not None:
            return d
        left = self.expr(n.left)
        comps = [self.expr(c) for c in n.comparators]
        operands = [left] + comps
        cs = [const(x) for x in operands]
        if all(c for c, _ in cs) and all(type(op) in COMPARE for op in n.ops):
            ok = True
            for k, op in enumerate(n.ops):
                a, b = cs[k][1], cs[k + 1][1]
                if isinstance(op, (ast.Is, ast.IsNot)) and not (
                        a in (None, True, False) and type(a) in (bool, type(None))
                        or b in (None, True, False) and type(b) in (bool, type(None))):
                    return self._rebuilt_compare(n, left, comps)
                if not COMPARE[type(op)](a, b):
                    ok = False
                    break
            return mk(ok)
        return self._rebuilt_compare(n, left, comps)

    def _string_test(self, n):
        """`<obj>.attr == "s"` (!=, in, not in) where attr never holds "s" (string_sets)."""
        if len(n.ops) != 1 or not isinstance(n.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            return None
        a, b = n.left, n.comparators[0]
        if not isinstance(a, ast.Attribute) and isinstance(b, ast.Attribute) and isinstance(
                n.ops[0], (ast.Eq, ast.NotEq)):
            a, b = b, a
        if not (isinstance(a, ast.Attribute) and isinstance(a.ctx, ast.Load) and pure(a.value)):
            return None
        c, lit = const(b)
        lits = (lit,) if isinstance(n.ops[0], (ast.Eq, ast.NotEq)) else lit
        if not c or not isinstance(lits, (tuple, list, frozenset)) or not all(
                isinstance(x, str) for x in lits):
            return None
        held = self.str_sets.get(a.attr)
        if held is None or any(x in held for x in lits):
            return None
        base = self.str_base.get(a.attr)
        if base is not None and not any(x in base for x in lits):
            return None                      # decided in sim/ already: not a fit fact
        self.note(f"# .{a.attr} never holds {', '.join(map(repr, lits))} under the fit "
                  f"(its strings: {', '.join(map(repr, sorted(held))) or 'none'})", None)
        return mk(isinstance(n.ops[0], (ast.NotEq, ast.NotIn)))

    def _rebuilt_compare(self, n, left, comps):
        if left is n.left and all(a is b for a, b in zip(comps, n.comparators)):
            return n
        return rebuild(n, left=left, comparators=comps)

    def fold_value(self, n):
        """Fold n without recording anything: (is constant, value, notes)."""
        saved = self.notes
        self.notes = []
        r = self.expr(n)
        notes, self.notes = self.notes, saved
        c, v = const(r)
        return c, v, notes

    # statements
    def stmts(self, lst) -> list:
        out = []
        for s in lst:
            res = self.stmt(s)
            prev = real(out)
            if prev and res and isinstance(prev[-1], ast.If):
                res = _after_exit(prev[-1], res)
            out.extend(res)
            r = real(res)
            if r and terminates(r[-1]):
                break
        return out

    def body(self, lst) -> list:
        out = self.stmts(lst)
        if not real(out):
            out.append(ast.Pass())
        return out

    def take_notes(self):
        notes, self.notes = self.notes, []
        return notes

    def stmt(self, s) -> list:
        self.notes = []
        if isinstance(s, ast.If):
            test = self.expr(s.test, True)
            notes = self.take_notes()
            c, v = const(test)
            if c:
                res = self.stmts(s.body if v else s.orelse)
                lines = [note_line(*x) + ("" if real(res) else ": branch removed")
                         for x in notes]
                head = Note(lines, comments_of=s if v else None, header=bool(v))
                return [head] + res
            body = _decided(self.stmts(s.body), test, True)
            orelse = _decided(self.stmts(s.orelse), test, False)
            after = []
            if not real(orelse):
                after, orelse = orelse, []   # an else of notes only: the notes follow the if
            if not real(body):
                if not real(orelse) and pure(test):
                    return [Note([note_line(*x) + ": branch removed" for x in notes])]
                body = body + [ast.Pass()]
            new = s if (test is s.test and _same(body, s.body) and _same(orelse, s.orelse)) \
                else rebuild(s, test=test, body=body, orelse=orelse)
            self.stmt_notes[id(new)] = notes
            return [new] + after
        if isinstance(s, ast.While):
            test = self.expr(s.test, True)
            notes = self.take_notes()
            c, v = const(test)
            if c and not v:
                return [Note([note_line(*x) for x in notes])] + self.stmts(s.orelse)
            body, orelse = self.body(s.body), self.stmts(s.orelse)
            new = s if (test is s.test and _same(body, s.body) and _same(orelse, s.orelse)) \
                else rebuild(s, test=test, body=body, orelse=orelse)
            self.stmt_notes[id(new)] = notes
            return [new]
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return [self.function(s)]
        if isinstance(s, ast.ClassDef):
            return [self.compound(s)]
        if isinstance(s, ast.ImportFrom) and s.level >= 2:
            new = rebuild(s, level=s.level + 1)
            new._import_level = True
            return [new]
        if (isinstance(s, ast.Assign) and len(s.targets) == 1
                and isinstance(s.targets[0], ast.Name) and s.targets[0].id in self.local):
            v, notes = self.local[s.targets[0].id]
            return [Note([note_line(*x) for x in notes])]
        if isinstance(s, ast.Assert):
            test = self.expr(s.test, True)
            c, v = const(test)
            if c and v:
                return [Note([note_line(*x) for x in self.take_notes()])]
        if any(isinstance(getattr(s, b, None), list) for b in BODIES):
            return [self.compound(s)]
        new = self.generic(s)
        self.stmt_notes[id(new)] = self.take_notes()
        return [new]

    def compound(self, s):
        changed = {}
        for name, value in ast.iter_fields(s):
            if name in BODIES:
                continue
            if isinstance(value, list):
                new = [self.child(x, s, name) for x in value]
                if any(a is not b for a, b in zip(new, value)):
                    changed[name] = new
            elif isinstance(value, ast.AST):
                new = self.child(value, s, name)
                if new is not value:
                    changed[name] = new
        notes = self.take_notes()
        for name in BODIES:
            value = getattr(s, name, None)
            if not isinstance(value, list):
                continue
            if name == "handlers":
                new = [self.handler(h) for h in value]
            elif name == "body":
                new = self.body(value)
            else:
                new = self.stmts(value)
                if not real(new):
                    new = []                 # (notes of a removed else/finally dropped)
            if not _same(new, value):
                changed[name] = new
        new = rebuild(s, **changed) if changed else s
        self.stmt_notes[id(new)] = notes
        return new

    def handler(self, h):
        body = self.body(h.body)
        return h if _same(body, h.body) else rebuild(h, body=body)

    def function(self, f):
        saved = (self.local, self.self_name)
        self.local = dict(self.local)
        for name in _arg_names(f):
            self.local.pop(name, None)
        self.local.update(self.local_consts(f))
        if getattr(f, "_top", False):
            self.local.update(self.param_consts.get(f.name, {}))
        args = f.args.args
        if _in_class(f):
            self.self_name = args[0].arg if args else None
        new = self.compound(f)
        self.local, self.self_name = saved
        return new

    def local_consts(self, f) -> dict:
        """Locals of f every binding of which is one simple assignment of a structural
        constant, all of the same value."""
        binds: dict = {}
        bad = set(_arg_names(f))
        simple = {id(a.targets[0]) for a in ast.walk(f)
                  if isinstance(a, ast.Assign) and len(a.targets) == 1}
        for x in ast.walk(f):
            if x is f:
                continue
            if isinstance(x, (ast.Global, ast.Nonlocal)):
                bad.update(x.names)
            elif isinstance(x, ast.Assign) and len(x.targets) == 1 and isinstance(
                    x.targets[0], ast.Name):
                binds.setdefault(x.targets[0].id, []).append(x.value)
                continue
            if isinstance(x, ast.Name) and not isinstance(x.ctx, ast.Load):
                if id(x) not in simple:
                    bad.add(x.id)
            elif isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bad.add(x.name)
            elif isinstance(x, ast.arg):
                bad.add(x.arg)
            elif isinstance(x, ast.alias):
                bad.add((x.asname or x.name).split(".")[0])
            elif isinstance(x, ast.ExceptHandler) and x.name:
                bad.add(x.name)
        out = {}
        for name, values in binds.items():
            if name in bad:
                continue
            got = [self.fold_value(v) for v in values]
            if not all(c and nts and type(v) in PROPAGATE for c, v, nts in got):
                continue                     # only constants a structural read made
            if len({(type(v), repr(v)) for _, v, _ in got}) != 1:
                continue
            notes = []
            for _, _, nts in got:
                for x in nts:
                    if x not in notes:
                        notes.append(x)
            out[name] = (got[0][1], notes)
        return out


def _decided(stmts: list, test, value: bool) -> list:
    """A branch of `if test` whose first statement tests the same pure condition again
    (`if T: ... else: if T: ...`, left by a folded elif): that inner test is known."""
    k = next((i for i, x in enumerate(stmts) if not isinstance(x, Note)), None)
    if k is None or not isinstance(stmts[k], ast.If) or not pure(test):
        return stmts
    inner = stmts[k]
    if ast.dump(inner.test) != ast.dump(test):
        return stmts
    kept = inner.body if value else inner.orelse
    note = Note([f"# {ast.unparse(test)}: decided by the test above"
                 + ("" if real(kept) else ", branch removed")])
    return stmts[:k] + [note] + _decided(list(kept), test, value) + stmts[k + 1:]


def _after_exit(prev, stmts: list) -> list:
    """`if T: return ...` (no else) then `if T` / `if not T` straight after: T is known false
    there (`if left == 2: return False` / `if left == 2: ...`, left by two folded rules)."""
    k = next((i for i, x in enumerate(stmts) if not isinstance(x, Note)), None)
    if (k is None or prev.orelse or not real(prev.body) or not terminates(real(prev.body)[-1])
            or not pure(prev.test) or not isinstance(stmts[k], ast.If)):
        return stmts
    inner = stmts[k]
    t = prev.test
    neg = t.operand if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not) else None
    if ast.dump(inner.test) == ast.dump(t):
        value = False
    elif neg is not None and ast.dump(inner.test) == ast.dump(neg):
        value = True
    elif (isinstance(inner.test, ast.UnaryOp) and isinstance(inner.test.op, ast.Not)
          and ast.dump(inner.test.operand) == ast.dump(t)):
        value = True
    else:
        return stmts
    kept = inner.body if value else inner.orelse
    note = Note([f"# {ast.unparse(inner.test)}: {value} here (the if above returned)"
                 + ("" if real(kept) else ", branch removed")])
    return stmts[:k] + [note] + list(kept) + stmts[k + 1:]


def _same(new, old) -> bool:
    return len(new) == len(old) and all(a is b for a, b in zip(new, old))


def _arg_names(f) -> list:
    a = f.args
    names = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return names


def _in_class(f) -> bool:
    return getattr(f, "_in_class", False)


def _self_stores(cls) -> set:
    out = set()
    for f in cls.body:
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.args.args:
            me = f.args.args[0].arg
            for x in ast.walk(f):
                if (isinstance(x, ast.Attribute) and isinstance(x.ctx, ast.Store)
                        and isinstance(x.value, ast.Name) and x.value.id == me):
                    out.add(x.attr)
    return out


def mark_methods(tree):
    for f in tree.body:
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            f._top = True
    for x in ast.walk(tree):
        if isinstance(x, ast.ClassDef):
            for f in x.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    f._in_class = f._top = True


# Package-wide analyses ----------------------------------------------------------------

def _attr_stores(trees: dict):
    """(stores: attr -> [value], augmented: attr -> [(op, value)], unfoldable attrs, attrs
    stored on self in a package class)."""
    stores: dict = {}
    augs: dict = {}
    bad = set()
    for tree in trees.values():
        for x in ast.walk(tree):
            if isinstance(x, ast.ClassDef):
                for b in x.body:
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        bad.add(b.name)
                    elif isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name):
                        bad.add(b.target.id)
                    elif isinstance(b, ast.Assign):
                        bad.update(t.id for t in b.targets if isinstance(t, ast.Name))
            elif isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in (
                    "getattr", "setattr", "hasattr", "delattr"):
                bad.update(a.value for a in x.args if isinstance(a, ast.Constant)
                           and isinstance(a.value, str))
            elif isinstance(x, ast.Assign):
                for t in x.targets:
                    _collect_stores(t, x.value, stores, bad)
            elif isinstance(x, ast.AugAssign) and isinstance(x.target, ast.Attribute):
                augs.setdefault(x.target.attr, []).append((x.op, x.value))
            elif isinstance(x, ast.AnnAssign):
                _collect_stores(x.target, None, stores, bad)
            elif isinstance(x, (ast.For, ast.AsyncFor, ast.withitem, ast.comprehension)):
                for t in ast.walk(getattr(x, "target", None) or getattr(x, "optional_vars", None)
                                  or ast.Pass()):
                    if isinstance(t, ast.Attribute):
                        bad.add(t.attr)
            elif isinstance(x, ast.Delete):
                bad.update(t.attr for t in x.targets if isinstance(t, ast.Attribute))
        for x in tree.body:
            if isinstance(x, ast.Assign):
                bad.update(t.id for t in x.targets if isinstance(t, ast.Name))
    owned = set()
    for tree in trees.values():
        for x in ast.walk(tree):
            if isinstance(x, ast.ClassDef):
                owned |= _self_stores(x)
    bad |= external_attrs()
    return stores, augs, bad, owned


def constant_attrs(trees: dict, structure: dict, baseline=None) -> dict:
    """attr -> (value, notes): attributes every store of which (anywhere in the package) is
    the same literal, never a class-level name, method, dataclass field, module name, a
    getattr/hasattr/setattr string or an attribute of a class from outside the package."""
    stores, augs, bad, owned = _attr_stores(trees)
    bad = bad | set(augs)
    out = {}
    for attr, values in stores.items():
        if attr in bad or attr not in owned:
            continue
        got = [const(v) + (getattr(v, "_notes", None) or _field_notes(v, structure),)
               for v in values]
        if (not all(c and type(v) in PROPAGATE for c, v, _ in got)
                or len({(type(v), repr(v)) for _, v, _ in got}) != 1):
            continue
        notes = []
        for _, _, nts in got:
            for x in nts or []:
                if x not in notes:
                    notes.append(x)
        if not notes:
            if baseline is not None and attr in baseline:
                continue                     # constant in sim/ already: not a fit fact
            if baseline is not None:         # the fold removed every other store
                notes = [(f".{attr}", got[0][1])]
        out[attr] = (got[0][1], notes)
    return out


def constant_params(trees: dict, structure: dict, baseline=None) -> dict:
    """{function: {parameter: (value, notes)}}: parameters of a private function or method
    (one definition in the package, referenced only by calls) to which every call passes the
    same literal, at least one of them a structural value (`self._interlocked(cls,
    cfg.io_interlock)`)."""
    defs: dict = {}
    for tree in trees.values():
        for parent in [tree] + [c for c in tree.body if isinstance(c, ast.ClassDef)]:
            for d in parent.body:
                if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.setdefault(d.name, []).append((d, parent is not tree))
    calls: dict = {}
    other: set = set()
    for tree in trees.values():
        funcs = set()
        for x in ast.walk(tree):
            if isinstance(x, ast.Call):
                fn = x.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(
                    fn, ast.Attribute) else None
                if name is not None:
                    calls.setdefault(name, []).append(x)
                    funcs.add(id(fn))
        for x in ast.walk(tree):
            if id(x) in funcs:
                continue
            if isinstance(x, ast.Name):
                other.add(x.id)
            elif isinstance(x, ast.Attribute):
                other.add(x.attr)
            elif isinstance(x, ast.Constant) and isinstance(x.value, str):
                other.add(x.value)
    out: dict = {}
    for name, ds in defs.items():
        if (not name.startswith("_") or name.startswith("__") or len(ds) != 1
                or name in other or name not in calls):
            continue
        f, method = ds[0]
        a = f.args
        if f.decorator_list or a.vararg or a.kwarg or a.posonlyargs or a.kwonlyargs:
            continue
        names = [x.arg for x in a.args]
        defaults = dict(zip(names[len(names) - len(a.defaults):], a.defaults))
        params = names[1:] if method else names
        stored = {x.id for x in ast.walk(f) if isinstance(x, ast.Name)
                  and not isinstance(x.ctx, ast.Load)}
        for i, p in enumerate(params):
            if p in stored:
                continue
            vals = []
            for c in calls[name]:
                if any(isinstance(x, ast.Starred) for x in c.args) or any(
                        k.arg is None for k in c.keywords):
                    vals = None
                    break
                kw = [k.value for k in c.keywords if k.arg == p]
                v = c.args[i] if i < len(c.args) else kw[0] if kw else defaults.get(p)
                if v is None:
                    vals = None
                    break
                vals.append(v)
            if not vals:
                continue
            got = [const(v) for v in vals]
            if (not all(c and type(x) in PROPAGATE for c, x in got)
                    or len({(type(x), repr(x)) for _, x in got}) != 1):
                continue
            notes = []
            for v in vals:
                for x in getattr(v, "_notes", None) or _field_notes(v, structure) or []:
                    if x not in notes:
                        notes.append(x)
            if not notes and baseline is not None and p not in baseline.get(name, {}):
                notes = [(p, got[0][1])]     # the fold removed every call passing another
            if notes or baseline is None:
                out.setdefault(name, {})[p] = (got[0][1], notes)
    return out


NONSTR_OPS = (ast.Sub, ast.FloorDiv, ast.Div, ast.LShift, ast.RShift, ast.BitOr, ast.BitAnd,
              ast.BitXor, ast.Pow)
NONSTR_RETURNS = ("int", "bool", "float", "None", "int | None", "bool | None", "float | None")


def string_sets(trees: dict) -> dict:
    """attr -> the strings it can hold: attributes every store of which (anywhere in the
    package) is a string literal or a value that is never a string (a number, a bool, None,
    arithmetic, a call of a function annotated to return int or bool, an attribute of that
    kind: a greatest fixpoint). A test of such an attribute against another string is
    decided (`eu.sync == "room"` when only None, counts and "defer" are ever stored)."""
    stores, augs, bad, owned = _attr_stores(trees)
    returns: dict = {}
    for tree in trees.values():
        for x in ast.walk(tree):
            if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)):
                r = ast.unparse(x.returns) if x.returns is not None else None
                returns.setdefault(x.name, []).append(r)
    attrs = {a for a in owned if a not in bad}
    nonstr = set(attrs)

    def ns(v) -> bool:
        if isinstance(v, ast.Constant):
            return not isinstance(v.value, str)
        if isinstance(v, ast.BinOp):
            if isinstance(v.op, NONSTR_OPS):
                return True
            if isinstance(v.op, ast.Add):
                return ns(v.left) or ns(v.right)
            return ns(v.left) and ns(v.right)
        if isinstance(v, (ast.UnaryOp, ast.Compare)):
            return True
        if isinstance(v, ast.BoolOp):
            return all(ns(x) for x in v.values)
        if isinstance(v, ast.IfExp):
            return ns(v.body) and ns(v.orelse)
        if isinstance(v, ast.Attribute):
            return v.attr in nonstr
        if isinstance(v, ast.Call):
            fn = v.func
            if isinstance(fn, ast.Name) and fn.id in ("int", "len", "bool", "abs", "float"):
                return True
            if isinstance(fn, ast.Name) and fn.id in ("max", "min"):
                return bool(v.args) and all(ns(a) for a in v.args)
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(
                fn, ast.Attribute) else None
            rs = returns.get(name, [])
            return len(rs) == 1 and rs[0] in NONSTR_RETURNS
        return False

    def ok(a) -> bool:
        return all(ns(v) for v in stores.get(a, [])) and all(
            isinstance(op, NONSTR_OPS) or isinstance(op, ast.Add) and ns(v)
            for op, v in augs.get(a, []))

    while True:
        gone = {a for a in nonstr if not ok(a)}
        if not gone:
            break
        nonstr -= gone
    out = {}
    for a in sorted(attrs):
        vals = stores.get(a, [])
        strs = {v.value for v in vals if isinstance(v, ast.Constant) and isinstance(v.value, str)}
        if not strs and a in nonstr:
            continue                         # never a string: nothing to decide
        if all(isinstance(v, ast.Constant) and isinstance(v.value, str) or ns(v) for v in vals) \
                and all(isinstance(op, NONSTR_OPS) or isinstance(op, ast.Add) and ns(v)
                        for op, v in augs.get(a, [])):
            out[a] = frozenset(strs)
    return out


def external_attrs() -> frozenset:
    """Attribute names of the classes sim/ uses from outside the package (Chain, Normalized,
    Event, ...): never folded, whatever the package stores under the same name."""
    import importlib
    import inspect

    names = set()
    for mod in ("types", "normalize", "image", "blocks"):
        try:
            m = importlib.import_module(f"validation.v35s.chains.{mod}")
        except ImportError:
            continue
        for _, c in inspect.getmembers(m, inspect.isclass):
            names |= set(vars(c))
            names |= set(getattr(c, "__dataclass_fields__", {}))
            names |= set(getattr(c, "__annotations__", {}))
    return frozenset(names)


def _field_notes(v, structure):
    f = getattr(v, "_field", None)
    if f in structure:
        return [(f, structure[f])]
    return getattr(v, "_fold_notes", None)


def _collect_stores(t, value, stores, bad):
    if isinstance(t, ast.Attribute):
        if value is None:
            bad.add(t.attr)
        else:
            stores.setdefault(t.attr, []).append(value)
    elif isinstance(t, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(t.elts):
            for a, b in zip(t.elts, value.elts):
                _collect_stores(a, b, stores, bad)
        else:
            for a in t.elts:
                _collect_stores(a, None, stores, bad)
    elif isinstance(t, ast.Starred):
        _collect_stores(t.value, None, stores, bad)


def remove_unused_private(trees: dict) -> list[str]:
    """Drop private functions, methods and classes nothing references any more (a fixpoint).
    Returns the dropped names (module.name)."""
    dropped = []
    while True:
        refs = set()
        defs = []
        for mod, tree in trees.items():
            for x in ast.walk(tree):
                if isinstance(x, ast.Name):
                    refs.add(x.id)
                elif isinstance(x, ast.Attribute):
                    refs.add(x.attr)
                elif isinstance(x, ast.Constant) and isinstance(x.value, str):
                    refs.add(x.value)
            for parent in [tree] + [c for c in tree.body if isinstance(c, ast.ClassDef)]:
                for d in parent.body:
                    if (isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                            and d.name.startswith("_") and not d.name.startswith("__")):
                        defs.append((mod, parent, d))
        gone = [(m, p, d) for m, p, d in defs if d.name not in refs]
        if not gone:
            return dropped
        names = {d.name for _, _, d in gone}
        for mod, parent, d in gone:
            parent.body = [x for x in parent.body if x is not d]
            if not real(parent.body):
                parent.body.append(ast.Pass())
            dropped.append(f"{mod}.{d.name}")
        for tree in trees.values():
            _drop_imports(tree, names)


def _drop_imports(tree, names):
    for parent in ast.walk(tree):
        for field in BODIES:
            body = getattr(parent, field, None)
            if not isinstance(body, list):
                continue
            out = []
            for s in body:
                if isinstance(s, ast.ImportFrom) and any(a.name in names for a in s.names):
                    kept = [a for a in s.names if a.name not in names]
                    if not kept:
                        continue
                    s2 = rebuild(s, names=kept)
                    s2._import_names = True
                    out.append(s2)
                else:
                    out.append(s)
            setattr(parent, field, out)


def drop_dead_aliases(tree):
    """`cfg = self.cfg` in a function that no longer reads cfg: gone."""
    for f in ast.walk(tree):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        loads = {x.id for x in ast.walk(f) if isinstance(x, ast.Name)
                 and isinstance(x.ctx, ast.Load)}
        body = [s for s in f.body if not (
            isinstance(s, ast.Assign) and len(s.targets) == 1
            and isinstance(s.targets[0], ast.Name) and s.targets[0].id not in loads
            and is_cfg(s.value) and isinstance(s.value, ast.Attribute))]
        if len(body) != len(f.body):
            f.body = body


# Emitting text ------------------------------------------------------------------------

class Emitter:
    def __init__(self, src: Source, stmt_notes: dict, orig_ids: set):
        self.src, self.stmt_notes, self.orig_ids = src, stmt_notes, orig_ids
        self.out: list[str] = []
        self.line_of: dict = {}               # id(stmt) -> first output line (1-based)
        self.lead: dict = {}                  # id(original stmt) -> [comment or "" lines]
        self.trailing: list = []
        self.fallbacks: list = []             # (sim line, node) printed by ast.unparse
        self._leading_comments(src.tree)

    # comments of the original layout
    def _region(self, a: int, b: int) -> list:
        out = []
        for line in range(a, b + 1):
            text = self.src.lines[line - 1]
            if not text.strip():
                out.append("")
            elif line in self.src.comments:
                c = self.src.comments[line]
                col = len(text) - len(text.lstrip(" ")) if text.lstrip().startswith("#") else None
                out.append((col, c))
        return out

    def _leading_comments(self, tree):
        src = self.src

        def walk(stmts, prev_end):
            for s in stmts:
                first = src.first_line(s)
                self.lead[id(s)] = self._region(prev_end + 1, first - 1)
                inner(s)
                prev_end = s.end_lineno
            return prev_end

        def inner(s):
            if not any(isinstance(getattr(s, b, None), list) for b in BODIES):
                return
            if isinstance(s, (ast.Module,)):
                return
            head = src.header_end_line(s)
            end = walk(s.body, head)
            if isinstance(s, ast.Try) or isinstance(s, getattr(ast, "TryStar", ast.Try)):
                for h in s.handlers:
                    hh = src.header_end_line(h)
                    self.lead[id(h)] = self._region(end + 1, h.lineno - 1)
                    end = walk(h.body, hh)
            if getattr(s, "orelse", None):
                end = walk(s.orelse, end)
            if getattr(s, "finalbody", None):
                walk(s.finalbody, end)

        end = walk(tree.body, 0)
        self.trailing = self._region(end + 1, len(src.lines))

    # rendering
    def render(self, n) -> str:
        if is_original(n, self.orig_ids):
            return self.src.seg(self.src.start(n), self.src.end(n))
        o = getattr(n, "_orig", None)
        if o is None or not hasattr(o, "lineno"):
            if not isinstance(n, (ast.Constant, ast.UnaryOp)):
                self.fallbacks.append((getattr(n, "lineno", None), type(n).__name__))
            return ast.unparse(n)
        if isinstance(n, ast.BoolOp) and hasattr(n, "_idx"):
            return self._boolop(n, o)
        a = self.src.start(o)
        text = self._replace(o, n, a, self.src.end(o))
        if text is None:
            self.fallbacks.append((o.lineno, type(n).__name__))
            return ast.unparse(n)
        return text

    def _boolop(self, n, o):
        src = self.src
        spans = [src.ext_span(v) for v in o.values]
        parts = []
        for j, (i, v) in enumerate(zip(n._idx, n.values)):
            ea, eb = spans[i]
            ov = o.values[i]
            text = self.render(v)
            if (isinstance(ov, ast.BoolOp) and not isinstance(v, (ast.BoolOp, ast.IfExp,
                                                                  ast.Lambda, ast.NamedExpr))
                    and "\n" not in text):
                body = text                  # (A or B) folded to A: no parentheses
            else:
                body = src.seg(ea, src.start(ov)) + text + src.seg(src.end(ov), eb)
            if j:
                prev = n._idx[j - 1]
                sep = src.seg(spans[i - 1][1], ea)
                if prev != i - 1:            # operands dropped between: keep a line break
                    before = src.seg(spans[prev][1], spans[prev + 1][0])
                    if "\n" in before or "\n" not in sep:
                        sep = before
                parts.append(sep)
            parts.append(body)
        return "".join(parts)

    def _repls(self, o, n, out) -> bool:
        for name, ov in ast.iter_fields(o):
            if name in BODIES and isinstance(ov, list):
                continue
            nv = getattr(n, name)
            if isinstance(ov, list):
                if len(ov) != len(nv):
                    return False
                pairs = list(zip(ov, nv))
            else:
                pairs = [(ov, nv)]
            for a, b in pairs:
                if a is b or not isinstance(a, ast.AST):
                    if a is not b and a != b:
                        return False
                    continue
                if hasattr(a, "lineno") and hasattr(a, "end_col_offset"):
                    text = self.render(b)
                    sa, sb = self.src.start(a), self.src.end(a)
                    if (isinstance(o, ast.Attribute) and name == "value"
                            and isinstance(b, (ast.Constant, ast.UnaryOp))):
                        text = f"({text})"         # 16 .bit_length(), not 16.bit_length()
                    elif (isinstance(a, (ast.IfExp, ast.BoolOp)) and isinstance(b, ATOMS)
                          and "\n" not in text):
                        sa, sb = self.src.ext_span(a)   # (x if c else y) folded to y: no parens
                    elif (isinstance(a, (ast.IfExp, ast.BoolOp))
                          and isinstance(b, (ast.IfExp, ast.BoolOp)) and "\n" in text):
                        # A and (B\n or C) folded to the multi-line operand alone: its grouping
                        # parentheses were the outer expression's, so they are put back
                        text = f"({text})"
                    out.append((sa, sb, text))
                elif getattr(b, "_orig", None) is a:
                    if not self._repls(a, b, out):
                        return False
                else:
                    return False
        return True

    def _replace(self, o, n, a: int, b: int):
        repls = []
        if not self._repls(o, n, repls):
            return None
        data = self.src.data
        pieces, pos = [], a
        for s, e, text in sorted(repls):
            if s < pos:
                return None
            pieces.append(data[pos:s].decode())
            pieces.append(text)
            pos = e
        pieces.append(data[pos:b].decode())
        return "".join(pieces)

    def note(self, indent: int, text: str):
        """A note line, unless the comment lines right above already say it."""
        k = len(self.out)
        while k and self.out[k - 1].lstrip().startswith("#"):
            k -= 1
            if self.out[k].strip() == text or self.out[k].strip() == text + ": branch removed":
                return
        self.emit(" " * indent + text)

    def emit(self, line: str = ""):
        self.out.append(line.rstrip())

    def comments(self, lines, indent, delta=0):
        for c in lines:
            if c == "":
                blanks = len(self.out) - len(self.out_rstrip())
                if self.out and blanks < 2 and not self.out[-1].endswith(":"):
                    self.emit("")
                continue
            col, text = c
            self.emit(" " * (indent if col is None else max(indent, col - delta)) + text)

    def out_rstrip(self):
        k = len(self.out)
        while k and not self.out[k - 1]:
            k -= 1
        return self.out[:k]

    def reindent(self, text: str, orig_col: int, indent: int, first_stripped: bool) -> list:
        lines = text.split("\n")
        delta = orig_col - indent
        out = []
        for k, ln in enumerate(lines):
            if k == 0 and first_stripped:
                out.append(" " * indent + ln.lstrip(" "))
                continue
            if delta >= 0:
                lead = len(ln) - len(ln.lstrip(" "))
                out.append(ln[min(delta, lead):])
            else:
                out.append(" " * (-delta) + ln if ln.strip() else ln)
        return out

    def block(self, stmts, indent):
        for s in stmts:
            if isinstance(s, Note):
                if s.comments_of is not None:
                    o = getattr(s.comments_of, "_orig", s.comments_of)
                    self.comments(self.lead.get(id(o), []), indent,
                                  self.src.indent_of(o.lineno) - indent)
                    if s.header:
                        hl = self.src.header_end_line(o)
                        self.comments([(None, self.src.comments[k]) for k in
                                       range(o.lineno, hl + 1) if k in self.src.comments], indent)
                for ln in s.lines:
                    self.note(indent, ln)
                continue
            self.stmt(s, indent)

    def stmt(self, s, indent, kw=None):
        src = self.src
        o = s if is_original(s, self.orig_ids) else getattr(s, "_orig", None)
        if o is not None:
            self.comments(self.lead.get(id(o), []), indent,
                          src.indent_of(src.first_line(o)) - indent)
        for label, value in self.stmt_notes.get(id(s), []):
            self.note(indent, note_line(label, value))
        self.line_of[id(s)] = len(self.out) + 1
        compound = any(isinstance(getattr(s, b, None), list) for b in BODIES)
        if o is None:
            text = ast.unparse(s)
            for ln in text.split("\n"):
                self.emit(" " * indent + ln if ln else "")
            return
        if not compound:
            if getattr(s, "_import_level", False) or getattr(s, "_import_names", False):
                text = self._import_text(s, o)
            elif s is o:
                text = src.seg(src.start(o), src.end(o))
            else:
                text = self.render(s)
            tail = src.bline[o.end_lineno - 1][o.end_col_offset:].decode()
            if tail.strip().startswith("#"):
                text += tail.rstrip()
            for ln in self.reindent(text, o.col_offset, indent, True):
                self.out.append(ln.rstrip())
            return
        # compound: header from the original lines, then the bodies
        first = src.first_line(o)
        hl = src.header_end_line(o)
        if any(getattr(b, "lineno", 0) <= hl for b in real(getattr(o, "body", []))):
            raise FreezeError(f"{src.name}:{o.lineno}: one-line compound statement")
        a, b = src.off[first], src.off[hl] + len(src.bline[hl - 1])
        text = None if s is not o else src.seg(a, b)
        if text is None:
            text = self._replace(o, s, a, b)
            if text is None:
                raise FreezeError(f"{src.name}:{o.lineno}: cannot render a changed header")
        lines = self.reindent(text, src.indent_of(first), indent, True)
        if isinstance(s, ast.If):
            head = lines[0].lstrip(" ")
            word = "elif" if head.startswith("elif") else "if"
            want = kw or "if"
            if word != want:
                lines[0] = " " * indent + want + head[len(word):]
        for ln in lines:
            self.out.append(ln.rstrip())
        if isinstance(s, (ast.Try,)):
            self.block(s.body, indent + 4)
            for h in s.handlers:
                ho = h if is_original(h, self.orig_ids) else h._orig
                self.comments(self.lead.get(id(ho), []), indent,
                              src.indent_of(ho.lineno) - indent)
                hh = src.header_end_line(ho)
                htext = src.seg(src.off[ho.lineno], src.off[hh] + len(src.bline[hh - 1]))
                for ln in self.reindent(htext, src.indent_of(ho.lineno), indent, True):
                    self.out.append(ln.rstrip())
                self.block(h.body, indent + 4)
            if s.orelse:
                self.emit(" " * indent + "else:")
                self.block(s.orelse, indent + 4)
            if s.finalbody:
                self.emit(" " * indent + "finally:")
                self.block(s.finalbody, indent + 4)
            return
        self.block(s.body, indent + 4)
        orelse = getattr(s, "orelse", None)
        if orelse:
            if (isinstance(s, ast.If) and len(orelse) == 1 and isinstance(orelse[0], ast.If)
                    and self._was_elif(orelse[0])):
                self.stmt(orelse[0], indent, kw="elif")
            else:
                self.emit(" " * indent + "else:")
                self.block(orelse, indent + 4)

    def _was_elif(self, s) -> bool:
        o = s if is_original(s, self.orig_ids) else getattr(s, "_orig", None)
        if o is None:
            return True
        return self.src.lines[o.lineno - 1].lstrip().startswith("elif")

    def _import_text(self, s, o) -> str:
        if getattr(s, "_import_names", False) and not getattr(s, "_import_level", False):
            return ast.unparse(s)
        text = self.src.seg(self.src.start(o), self.src.end(o))
        if getattr(s, "_import_names", False):
            return ast.unparse(s)
        old = "from " + "." * o.level
        assert text.startswith(old), text
        return "from " + "." * s.level + text[len(old):]

    def module(self, tree) -> str:
        self.block(tree.body, 0)
        self.comments(self.trailing, 0)
        while self.out and not self.out[-1]:
            self.out.pop()
        return "\n".join(self.out) + "\n"


# Generation ---------------------------------------------------------------------------

HEADER_LINES = 4


def header(sha: str) -> str:
    return (f"# Generated by validation/v35s/chains/freeze.py from {REL_FIT}\n"
            f"# (sha256 {sha}); do not edit.\n"
            "# Regenerate: python -m validation.v35s.chains.freeze. Every structural field of\n"
            "# the fit is a constant here; `# <field> = <value> (fit)` marks where one was read.\n")


def strip_notes(tree):
    t = copy.deepcopy(tree)
    for x in ast.walk(t):
        for b in BODIES:
            v = getattr(x, b, None)
            if isinstance(v, list):
                setattr(x, b, [s for s in v if not isinstance(s, Note)])
    return t


def _insert_check(tree):
    """frozen machine.py: Machine.__init__ rejects a Config whose structure is not the fit's."""
    for k, s in enumerate(tree.body):
        if isinstance(s, ast.ImportFrom) and s.module == "config" and s.level == 1:
            imp = ast.ImportFrom(module="config", names=[ast.alias(name="check_structure")],
                                 level=1)
            tree.body.insert(k + 1, imp)
            break
    else:
        raise FreezeError("machine.py: no `from .config import` to extend")
    for c in tree.body:
        if isinstance(c, ast.ClassDef) and c.name == "Machine":
            for f in c.body:
                if isinstance(f, ast.FunctionDef) and f.name == "__init__":
                    at = 1 if (f.body and isinstance(f.body[0], ast.Expr)
                               and isinstance(f.body[0].value, ast.Constant)) else 0
                    call = ast.Expr(value=ast.Call(func=ast.Name(id="check_structure",
                                                                 ctx=ast.Load()),
                                                   args=[ast.Name(id="cfg", ctx=ast.Load())],
                                                   keywords=[]))
                    f.body[at:at] = [Note(["# frozen: only the fit's structure runs here"]), call]
                    return
    raise FreezeError("machine.py: no Machine.__init__")


def config_module(sha: str, structure: dict, cfg) -> str:
    lines = [header(sha).rstrip("\n"),
             '"""The fit the frozen package was generated from (generated; see freeze.py).',
             "",
             "STRUCTURE holds every structural field's fitted value: the frozen code has them",
             "built in, so a Config whose structure differs is rejected (check_structure). The",
             "class integers (COST, read through Config.c) and the EA table (EA) stay parameters:",
             "DEFAULT is the fit, and a Config with other integers runs as it would in sim/.",
             '"""',
             "",
             "from __future__ import annotations",
             "",
             "from ..config import Config  # noqa: F401  (sim.config: the class itself)",
             "",
             f'FIT_SHA256 = "{sha}"',
             "",
             "STRUCTURE = {"]
    for k, v in structure.items():
        lines.append(f"    {k!r}: {v!r},")
    lines.append("}")
    lines.append("")
    lines.append("COST = {")
    for cls in sorted(cfg.cost):
        lines.append(f"    {cls!r}: {{" + ", ".join(f"{n!r}: {v!r}" for n, v in
                                                     sorted(cfg.cost[cls].items())) + "},")
    lines.append("}")
    lines.append("")
    lines.append("EA = {" + ", ".join(f"{k!r}: {v!r}" for k, v in sorted(cfg.ea.items())) + "}")
    lines += ["",
              "",
              "def check_structure(cfg) -> None:",
              '    """Raise ValueError unless every structural field of cfg is the fit\'s."""',
              "    bad = [f\"{k}={getattr(cfg, k, None)!r} (fit: {v!r})\" for k, v in STRUCTURE.items()",
              "           if getattr(cfg, k, None) != v or type(getattr(cfg, k, None)) is not type(v)]",
              "    if bad:",
              "        raise ValueError(\"frozen model: the Config's structure is not the fit's \"",
              "                         f\"(fit.json sha256 {FIT_SHA256[:12]}): \" + \", \".join(bad))",
              "",
              "",
              "# The fit: the default Config of the frozen model (sim.config.DEFAULT is the unfitted",
              "# baseline, which this package rejects).",
              'DEFAULT = Config.from_json({**STRUCTURE, "cost": COST, "ea": EA})',
              ""]
    return "\n".join(lines)


class Result:
    def __init__(self):
        self.files: dict[str, str] = {}
        self.unfolded: list = []      # (module, frozen line, sim line, label, value, context)
        self.dropped: list = []
        self.fallbacks: list = []
        self.attr_consts: dict = {}


def generate(fit_path: Path = FIT, sim_dir: Path = SIM) -> Result:
    sha, structure, cfg = load_fit(fit_path)
    sources = {m: Source(m, (sim_dir / f"{m}.py").read_text()) for m in MODULES}
    for s in sources.values():
        mark_methods(s.tree)
    attr_consts: dict = {}
    param_consts: dict = {}
    originals = {m: s.tree for m, s in sources.items()}
    base_attrs = constant_attrs(originals, structure)
    base_params = constant_params(originals, structure)
    base_strs = string_sets(originals)
    str_sets: dict = {}
    for _ in range(10):
        folded, folders = {}, {}
        for m, s in sources.items():
            f = Folder(structure, attr_consts, m, param_consts, str_sets, base_strs)
            folded[m] = ast.Module(body=f.stmts(s.tree.body), type_ignores=[])
            folders[m] = f
        plain = {m: strip_notes(t) for m, t in folded.items()}
        new = {**attr_consts, **constant_attrs(plain, structure, base_attrs)}
        newp = constant_params(plain, structure, base_params)
        for k, v in param_consts.items():
            newp[k] = {**v, **newp.get(k, {})}
        news = string_sets(plain)
        if new == attr_consts and newp == param_consts and news == str_sets:
            break
        attr_consts, param_consts, str_sets = new, newp, news
    else:
        raise FreezeError("attribute propagation did not converge")
    res = Result()
    res.attr_consts = attr_consts
    res.str_sets = {a: v for a, v in str_sets.items() if base_strs.get(a) != v}
    res.param_consts = param_consts
    for t in folded.values():
        drop_dead_aliases(t)
    res.dropped = remove_unused_private(folded)
    _insert_check(folded["machine"])
    for m, s in sources.items():
        orig_ids = {id(x) for x in ast.walk(s.tree)}
        em = Emitter(s, folders[m].stmt_notes, orig_ids)
        text = header(sha) + em.module(folded[m])
        want = ast.dump(strip_notes(folded[m]))
        got = ast.dump(ast.parse(text))
        if want != got:
            raise FreezeError(f"{m}.py: the rendered text is not the folded AST "
                              f"(first difference at {_first_diff(want, got)})")
        leftovers = _structure_reads(ast.parse(text), structure)
        if leftovers:
            raise FreezeError(f"{m}.py: structural reads left: {leftovers[:5]}")
        res.files[f"{m}.py"] = text
        res.unfolded += _surviving(m, folded[m], em, structure)
        res.fallbacks += [(m,) + x for x in em.fallbacks]
    res.files["config.py"] = config_module(sha, structure, cfg)
    return res


def _first_diff(a: str, b: str) -> str:
    k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return f"...{a[max(0, k - 120):k + 80]!r} vs ...{b[max(0, k - 120):k + 80]!r}"


def _structure_reads(tree, structure) -> list:
    return [(x.lineno, x.attr) for x in ast.walk(tree)
            if isinstance(x, ast.Attribute) and x.attr in structure and is_cfg(x.value)]


def _surviving(mod, tree, em, structure) -> list:
    """Literals standing for a structural read that are still in the folded code."""
    out = []

    def visit(stmt_list):
        for s in stmt_list:
            if isinstance(s, Note):
                continue
            for parent in _walk_no_bodies(s):
                for name, value in ast.iter_fields(parent):
                    kids = value if isinstance(value, list) else [value]
                    for k in kids:
                        if isinstance(k, ast.AST) and getattr(k, "_field", None):
                            line = em.line_of.get(id(s))
                            out.append((mod, line and line + HEADER_LINES,
                                        getattr(getattr(s, "_orig", s), "lineno", None),
                                        k._field, const(k)[1], _context(parent, name, k)))
            for b in BODIES:
                v = getattr(s, b, None)
                if isinstance(v, list):
                    if b == "handlers":
                        for h in v:
                            visit(h.body)
                    else:
                        visit(v)

    visit(tree.body)
    return out


def _walk_no_bodies(s):
    todo = [s]
    while todo:
        x = todo.pop()
        yield x
        for name, value in ast.iter_fields(x):
            if name in BODIES and isinstance(value, list) and (not value or isinstance(
                    value[0], (ast.stmt, Note, ast.ExceptHandler))):
                continue
            for k in (value if isinstance(value, list) else [value]):
                if isinstance(k, ast.AST):
                    todo.append(k)


def _context(parent, name, k) -> str:
    if isinstance(parent, ast.Call):
        fn = ast.unparse(parent.func)
        return f"argument of {fn}()"
    if isinstance(parent, ast.keyword):
        return f"keyword {parent.arg}="
    if isinstance(parent, (ast.Assign, ast.AnnAssign)):
        tg = parent.targets[0] if isinstance(parent, ast.Assign) else parent.target
        return f"stored in {ast.unparse(tg)}"
    if isinstance(parent, ast.Compare):
        return f"compared: {ast.unparse(parent)[:70]}"
    if isinstance(parent, ast.BinOp):
        return f"arithmetic: {ast.unparse(parent)[:70]}"
    if isinstance(parent, (ast.Tuple, ast.List)):
        return f"element of {ast.unparse(parent)[:70]}"
    if isinstance(parent, ast.Return):
        return "returned"
    return f"{type(parent).__name__}.{name}: {ast.unparse(parent)[:70]}"


def write(res: Result, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(res.files.items()):
        (out / name).write_text(text)
    for p in sorted(out.glob("*.py")):
        if p.name not in res.files:
            p.unlink()


def check(out: Path = FROZEN) -> int:
    import difflib

    res = generate()
    with tempfile.TemporaryDirectory() as tmp:
        write(res, Path(tmp))
        bad = 0
        names = sorted({p.name for p in Path(tmp).glob("*.py")} | {p.name for p in
                                                                   out.glob("*.py")})
        for name in names:
            a, b = out / name, Path(tmp) / name
            old = a.read_text().splitlines(keepends=True) if a.exists() else []
            new = b.read_text().splitlines(keepends=True) if b.exists() else []
            if old != new:
                bad += 1
                sys.stdout.writelines(list(difflib.unified_diff(
                    old, new, f"checked-in/{name}", f"regenerated/{name}"))[:60])
    print("frozen package matches the fit and sim/" if not bad else
          f"frozen package differs from a fresh generation in {bad} file(s)")
    return 1 if bad else 0


# Report ---------------------------------------------------------------------------------

def loc(text: str) -> tuple[int, int]:
    """(lines, code lines: not blank, not a comment, not in a docstring)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    doc = set()
    tree = ast.parse(text)
    for x in ast.walk(tree):
        if isinstance(x, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = x.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and \
                    isinstance(b[0].value.value, str):
                doc.update(range(b[0].lineno, b[0].end_lineno + 1))
    code = sum(1 for k, ln in enumerate(lines, 1)
               if ln.strip() and not ln.strip().startswith("#") and k not in doc)
    return len(lines), code


def report(res: Result) -> str:
    out = ["module        sim lines  frozen lines   sim code  frozen code"]
    tot = [0, 0, 0, 0]
    for name in sorted(res.files):
        if name == "config.py":
            continue
        a = loc((SIM / name).read_text())
        b = loc(res.files[name])
        tot = [tot[0] + a[0], tot[1] + b[0], tot[2] + a[1], tot[3] + b[1]]
        out.append(f"{name:<13} {a[0]:>9} {b[0]:>13} {a[1]:>10} {b[1]:>12}")
    out.append(f"{'total':<13} {tot[0]:>9} {tot[1]:>13} {tot[2]:>10} {tot[3]:>12}")
    a, b = loc((SIM / "config.py").read_text()), loc(res.files["config.py"])
    out.append(f"{'config.py':<13} {a[0]:>9} {b[0]:>13} {a[1]:>10} {b[1]:>12}  (frozen: generated, "
               "not transformed)")
    out.append("")
    out.append(f"instance attributes folded as constants: "
               + ", ".join(f"{k}={v[0]!r} ({', '.join(f for f, _ in v[1])})"
                           for k, v in sorted(res.attr_consts.items())))
    out.append("parameters folded as constants: " + ", ".join(
        f"{fn}({p}={v[0]!r}: {', '.join(f for f, _ in v[1])})"
        for fn, ps in sorted(res.param_consts.items()) for p, v in sorted(ps.items())))
    out.append("attributes whose possible strings the fold narrowed: " + ", ".join(
        f"{a} -> {{{', '.join(map(repr, sorted(v)))}}}" for a, v in sorted(res.str_sets.items())))
    out.append(f"private functions dropped as unreachable: {', '.join(res.dropped) or 'none'}")
    out.append("")
    out.append("structural values still read as data (frozen file:line, sim line, field = value, "
               "use):")
    for mod, fl, sl, label, value, ctx in dict.fromkeys(res.unfolded):
        out.append(f"  frozen/{mod}.py:{fl}  sim/{mod}.py:{sl}  {label} = {value!r}  {ctx}")
    return "\n".join(out)


# Verify ---------------------------------------------------------------------------------

_RUNS: dict = {}


def _verify_chunk(args):
    family, lo, hi = args
    from .normalize import load_runs, normalize
    from .sim import machine as m0
    from .sim.config import Config
    from .sim.frozen import machine as m1

    m0.FAST_FORWARD = m1.FAST_FORWARD = False
    cfg = Config.fitted()
    if _RUNS.get("family") != family:      # one family's records per worker at a time
        _RUNS.clear()
        _RUNS.update(family=family, runs=load_runs(family))
    runs = _RUNS["runs"][lo:hi]
    out = []
    for rec in runs:
        s = normalize(rec)
        anchor = m0.refresh_anchor(s)
        a, b = _one(m0, s, cfg, anchor), _one(m1, s, cfg, anchor)
        out.append((rec["chain"]["id"], _diff(a, b)))
    return family, out


def _one(mod, s, cfg, anchor):
    log = []
    try:
        n = mod.simulate_normalized(s.chain, cfg, s.chain_base, clock_log=log, refresh=anchor)
    except Exception as e:   # noqa: BLE001 - the error itself is compared
        return ("error", f"{type(e).__name__}: {e}", log)
    return ("ok", n, log)


def _diff(a, b):
    """None when identical, else (clock, key, sim value, frozen value)."""
    if a[0] != b[0] or a[0] == "error" and a[1] != b[1]:
        return (None, "outcome", str(a[1])[:80], str(b[1])[:80])
    if a[0] == "ok":
        na, nb = a[1], b[1]
        for k, (x, y) in enumerate(zip(na.events, nb.events)):
            if x != y:
                return (x.clock, f"events[{k}]", x, y)
        if len(na.events) != len(nb.events):
            return (None, "events (length)", len(na.events), len(nb.events))
        for f in vars(na):
            if getattr(na, f) != getattr(nb, f):
                return (None, f"Normalized.{f}", getattr(na, f), getattr(nb, f))
    for x, y in zip(a[2], b[2]):
        if x != y:
            key = next((k for k in x if x[k] != y.get(k)), None)
            key = key or next(k for k in y if k not in x)
            return (x["t"], f"row.{key}", x.get(key), y.get(key))
    if len(a[2]) != len(b[2]):
        return (None, "rows (length)", len(a[2]), len(b[2]))
    return None


def verify(families=None, jobs: int = 4, chunk: int = 40) -> int:
    from multiprocessing import get_context

    from .families import FAMILIES, UNMODELLED
    from .normalize import load_runs

    fams = [f for f in (families or FAMILIES) if f not in UNMODELLED]
    tasks = []
    counts = {}
    for f in fams:
        n = len(load_runs(f))
        counts[f] = n
        tasks += [(f, lo, min(lo + chunk, n)) for lo in range(0, n, chunk)]
    t0 = time.time()
    found: dict = {f: [] for f in fams}
    done: dict = {f: 0 for f in fams}
    with get_context("spawn").Pool(min(jobs, 8), maxtasksperchild=200) as pool:
        for fam, out in pool.imap_unordered(_verify_chunk, tasks):
            done[fam] += len(out)
            found[fam] += [(rid, d) for rid, d in out if d is not None]
            if done[fam] == counts[fam]:
                bad = sorted(found[fam], key=lambda x: x[0])
                first = (f"first {bad[0][0]}: clock {bad[0][1][0]} {bad[0][1][1]} "
                         f"sim={bad[0][1][2]!r} frozen={bad[0][1][3]!r}" if bad else "")
                print(f"{fam:<5} {counts[fam]:>6} runs  {'identical' if not bad else f'{len(bad)} DIFFER'}"
                      f"  {first}", flush=True)
    total = sum(counts.values())
    nbad = sum(len(v) for v in found.values())
    print(f"{total} runs over {len(fams)} families: "
          f"{'all identical' if not nbad else f'{nbad} differ'} ({time.time() - t0:.0f} s)")
    return 1 if nbad else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m validation.v35s.chains.freeze",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=FROZEN, help="output directory (default sim/frozen)")
    p.add_argument("--check", action="store_true", help="regenerate and diff; exit 1 on drift")
    p.add_argument("--report", action="store_true", help="print sizes and unfolded reads")
    p.add_argument("--verify", action="store_true", help="sim/ vs sim/frozen/ over the corpus")
    p.add_argument("--family", nargs="+", help="--verify: these families only")
    p.add_argument("--jobs", type=int, default=4, help="--verify: worker processes (max 8)")
    args = p.parse_args(argv)
    if args.check:
        return check(args.out)
    if args.verify:
        return verify(args.family, args.jobs)
    res = generate()
    if args.report:
        print(report(res))
        return 0
    write(res, args.out)
    print(f"wrote {len(res.files)} files to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
