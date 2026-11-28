#!/usr/bin/env python3
"""ss_inventory.py - mechanical inventory of every state-holding element of the V35S core v2.

What it does
------------
The synthesizable core (top module v35_top; the file list of fpga/v35s/build_sim.sh
`direct v35`) is elaborated by Verilator (`--xml-only`: the AST after parameter resolution,
one <module> per parameterisation, with the instance tree in <cells>) twice: once with
`-DSYNTHESIS` and once without. In each elaboration, per module:

  * every variable that is the target of a non-blocking assignment (<assigndly>) inside an
    edge-clocked always (<always> with <sentree>/<senitem edgeType=POS|NEG>) is a state
    element. The target is found through part selects (<sel>: packed slices and struct
    members), array element writes (<arraysel>: memories) and concatenations;
  * every variable loaded by $readmemh/$readmemb and never written is a CONST memory (ROM);
  * blocking assignments in clocked blocks (to anything that is not an integer loop
    variable), non-blocking assignments outside clocked blocks, clocks other than
    `posedge clock`, and variables written only by `initial` are reported as WARNINGS (they
    are the shapes this method does not turn into inventory rows by itself; a non-loop
    blocking target IS added to the inventory, marked `blocking`).

Width and depth come from Verilator's type table (packed structs and enums resolved; the
unpacked dimensions multiplied into the depth). The enable class is read from the guards (the
enclosing `if` conditions, split into their AND terms) of every non-reset write: a term that
is `ce_a` / `ce_b` (followed through instance port connections up to v35_top) gives the
class; a write under no guard at all is `raw clock`; anything else is `other: <outermost
guard>`. A write in the `!reset_n` branch is a reset write; its value is recorded if constant.
Declaration initialisers (`logic x = 0`) are recorded as `init=`.

The hierarchical path is computed by walking <cells> from v35_top. An element present only
in the elaboration without `-DSYNTHESIS` is SIMONLY (the `ifndef SYNTHESIS` regions: the
+v35_chk shadow registers, v35_trace). The deliverable inventory is the SYNTHESIS set.

Cross-check: a plain textual scan of the sources (comments and strings stripped, `ifdef
SYNTHESIS resolved the same two ways, split at module ... endmodule) collects every
identifier that stands on the left of a statement-level `<=`; names found by one method and
not by the other are listed, per module.

Modes
-----
  ss_inventory.py [--root REPO] [--out DIR] [--work DIR]
        writes DIR/ss_inventory.tsv (path, module, name, width, depth, bits, enable, reset,
        simonly; sorted by path), DIR/ss_inventory_simonly.tsv, prints per-module totals,
        instance multiplicities, the cross-check and the warnings.
  ss_inventory.py --template [FILE]
        emits the class file skeleton (module, name, bits, class, note), class `?`
        (ROMs pre-set to CONST and sim-only elements to SIMONLY: both are mechanical).
  ss_inventory.py --check CLASSFILE
        exit 1, listing them, if an inventory element (module + declared name) is missing
        from CLASSFILE, CLASSFILE names an element that no longer exists, the bits differ,
        the class is not one of SAVED/DERIVED/IDLE/HISTORY/CONST/SIMONLY, a sim-only
        element is not SIMONLY (or the reverse), or the two methods disagree. Prints the
        total SAVED bits (bits x the number of instances of the module under v35_top).

Exit status: 0 clean, 1 check failed, 2 tool failure (Verilator did not elaborate).

Wiring into validation/v35s/chains/test_v35_struct.py (not done here; a sketch)
------------------------------------------------------------------------------
Move this file next to the test (or keep it and import by path), commit the class file as
e.g. fpga/v35s/core/v35/v35_ss_class.tsv, and add:

    import ss_inventory                       # this file
    class SaveStateInventory(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.inv = ss_inventory.build(REPO_ROOT)        # two Verilator runs, < 1 s
        def test_every_register_is_classified(self):
            problems, saved = ss_inventory.check(self.inv, CLASS_FILE)
            self.assertEqual(problems, [], "\\n".join(problems))
        def test_both_methods_agree(self):
            self.assertEqual(ss_inventory.crosscheck(self.inv), [])

`build()` needs only `verilator` on PATH (skipTest if shutil.which fails, as the other
structural tests do for their tools). A new register in the core then fails
test_every_register_is_classified until a row is added to the class file.

Stdlib only.
"""
import argparse
import collections
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

TOP = "v35_top"
V35 = "fpga/v35s/core/v35"
CORE = "fpga/v35s/core"
SOURCES = [V35 + "/" + f for f in (
    "v35_front_pkg.sv", "v35_pkg.sv", "v35_fn_pkg.sv", "v35_bus.sv", "v35_queue.sv",
    "v35_loader.sv", "v35_useq.sv", "v35_ea.sv", "v35_eu.sv", "v35_regram.sv",
    "v35_trace.sv", "v35_ss.sv")] + [CORE + "/v35_sfr.sv", CORE + "/v35_refresh.sv", V35 + "/v35_top.sv"]
INCDIRS = [CORE, V35]
CLASSES = ("SAVED", "DERIVED", "IDLE", "HISTORY", "CONST", "SIMONLY")
COLS = ("path", "module", "name", "width", "depth", "bits", "enable", "reset", "simonly")

STMT_TAGS = {"assign", "assigndly", "if", "case", "begin", "while", "jumpblock", "jumpgo",
             "jumplabel", "display", "stop", "finish", "fopen", "fclose", "fflush",
             "stmtexpr", "readmem", "writemem", "sformat", "assignw", "contassign"}


# ----------------------------------------------------------------------------- Verilator

def run_verilator(root, work, synthesis):
    tag = "syn" if synthesis else "sim"
    out = os.path.join(work, tag + ".xml")
    cmd = ["verilator", "--xml-only", "--xml-output", out,
           "--Mdir", os.path.join(work, "md_" + tag),
           "-Wno-fatal", "-Wno-lint", "-Wno-style", "--timing", "--timescale", "1ns/1ps",
           "--top-module", TOP] + ["-I" + d for d in INCDIRS]
    if synthesis:
        cmd.append("-DSYNTHESIS")
    cmd += SOURCES
    p = subprocess.run(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    if p.returncode != 0 or not os.path.exists(out):
        sys.stderr.write(p.stdout)
        raise RuntimeError("verilator failed: " + " ".join(cmd))
    return out


def const_int(name):
    """Verilator const text (8'hff, 32'sh3) -> int, or None."""
    m = re.match(r"(\d+)'s?([hbdo])([0-9a-fA-F_xzXZ?]+)$", name)
    if not m:
        return None
    try:
        return int(m.group(3).replace("_", ""), {"h": 16, "b": 2, "d": 10, "o": 8}[m.group(2)])
    except ValueError:
        return None


class Types:
    INTW = {"int": 32, "integer": 32, "shortint": 16, "longint": 64, "byte": 8, "bit": 1,
            "logic": 1, "reg": 1, "time": 64}

    def __init__(self, typetable):
        self.t = {e.get("id"): e for e in typetable}

    def dims(self, tid):
        """(packed width, unpacked depth) of a dtype id."""
        e = self.t.get(tid)
        if e is None:
            return (0, 1)
        k = e.tag
        if k == "basicdtype":
            if e.get("left") is not None:
                return (abs(int(e.get("left")) - int(e.get("right"))) + 1, 1)
            return (self.INTW.get(e.get("name"), 0), 1)
        if k in ("refdtype", "enumdtype", "memberdtype", "constdtype"):
            return self.dims(e.get("sub_dtype_id"))
        if k in ("structdtype", "uniondtype"):
            ws = [self.dims(m.get("sub_dtype_id"))[0] for m in e.findall("memberdtype")]
            return ((max(ws) if k == "uniondtype" else sum(ws)) if ws else 0, 1)
        if k in ("unpackarraydtype", "packarraydtype"):
            rng = e.find("range")
            a, b = (const_int(c.get("name")) for c in rng)
            n = abs(a - b) + 1
            w, d = self.dims(e.get("sub_dtype_id"))
            return (w, d * n) if k == "unpackarraydtype" else (w * n, d)
        return (0, 1)


def pos(e):
    loc = (e.get("loc") or "a,0,0").split(",")
    return (int(loc[1]), int(loc[2]))


BINOPS = {"and": "&", "or": "|", "xor": "^", "eq": "==", "neq": "!=", "add": "+", "sub": "-",
          "lt": "<", "gt": ">", "lte": "<=", "gte": ">=", "lts": "<", "gts": ">",
          "ltes": "<=", "gtes": ">=", "shiftl": "<<", "shiftr": ">>", "logand": "&&",
          "logor": "||", "eqcase": "===", "neqcase": "!==", "mul": "*", "muls": "*"}
UNOPS = {"not": "!", "lognot": "!", "negate": "-", "redor": "|", "redand": "&", "redxor": "^"}


def render(e):
    """Compact source-like text of an expression node (operands in source order)."""
    t = e.tag
    if t == "varref":
        return e.get("name")
    if t == "const":
        return e.get("name")
    k = list(e)
    if t in UNOPS and len(k) == 1:
        return UNOPS[t] + render(k[0])
    if t in BINOPS and len(k) == 2:
        a, b = sorted(k, key=pos)
        return "(" + render(a) + " " + BINOPS[t] + " " + render(b) + ")"
    if t == "sel" and len(k) == 3:
        lsb, w = const_int(k[1].get("name") or ""), const_int(k[2].get("name") or "")
        if lsb is not None and w is not None:
            return render(k[0]) + ("[%d]" % lsb if w == 1 else "[%d:%d]" % (lsb + w - 1, lsb))
        return render(k[0]) + "[" + render(k[1]) + "+:" + render(k[2]) + "]"
    if t == "arraysel" and len(k) == 2:
        return render(k[0]) + "[" + render(k[1]) + "]"
    if t == "cond" and len(k) == 3:
        return "(" + render(k[0]) + " ? " + render(k[1]) + " : " + render(k[2]) + ")"
    if t == "concat":
        return "{" + ", ".join(render(c) for c in k) + "}"
    if t in ("extend", "extends", "ccast") and len(k) == 1:
        return render(k[0])
    if t == "funcref":
        return e.get("name") + "(" + ", ".join(render(c) for c in k) + ")"
    if t == "arg" and len(k) == 1:
        return render(k[0])
    return t + "(" + ", ".join(render(c) for c in k) + ")"


def lhs_vars(e):
    """Variable names a (possibly selected / concatenated) assignment target writes."""
    if e.tag == "varref":
        return [e.get("name")]
    if e.tag == "concat":
        return [n for c in e for n in lhs_vars(c)]
    if e.tag in ("sel", "arraysel", "structsel", "membersel", "slicesel") and len(e):
        return lhs_vars(e[0])
    return []


def conjuncts(e, pol, out):
    """Split a guard into AND terms: [(node, polarity)]."""
    if e.tag in ("not", "lognot"):
        conjuncts(e[0], not pol, out)
    elif (e.tag in ("and", "logand") and pol) or (e.tag in ("or", "logor") and not pol):
        for c in sorted(e, key=pos):
            conjuncts(c, pol, out)
    elif e.tag in ("redor",) and len(e) == 1 and e[0].tag == "varref":
        conjuncts(e[0], pol, out)
    else:
        out.append((e, pol))


def disjuncts(e, pol, out):
    """Split a guard term into OR terms: [(node, polarity)]."""
    if e.tag in ("not", "lognot"):
        disjuncts(e[0], not pol, out)
    elif (e.tag in ("or", "logor") and pol) or (e.tag in ("and", "logand") and not pol):
        for c in sorted(e, key=pos):
            disjuncts(c, pol, out)
    else:
        out.append((e, pol))


def reset_active(n, p):
    """Is the term (node, polarity) `reset asserted`?"""
    return n.tag == "varref" and is_reset_name(n.get("name")) and \
        p != n.get("name").endswith(("_n", "n", "_l"))


def is_reset_name(n):
    return bool(re.search(r"(^|_)(reset|rst)(_n|n|_l)?$", n))


class Write:
    __slots__ = ("guards", "reset", "rhs", "full", "clock", "blocking")


class Module:
    """One elaborated module: its variables, state writes, ROMs, instances."""

    def __init__(self, m, types):
        self.name = m.get("name")
        self.orig = m.get("origName") or self.name
        self.vars = {}       # name -> var element
        self.local = set()   # block-local variables (declared inside a procedural block)
        self.ports_in = set()
        self.writes = collections.defaultdict(list)   # name -> [Write]
        self.roms = set()
        self.init = {}       # name -> constant initial value text
        self.initonly = set()
        self.instances = {}  # instance name -> {port: expr element}
        self.warn = []
        self.types = types
        other_written = set()
        self._collect_vars(m, "", False)
        for child in m:
            self._top_item(child, other_written)
        self.roms -= set(self.writes)
        self.roms -= other_written
        self.initonly = set(n for n in set(self.init) - set(self.writes) - other_written
                            - self.roms if not n.startswith("unused") and
                            self.vars[n].get("vartype") not in ("integer", "int", "genvar"))

    def _collect_vars(self, node, prefix, procedural):
        for c in node:
            if c.tag == "var":
                n = c.get("name")
                self.vars[n] = c
                if procedural:
                    self.local.add(n)
                if c.get("dir") == "input":
                    self.ports_in.add(n)
            elif c.tag == "func":
                continue
            elif c.tag in ("always", "initial", "initialstatic", "final"):
                self._collect_vars(c, prefix, True)
            else:
                self._collect_vars(c, prefix, procedural)

    def _top_item(self, c, other_written):
        if c.tag == "begin":                      # generate block
            for g in c:
                self._top_item(g, other_written)
        elif c.tag == "instance":
            self.instances[c.get("name")] = (c.get("defName"),
                                              {p.get("name"): p[0] for p in c.findall("port")
                                               if len(p)})
        elif c.tag == "always":
            st = c.find("sentree")
            edges = [s for s in (st if st is not None else []) if s.get("edgeType") in
                     ("POS", "NEG", "BOTH")]
            if edges:
                clk = " or ".join({"POS": "posedge ", "NEG": "negedge ", "BOTH": "edge "}
                                  [s.get("edgeType")] + render(s[0]) for s in edges)
                self.loopvars = set()      # `for (i = 0; ...)`: an assign, then its while
                for node in c.iter():
                    kids = list(node)
                    for x, y in zip(kids, kids[1:]):
                        if x.tag == "assign" and y.tag == "while":
                            self.loopvars.update(lhs_vars(x[-1]))
                for b in c:
                    if b.tag != "sentree":
                        self._stmt(b, [], clk)
            else:
                for a in c.iter("assigndly"):
                    for n in lhs_vars(a[-1]):
                        other_written.add(n)
                        self.warn.append("non-blocking assignment to %s outside a clocked "
                                         "always (line %d)" % (n, pos(a)[0]))
                for a in c.iter("assign"):
                    other_written.update(lhs_vars(a[-1]))
        elif c.tag in ("contassign", "assignw", "alias"):
            other_written.update(lhs_vars(c[-1]))
        elif c.tag in ("initial", "initialstatic"):
            for r in c.iter("readmem"):
                self.roms.update(lhs_vars(r[-1]))
            for a in list(c.iter("assign")) + list(c.iter("assigndly")):
                for n in lhs_vars(a[-1]):
                    if n in self.local:
                        continue
                    if a[0].tag == "const" and a[-1].tag == "varref" and n not in self.init:
                        self.init[n] = a[0].get("name")
                    else:
                        self.init.setdefault(n, "(not one constant)")

    def _stmt(self, s, guards, clk):
        t = s.tag
        if t in ("assigndly", "assign"):
            for n in lhs_vars(s[-1]):
                if t == "assign":
                    if n in self.local or n in self.loopvars:
                        continue        # block temporaries, loop variables
                    if not any(w.blocking for w in self.writes[n]):
                        self.warn.append("blocking assignment to %s in a clocked always "
                                         "(first at line %d)" % (n, pos(s)[0]))
                w = Write()
                w.guards = list(guards)
                w.rhs = s[0]
                w.full = s[-1].tag == "varref"
                w.clock = clk
                w.blocking = t == "assign"
                w.reset = False
                self.writes[n].append(w)
        elif t == "if":
            k = list(s)
            self._branch(k[1:2], guards + [(k[0], True)], clk)
            self._branch(k[2:3], guards + [(k[0], False)], clk)
        elif t == "case":
            k = list(s)
            sel = render(k[0])
            for item in k[1:]:
                labs = [c for c in item if c.tag not in STMT_TAGS]
                lab = ET.Element("caselabel")
                lab.set("name", "case " + sel + ": " +
                        (", ".join(render(c) for c in labs) or "default"))
                for c in item:
                    if c.tag in STMT_TAGS:
                        self._stmt(c, guards + [(lab, True)], clk)
        else:
            for c in s:
                if c.tag in STMT_TAGS:
                    self._stmt(c, guards, clk)

    def _branch(self, nodes, guards, clk):
        for n in nodes:
            self._stmt(n, guards, clk)


def gtext(node, pol):
    s = node.get("name") if node.tag == "caselabel" else render(node)
    return s if pol else "!" + s


class Design:
    """One elaboration (with or without SYNTHESIS): modules, hierarchy, elements."""

    def __init__(self, xmlfile):
        root = ET.parse(xmlfile).getroot()
        nl = root.find("netlist")
        self.types = Types(nl.find("typetable"))
        self.mods = {m.get("name"): Module(m, self.types) for m in nl.findall("module")}
        cells = root.find("cells")
        self.inst = {}       # path -> (module, parent path, instance name)

        def walk(c, parent):
            p = c.get("hier")
            self.inst[p] = (c.get("submodname"), parent, c.get("name"))
            for k in c.findall("cell"):
                walk(k, p)
        for c in cells.findall("cell"):
            walk(c, None)
        self.elements = self._elements()

    def resolve(self, path, node):
        """Follow a guard term that is an input port up through the instance connections."""
        text = render(node)
        while node.tag == "varref":
            modname, parent, iname = self.inst[path]
            if parent is None or node.get("name") not in self.mods[modname].ports_in:
                break
            conn = self.mods[self.inst[parent][0]].instances.get(iname, (None, {}))[1]
            nxt = conn.get(node.get("name"))
            if nxt is None:
                break
            node, path = nxt, parent
            text = render(node)
        return node, text

    def _classify(self, path, mod, writes):
        """(enable text, reset text) for the writes of one variable."""
        classes, others, rvals, clocks = [], [], [], set()
        any_reset = rst_load = False
        for w in writes:
            clocks.add(w.clock)
            terms = []
            for g, pol in w.guards:
                if g.tag == "caselabel":
                    terms.append((g, pol))
                    continue
                conjuncts(g, pol, terms)
            reset = False
            live = []
            split = []
            for n, p in terms:              # `if (!reset_n || ce_a)`: loads in reset too
                dj = []
                if n.tag != "caselabel":
                    disjuncts(n, p, dj)
                rest = [(x, q) for x, q in dj if not reset_active(x, q)]
                if len(dj) > 1 and len(rest) < len(dj):
                    rst_load = True
                    if len(rest) == 1:
                        split.append(rest[0])
                    elif all(q for _x, q in rest):
                        grp = ET.Element("or")
                        grp.extend(x for x, _q in rest)
                        split.append((grp, True))
                    else:
                        split.append((n, p))
                else:
                    split.append((n, p))
            for n, p in split:
                if n.tag == "varref" and is_reset_name(n.get("name")):
                    active_low = n.get("name").endswith(("_n", "n", "_l"))
                    if p != active_low:
                        reset = True
                    continue            # the non-reset side: not an enable
                live.append((n, p))
            if reset:
                any_reset = True
                v = w.rhs.get("name") if w.rhs.tag == "const" else "expr:" + render(w.rhs)
                rvals.append(v if w.full else "part:" + v)
                continue
            ce = set()
            for n, p in live:
                if not p or n.tag == "caselabel":
                    continue
                rn, text = self.resolve(path, n)
                names = set(re.findall(r"\bce_[ab]\b", text))
                if rn.tag == "varref" and names:
                    ce |= names
                elif rn.tag in ("or", "logor") and names == {"ce_a", "ce_b"} and \
                        all(c.tag == "varref" for c in rn):
                    ce |= names
            if ce:
                classes.append(ce)
            elif not live:
                classes.append({"raw clock"})
            else:
                n, p = live[0]
                others.append(gtext(n, p) if n.tag == "caselabel"
                              else ("" if p else "!") + self.resolve(path, n)[1])
        ce = set().union(*classes) if classes else set()
        parts = []
        if ce & {"ce_a", "ce_b"}:
            parts.append("|".join(sorted(ce & {"ce_a", "ce_b"})))
        if "raw clock" in ce:
            parts.append("raw clock")
        if others:
            uniq = list(collections.OrderedDict.fromkeys(others))
            txt = " ; ".join(uniq[:3]) + (" ; ...(%d)" % len(uniq) if len(uniq) > 3 else "")
            parts.append("other: " + txt[:160])
        if not parts:
            parts.append("reset only")
        extra = clocks - {"posedge clock"}
        if extra:
            parts.append("CLOCK " + ",".join(sorted(extra)))
        if any(w.blocking for w in writes):
            parts.append("blocking")
        en = " + ".join(parts)
        if any_reset:
            u = list(collections.OrderedDict.fromkeys(rvals))
            rs = "reset=" + (u[0] if len(u) == 1 else "{" + ", ".join(u[:6]) +
                             (", ..." if len(u) > 6 else "") + "}")
        else:
            rs = "none"
        if rst_load:
            rs = ("" if rs == "none" else rs + "; ") + "loads in reset (enable | !reset_n)"
        return en, rs

    def _elements(self):
        out = {}
        for path, (modname, _parent, _iname) in self.inst.items():
            mod = self.mods[modname]
            rel = path[len(TOP) + 1:] if path != TOP else ""
            names = sorted(set(mod.writes) | mod.roms)
            for n in names:
                v = mod.vars.get(n)
                width, depth = self.types.dims(v.get("dtype_id")) if v is not None else (0, 1)
                if n in mod.roms:
                    en, rs = "CONST ($readmem)", "none"
                else:
                    en, rs = self._classify(path, mod, mod.writes[n])
                    if n in mod.init:
                        rs = ("" if rs == "none" else rs + "; ") + "init=" + mod.init[n]
                    elif v is not None and v.find("const") is not None:
                        rs = ("" if rs == "none" else rs + "; ") + "init=" + \
                            v.find("const").get("name")
                p = (rel + "." if rel else "") + n
                out[p] = dict(path=p, module=mod.orig, name=n, width=width, depth=depth,
                              bits=width * depth, enable=en, reset=rs, simonly="",
                              const=n in mod.roms)
        return out


# ---------------------------------------------------------------------- the textual scan

def preprocess(text, defines):
    """Strip comments and strings; resolve `ifdef / `ifndef / `elsif / `else / `endif."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    text = re.sub(r'"(\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"//[^\n]*", "", text)
    defs = set(defines)
    out, stack = [], []          # stack of [active, taken]
    for line in text.split("\n"):
        m = re.match(r"\s*`(ifdef|ifndef|elsif|else|endif)\b\s*(\w+)?", line)
        active = all(s[0] for s in stack)
        if m:
            d, a = m.group(1), m.group(2)
            if d in ("ifdef", "ifndef"):
                c = (a in defs) == (d == "ifdef")
                stack.append([c, c])
            elif d == "elsif":
                c = (a in defs) and not stack[-1][1]
                stack[-1][0] = c
                stack[-1][1] = stack[-1][1] or c
            elif d == "else":
                stack[-1][0] = not stack[-1][1]
                stack[-1][1] = True
            else:
                stack.pop()
            out.append("")
            continue
        if active:
            m = re.match(r"\s*`define\s+(\w+)", line)
            if m:
                defs.add(m.group(1))
            out.append(line)
        else:
            out.append("")
    return "\n".join(out)


LHS_TAIL = re.compile(r"(\{[^{};]*\}|[A-Za-z_]\w*(?:\s*(?:\[[^\[\];]*(?:\[[^\[\];]*\][^\[\];]*)*\]"
                      r"|\.\s*[A-Za-z_]\w*))*)\s*$")


def text_scan(root, defines):
    """{module: set of names on the left of a statement-level `<=`}."""
    res = {}
    for f in SOURCES:
        with open(os.path.join(root, f)) as fh:
            src = preprocess(fh.read(), defines)
        for mm in re.finditer(r"\bmodule\s+(\w+)(.*?)\bendmodule\b", src, flags=re.S):
            name, body = mm.group(1), mm.group(2)
            depth, d = [], 0
            for ch in body:
                depth.append(d)
                if ch == "(":
                    d += 1
                elif ch == ")":
                    d -= 1
            found = res.setdefault(name, set())
            for m in re.finditer(r"<=", body):
                i = m.start()
                if depth[i] > 0 or body[i - 1:i] == "<" or body[i + 2:i + 3] == "=":
                    continue                   # a comparison in parentheses, <<=, <==
                seg = body[max(0, i - 400):i]
                lm = LHS_TAIL.search(seg)
                if not lm:
                    continue
                before = seg[:lm.start()].rstrip()
                if before and not re.search(r"(;|\)|\bbegin|\belse|:|\bend\w*)$", before):
                    continue                   # an operand of an expression, not a target
                lhs = lm.group(1)
                if lhs.startswith("{"):
                    parts, lvl, cur = [], 0, ""
                    for ch in lhs[1:-1]:
                        if ch in "[(":
                            lvl += 1
                        elif ch in "])":
                            lvl -= 1
                        if ch == "," and lvl == 0:
                            parts.append(cur)
                            cur = ""
                        else:
                            cur += ch
                    parts.append(cur)
                else:
                    parts = [lhs]
                for p in parts:
                    im = re.match(r"\s*([A-Za-z_]\w*)", p)
                    if im:
                        found.add(im.group(1))
    return res


# ------------------------------------------------------------------------------- the API

class Inventory:
    pass


def build(root, work=None):
    """Elaborate both ways; return an Inventory (syn / sim element dicts, text scans)."""
    tmp = None
    if work is None:
        tmp = tempfile.TemporaryDirectory(prefix="ss_inv_")
        work = tmp.name
    os.makedirs(work, exist_ok=True)
    inv = Inventory()
    inv.root = root
    inv.syn = Design(run_verilator(root, work, True))
    inv.sim = Design(run_verilator(root, work, False))
    inv.elements = inv.syn.elements                       # path -> row
    inv.simonly = {p: dict(r, simonly="SIMONLY") for p, r in inv.sim.elements.items()
                   if p not in inv.syn.elements}
    inv.changed = [p for p, r in inv.syn.elements.items() if p in inv.sim.elements and
                   (r["bits"], r["module"]) != (inv.sim.elements[p]["bits"],
                                                inv.sim.elements[p]["module"])]
    inv.gone = [p for p in inv.syn.elements if p not in inv.sim.elements]
    inv.text = {True: text_scan(root, {"SYNTHESIS"}), False: text_scan(root, set())}
    if tmp:
        tmp.cleanup()
    return inv


def crosscheck(inv, notes=None):
    """Names found by one method and not the other: list of text lines (empty = agree).
    Modules in the file list that are not instantiated under v35_top (v35_trace: the harness
    instantiates it) are no disagreement; their textual names go to `notes` if given."""
    out = []
    for syn, design in ((True, inv.syn), (False, inv.sim)):
        tag = "SYNTHESIS" if syn else "no SYNTHESIS"
        ver = collections.defaultdict(set)
        used = set(mn for mn, _p, _i in design.inst.values())
        for m in design.mods.values():
            if m.name in used:
                ver[m.orig] |= set(n for n, ws in m.writes.items()
                                   if any(not w.blocking for w in ws))
        txt = inv.text[syn]
        for mod in sorted(set(ver) | set(txt)):
            if mod not in ver:
                if txt[mod] and notes is not None:
                    notes.append("[%s] %s: module not under %s; textual names: %s"
                               % (tag, mod, TOP, " ".join(sorted(txt[mod]))))
                continue
            a, b = ver[mod], txt.get(mod, set())
            if a - b:
                out.append("[%s] %s: Verilator only: %s" % (tag, mod, " ".join(sorted(a - b))))
            if b - a:
                out.append("[%s] %s: textual only: %s" % (tag, mod, " ".join(sorted(b - a))))
    return out


def by_key(rows):
    """{(module, name): [bits set, instance count, const]} over a path -> row dict."""
    d = {}
    for r in rows.values():
        e = d.setdefault((r["module"], r["name"]), [set(), 0, r["const"]])
        e[0].add(r["bits"])
        e[1] += 1
    return d


def template_rows(inv):
    rows = []
    syn = by_key(inv.elements)
    for keyed, cls in ((syn, "?"), (by_key(inv.simonly), "SIMONLY")):
        for (mod, name), (bits, n, const) in sorted(keyed.items()):
            if cls == "SIMONLY" and (mod, name) in syn:
                continue
            note = "" if n == 1 else "x%d instances" % n
            rows.append((mod, name, "/".join(str(b) for b in sorted(bits)),
                         "CONST" if const and cls == "?" else cls, note))
    return rows


def check(inv, classfile):
    """(problems, saved_bits): problems is a list of text lines; empty means pass."""
    syn, simo = by_key(inv.elements), by_key(inv.simonly)
    simo = {k: v for k, v in simo.items() if k not in syn}
    cls = {}
    problems = []
    with open(classfile) as fh:
        for ln, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            f = line.split("\t")
            if f[0] == "module" and len(f) > 1 and f[1] == "name":
                continue
            if len(f) < 4:
                problems.append("%s:%d: fewer than 4 columns" % (classfile, ln))
                continue
            key = (f[0], f[1])
            if key in cls:
                problems.append("%s:%d: %s.%s listed twice" % (classfile, ln, f[0], f[1]))
            cls[key] = (f[2], f[3], ln)
    saved = 0
    for key, (bits, n, const) in sorted(list(syn.items()) + list(simo.items())):
        who = "%s.%s" % key
        want = "/".join(str(b) for b in sorted(bits))
        if key not in cls:
            problems.append("unclassified: %s (%s bits, %d instance%s)"
                            % (who, want, n, "" if n == 1 else "s"))
            continue
        cbits, c, ln = cls[key]
        if cbits != want:
            problems.append("bits differ: %s is %s, class file line %d says %s"
                            % (who, want, ln, cbits))
        if c not in CLASSES:
            problems.append("bad class: %s is '%s' (line %d)" % (who, c, ln))
        elif (key in simo) != (c == "SIMONLY"):
            problems.append("%s: class %s but the element is %s"
                            % (who, c, "sim-only" if key in simo else "synthesized"))
        elif const and c != "CONST" and key in syn:
            problems.append("%s: a $readmem ROM never written must be CONST, not %s" % (who, c))
        if c == "SAVED" and key in syn:
            saved += sum(r["bits"] for r in inv.elements.values()
                         if (r["module"], r["name"]) == key)
    for key in sorted(cls):
        if key not in syn and key not in simo:
            problems.append("stale: %s.%s (line %d) is no state element of the core"
                            % (key[0], key[1], cls[key][2]))
    for line in crosscheck(inv):
        problems.append("methods disagree: " + line)
    return problems, saved


# ---------------------------------------------------------------------------------- main

def write_tsv(fn, rows):
    with open(fn, "w") as fh:
        fh.write("\t".join(COLS) + "\n")
        for p in sorted(rows):
            r = rows[p]
            fh.write("\t".join(str(r[c]) if c != "simonly" else (r[c] or "no")
                               for c in COLS) + "\n")


def totals(rows, title):
    print(title)
    per = collections.OrderedDict()
    for p in sorted(rows):
        r = rows[p]
        inst = p.rsplit(".", 1)[0] if "." in p else "(top)"
        e = per.setdefault((inst, r["module"]), [0, 0, 0, 0])
        e[0] += 1
        e[1] += r["bits"]
        if r["const"]:
            e[2] += 1
            e[3] += r["bits"]
    print("  %-14s %-12s %8s %8s %12s %10s" % ("instance", "module", "elements", "bits",
                                                "of it CONST", "CONST bits"))
    te = tb = tc = tcb = 0
    for (inst, mod), (n, b, c, cb) in per.items():
        print("  %-14s %-12s %8d %8d %12d %10d" % (inst, mod, n, b, c, cb))
        te, tb, tc, tcb = te + n, tb + b, tc + c, tcb + cb
    print("  %-14s %-12s %8d %8d %12d %10d" % ("TOTAL", "", te, tb, tc, tcb))
    print("  (state without the CONST ROMs: %d elements, %d bits)" % (te - tc, tb - tcb))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.getcwd(), help="repository root (default: cwd)")
    ap.add_argument("--out", default=here, help="output directory (default: beside the script)")
    ap.add_argument("--work", default=None, help="keep the Verilator XML here (default: temp)")
    ap.add_argument("--check", metavar="CLASSFILE")
    ap.add_argument("--template", nargs="?", const="-", metavar="FILE")
    a = ap.parse_args()
    try:
        inv = build(a.root, a.work)
    except (RuntimeError, OSError, ET.ParseError) as e:
        sys.stderr.write("ss_inventory: %s\n" % e)
        return 2

    if a.template is not None:
        fh = sys.stdout if a.template == "-" else open(a.template, "w")
        fh.write("module\tname\tbits\tclass\tnote\n")
        for r in template_rows(inv):
            fh.write("\t".join(r) + "\n")
        if fh is not sys.stdout:
            fh.close()
        return 0

    if a.check:
        problems, saved = check(inv, a.check)
        for p in problems:
            print(p)
        print("SAVED bits (x instances): %d (%d bytes)" % (saved, (saved + 7) // 8))
        print("check: %s" % ("FAIL, %d problem(s)" % len(problems) if problems else "ok"))
        return 1 if problems else 0

    write_tsv(os.path.join(a.out, "ss_inventory.tsv"), inv.elements)
    write_tsv(os.path.join(a.out, "ss_inventory_simonly.tsv"), inv.simonly)
    totals(inv.elements, "SYNTHESIS inventory, per instance:")
    totals(inv.simonly, "SIMONLY elements (present only without -DSYNTHESIS), per instance:")
    print("instances under %s:" % TOP)
    cnt = collections.Counter()
    for path, (modname, _p, _i) in sorted(inv.syn.inst.items()):
        m = inv.syn.mods[modname]
        cnt[m.orig] += 1
        print("  %-22s %s%s" % (path, m.orig, "" if m.name == m.orig else "  (" + m.name + ")"))
    print("  multiplicity > 1: " + (", ".join("%s x%d" % kv for kv in sorted(cnt.items())
                                              if kv[1] > 1) or "none"))
    simmods = set(inv.sim.inst) - set(inv.syn.inst)
    if simmods:
        print("  instances only without SYNTHESIS: " + ", ".join(sorted(simmods)))
    for k, v in sorted(by_key(inv.elements).items()):
        if len(v[0]) > 1:
            print("  NOTE %s.%s has different bits between parameterisations: %s"
                  % (k[0], k[1], sorted(v[0])))
    if inv.changed:
        print("elements whose bits differ with/without SYNTHESIS: " + " ".join(inv.changed))
    if inv.gone:
        print("elements present only WITH SYNTHESIS: " + " ".join(inv.gone))
    notes = []
    cc = crosscheck(inv, notes)
    print("cross-check against the textual scan: %s" % ("agree" if not cc else ""))
    for line in cc + notes:
        print("  " + line)
    print("warnings (shapes outside the non-blocking-in-clocked-always rule):")
    nw = 0
    for tag, d in (("SYNTHESIS", inv.syn), ("no SYNTHESIS", inv.sim)):
        for m in d.mods.values():
            for w in sorted(set(m.warn)):
                print("  [%s] %s: %s" % (tag, m.name, w))
                nw += 1
            if m.initonly:
                print("  [%s] %s: written only by an initial (constants, not listed): %s"
                      % (tag, m.name, " ".join(sorted(m.initonly))))
                nw += 1
    if not nw:
        print("  none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
