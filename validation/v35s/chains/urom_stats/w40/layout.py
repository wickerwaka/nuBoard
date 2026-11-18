"""The 40-bit microword layout L40 (w40-layout.md section 2): fit test, encoder, decoder.

    39..35 SEQ   5   sequencing and condition in one code (SEQC below)
    34..26 K     9   e f nb bi vk ro rl[2] flush          raw, as today
    25..23 POP   3   raw
    22..21 WID   2   raw
    20..16 RA    5   register selector 0..26, raw; 28..31: the word reads no register, and
                     P = {RA[1:0], RB} (7 bits) is payload                       (form N)
    15..11 RB    5   register selector, raw; payload in form N
    10..0  B    11   SEQ >= 8: the target (the vector number for VEC); else payload, and
                     B[10] = POST (the word posts a bus request)

The late fields come from two generated tables: X (alu ax ay wf cnt, 18 bits an entry, 256
entries) and Y (d1 s1 d2 s2 wr ws ea bus seg pfx susp halt ist, 35 bits, two halves of 256:
the entries that post a request and those that do not). A form with less room than a full
code reads a fixed page of the table.

 form                 payload bits                                  codes
 N    no reg, no tgt  P7 + B11 = 18   B[10] POST, B[9:2] Y8, {P,B[1]} X8, B[0] KW
 NH   ... hold        P7 + B[4:0]     B[10] POST, B[9:6] count-1 (1..16), B[5] nbl (the mark on the
                                      last held clock), {P,B[4:0]} = X6, Y6
 NT   ... target      P7              P < 48: X ; 48..95: Y that does not post ; 96..127: Y that
                                      posts (POST = P[6] & P[5])
 NTH  ... tgt + hold  P7              P[4:0] count-1, P[5] nbl, P[6] = 0; no payload
 R    reg, no tgt     B11             B[1:0]=00: X8 at B[9:2] ; 10: B[10] POST, Y8 at B[9:2] ;
                                      B[0]=1: B[10] POST, Y5 at B[9:5], X4 at B[4:1]
 RH   ... hold        B[4:0]          B[10] POST, B[9:6] count-1, B[5] nbl, B[4]=0: X4 ; 1: Y4
 RT   ... target      none
"""
import collections
import lib
from lib import SQ, SEQV

XF = ["alu", "ax", "ay", "wf", "cnt"]
YF = ["d1", "s1", "d2", "s2", "wr", "ws", "ea", "bus", "seg", "pfx", "susp", "halt", "ist"]
KF = ["e", "f", "nb", "bi", "vk", "ro", "rl", "flush"]
FW = {n: w for n, t, w in lib.uasm.FIELDS}
XBITS = sum(FW[f] for f in XF); YBITS = sum(FW[f] for f in YF)
TKI_CODES = True       # way out (d): TKI0 / TKI1, the take entry from a generated two-entry table
SEQC = {"NEXT": 0, "EREP": 1, "RET": 2, "HOLD": 3, "TKI0": 4, "TKI1": 5, "DISP": 6,
        "JMP": 8, "CALL": 9, "LOOP": 10, "EAC": 11, "HJMP": 12, "TRAP": 13, "VEC": 14, "TKI": 15}
SEQN = {v: k for k, v in SEQC.items()}; SEQN[7] = "DISP"
RLX = 3; ESC = 28
EU = lib.uasm.enum_value
BUS_NONE, BUS_RSV = 0, EU("v35_bus_e", "rsv"); EA_REP = EU("v35_ea_e", "rep"); OPRW = EU("v35_mvd_e", "oprw")

def xp(f): return tuple(f.get(a, 0) for a in XF)
def yp(f): return tuple(f.get(a, 0) for a in YF)
def nz(t): return any(t)
def posts(f): return f.get("bus", 0) not in (BUS_NONE, BUS_RSV)
def yposts(p): return p[YF.index("bus")] not in (BUS_NONE, BUS_RSV)
def kw(f): return f.get("d1", 0) == OPRW or f.get("d2", 0) == OPRW
def is_vec(f): return bool(f.get("vk") and not f.get("bi") and f.get("rl", 0) != RLX and f.get("tgt", 0))
def sq(f): return SQ[f.get("seq", 0)]
def has_tgt(f): return sq(f) in lib.HAS_TGT
def target_half(f):
    """SEQ >= 8: B is not payload"""
    s = sq(f)
    if s == "TKI": return not TKI_CODES
    return s in ("JMP", "CALL", "LOOP", "EAC", "JC", "JNC", "TRAP") or (is_vec(f) and s == "NEXT")
def is_reg(f): return bool(f.get("ra") or f.get("rb"))
def held(w): return bool(w.hold or w.f.get("nb_last"))

def context(w):
    f = w.f; r = is_reg(f); t = target_half(f); h = held(w)
    return ("R" if r else "N") + ("T" if t else "") + ("H" if h else "")

# pages: context -> (base, size) in the X code space (0..255) and in the Y index space (0..255)
# (a page's base is its address prefix: the table address is the prefix and the code, no adder)
XPAGE = {"RH": (0, 16), "R": (16, 16), "NH": (64, 64), "NT": (128, 48)}
YPAGE = {"RH": (0, 16), "R": (32, 32), "NH": (64, 64), "NT": (176, 48), "NT1": (224, 32)}

class Dict:
    """A payload table. Y has two halves (cls 0: no post, cls 1: posts); X has one."""
    def __init__(s, name, words, get, pages, size, ncls):
        s.name = name; s.pages = pages; s.size = size; s.ncls = ncls
        s.tab = [[None] * size for _ in range(ncls)]
        s.tab[0][0] = ()
        for c, (b, n) in pages.items():
            if c not in ("NT", "NT1") or name == "X": s.tab[0][b] = ()        # entry 0 of a page: nothing
        s.where = collections.defaultdict(list)
        need = collections.defaultdict(collections.Counter); allp = collections.Counter()
        for w in words:
            p = get(w.f)
            if not nz(p): continue
            allp[p] += 1
            c = context(w)
            other = nz(xp(w.f)) if name == "Y" else nz(yp(w.f))
            if c == "R" and not other: continue              # form R with one payload: the full code
            if c in pages: need[c][p] += 1
        s.lost = collections.Counter()
        for c in ("RH", "R", "NT", "NH"):
            for p, k in need[c].most_common():
                b, n = s.page(c, p)
                if not s._put(p, range(b, b + n)): s.lost[c] += k
        for p, k in allp.most_common():
            if not s.where[p] and not s._put(p, range(size)): s.lost["full"] += k
        s.used = sum(1 for t in s.tab for q in t if q); s.distinct = len(allp)
        s.percls = [sum(1 for q in t if q) for t in s.tab]
    def cls(s, p): return int(yposts(p)) if s.ncls == 2 else 0
    def page(s, c, p): return s.pages["NT1"] if c == "NT" and s.cls(p) else s.pages[c]
    def _put(s, p, rng):
        k = s.cls(p)
        if any(q in rng for q in s.where[p]): return True
        for q in rng:
            if s.tab[k][q] is None: s.tab[k][q] = p; s.where[p].append(q); return True
        return False
    def code(s, p, ctx=None):
        """-> the index (within the page when ctx names one), or None"""
        if not nz(p): return 0
        cs = s.where.get(p, [])
        if ctx in s.pages:
            b, n = s.page(ctx, p)
            for q in cs:
                if b <= q < b + n: return q - b
            return None
        return cs[0] if cs else None
    def payload(s, idx, ctx=None, k=0):
        b = s.pages[ctx][0] if ctx in s.pages else 0
        return s.tab[k][b + idx] or ()
    def at(s, addr, k=0): return s.tab[k][addr] or ()

def arming_words():
    """The present ROM's words that arm an unarmed write: the first word that loads OPRW behind
    a bus=MEMWD word (original word indices). The EU reads the next word's KW bit early."""
    memwd = EU("v35_bus_e", "memwd"); out = set()
    for r in lib.P.routines:
        arm = False
        for k, x in enumerate(r.words):
            if arm and kw(x.fields): out.add(r.base + k); arm = False
            if x.fields.get("bus") == memwd: arm = True
    return out
KW_MEMBERS = arming_words()

class Layout:
    def __init__(s, words):
        s.X = Dict("X", words, xp, XPAGE, 256, 1); s.Y = Dict("Y", words, yp, YPAGE, 256, 2)
        s.tki = []
        for w in words:
            if sq(w.f) == "TKI" and w.f.get("tgt", 0) not in s.tki: s.tki.append(w.f.get("tgt", 0))

    def fit(s, w):
        """-> None when the word fits, else the conflict as text"""
        f = w.f; c = context(w); x, y = xp(f), yp(f); hx, hy = nz(x), nz(y); q = sq(f)
        if f.get("cond") and q not in ("JC", "JNC"): return "cond without a conditional jump"
        if c != "N" and KW_MEMBERS.intersection(w.members): return "the arming word of an unarmed write: the early KW bit exists in form N only"
        if TKI_CODES and q == "TKI" and s.tki.index(f.get("tgt", 0)) > 1: return "a third take entry"
        if is_vec(f) and q != "NEXT": return "vector number + sequencing " + q
        if held(w) and q not in ("NEXT", "JMP"): return "hold count + sequencing " + q
        if held(w) and w.hold > (32 if c in ("NTH", "RTH") else 16): return "hold count over 16"
        if f.get("e") and f.get("ea") == EA_REP and q != "NEXT": return "EREP + sequencing"
        what = ("register read + " if is_reg(f) else "") + ("target" if has_tgt(f) and target_half(f) else "vector number" if is_vec(f) else "TRAP" if q == "TRAP" else "")
        if held(w): what += " + hold count"
        what = what.strip(" +")
        pl = " + ".join(n for n, h in (("X (ALU / counter)", hx), ("Y (move / write / bus)", hy)) if h)
        if c in ("RT", "NTH", "RTH"):
            if c == "RTH": return what + (" + " + pl if pl else "") + ": no room for the count"
            return None if not (hx or hy) else f"{what} + {pl}: no payload bits"
        if c in ("N",):
            if s.X.code(x) is None: return "X table full"
            if s.Y.code(y) is None: return "Y table full"
            return None
        if c == "NH":
            if s.X.code(x, c) is None: return f"{what} + {pl}: X outside its 6-bit page"
            if s.Y.code(y, c) is None: return f"{what} + {pl}: Y outside its 6-bit page"
            return None
        if c == "NT":
            if hx and hy: return f"{what} + {pl}: one payload code only"
            if hx and s.X.code(x, c) is None: return f"{what} + {pl}: X outside its page"
            if hy and s.Y.code(y, c) is None: return f"{what} + {pl}: Y outside its page"
            return None
        if c == "RH":
            if hx and hy: return f"{what} + {pl}: one payload code only"
            if hx and s.X.code(x, c) is None: return f"{what} + {pl}: X outside its 4-bit page"
            if hy and s.Y.code(y, c) is None: return f"{what} + {pl}: Y outside its 4-bit page"
            return None
        if c == "R":
            if hx and hy:
                if s.X.code(x, c) is None: return f"register read + {pl}: X outside its 4-bit page"
                if s.Y.code(y, c) is None: return f"register read + {pl}: Y outside its 5-bit page"
                return None
            if hx and s.X.code(x) is None: return "X table full"
            if hy and s.Y.code(y) is None: return "Y table full"
            return None
        raise AssertionError(c)

    def seq5(s, w):
        f = w.f; q = sq(f)
        if q in ("JC", "JNC"): return 16 | (8 if q == "JNC" else 0) | f.get("cond", 0)
        if held(w): return SEQC["HJMP" if q == "JMP" else "HOLD"]
        if q == "TKI" and TKI_CODES: return SEQC["TKI1" if s.tki.index(f.get("tgt", 0)) else "TKI0"]
        if q == "NEXT" and is_vec(f): return SEQC["VEC"]
        if q == "NEXT" and f.get("e") and f.get("ea") == EA_REP: return SEQC["EREP"]
        return SEQC[q]

    def encode(s, w):
        """-> the 40-bit word. The word must fit; its target must be an address."""
        f = w.f; c = context(w); x, y = xp(f), yp(f)
        k = 0
        for a in KF: k = (k << FW[a]) | f.get(a, 0)
        cnt = (w.hold - 1) & 31 if w.hold else 0; nbl = 1 if f.get("nb_last") else 0
        post = int(posts(f)); ra = f.get("ra", 0); rb = f.get("rb", 0); b = 0; p7 = None
        if c == "N":
            xc = s.X.code(x); b = (post << 10) | (s.Y.code(y) << 2) | ((xc & 1) << 1) | int(kw(f)); p7 = xc >> 1
        elif c == "NH":
            pay = (s.X.code(x, c) << 6) | s.Y.code(y, c)
            b = (post << 10) | (cnt << 6) | (nbl << 5) | (pay & 31); p7 = pay >> 5
        elif c == "NT":
            p7 = ((96 if post else 48) + s.Y.code(y, c)) if nz(y) else s.X.code(x, c)
            b = f.get("tgt", 0) & 0x7FF
        elif c == "NTH":
            p7 = (nbl << 5) | cnt; b = f.get("tgt", 0) & 0x7FF
        elif c == "R":
            if nz(x) and nz(y): b = (post << 10) | (s.Y.code(y, c) << 5) | (s.X.code(x, c) << 1) | 1
            elif nz(y): b = (post << 10) | (s.Y.code(y) << 2) | 2
            else: b = s.X.code(x) << 2
        elif c == "RH":
            pay = (16 | s.Y.code(y, c)) if nz(y) else s.X.code(x, c)
            b = (post << 10) | (cnt << 6) | (nbl << 5) | pay
        elif c == "RT":
            b = f.get("tgt", 0) & 0x7FF
        if p7 is not None: ra = ESC | (p7 >> 5); rb = p7 & 31
        v = s.seq5(w)
        for val, wd in ((k, 9), (f.get("pop", 0), 3), (f.get("wid", 0), 2), (ra, 5), (rb, 5), (b, 11)): v = (v << wd) | val
        return v

    # ---- the early bits, as the tick-B logic reads them from the raw word (no table)
    @staticmethod
    def early(v):
        b = v & 0x7FF; rb = (v >> 11) & 31; ra = (v >> 16) & 31; s5 = v >> 35
        tgt = s5 >= 8; esc = ra >= ESC
        return dict(disp=(s5 >> 1) == 3, tki=(s5 >> 1) == 2, erep=bool((v >> 34) & 1 and s5 & 1),      # erep = E and SEQ[0]
                    post=(esc and (ra & 3) == 3) if tgt else bool(b >> 10),
                    kw=esc and s5 < 8 and s5 != SEQC["HOLD"] and bool(b & 1))

    def decode(s, v):
        """the expand stage -> (fields, hold, nb_last)"""
        b = v & 0x7FF; rb = (v >> 11) & 31; ra = (v >> 16) & 31; wid = (v >> 21) & 3; pop = (v >> 23) & 7; k = (v >> 26) & 511; s5 = v >> 35
        f = {}
        for a in reversed(KF):
            f[a] = k & ((1 << FW[a]) - 1); k >>= FW[a]
        f["pop"] = pop; f["wid"] = wid
        hold = hj = False; n = None
        if s5 & 16: f["seq"] = SEQV["JNC" if s5 & 8 else "JC"]; f["cond"] = s5 & 7
        else:
            n = SEQN[s5]
            if n == "HOLD": hold = True
            elif n == "HJMP": hold = hj = True; f["seq"] = SEQV["JMP"]
            elif n in ("TKI0", "TKI1"): f["seq"] = SEQV["TKI"]; f["tgt"] = s.tki[s5 & 1] & 0x7FF
            elif n in ("EREP", "VEC"): pass
            else: f["seq"] = SEQV[n]
        t = s5 >= 8; esc = ra >= ESC; x = y = (); cnt = nbl = 0
        if t and n != "TRAP": f["tgt"] = b
        if esc:
            p7 = ((ra & 3) << 5) | rb; ra = rb = 0
            if hj: cnt = p7 & 31; nbl = (p7 >> 5) & 1
            elif t:
                if p7 >= 96: y = s.Y.at(128 + p7, 1)
                elif p7 >= 48: y = s.Y.at(128 + p7, 0)
                else: x = s.X.at(128 + p7)
            elif hold:
                pay = (p7 << 5) | (b & 31); cnt = (b >> 6) & 15; nbl = (b >> 5) & 1
                x = s.X.payload(pay >> 6, "NH"); y = s.Y.payload(pay & 63, "NH", b >> 10)
            else:
                x = s.X.payload((p7 << 1) | ((b >> 1) & 1)); y = s.Y.payload((b >> 2) & 255, None, b >> 10)
        elif not t:
            if hold:
                cnt = (b >> 6) & 15; nbl = (b >> 5) & 1
                if b & 16: y = s.Y.payload(b & 15, "RH", b >> 10)
                else: x = s.X.payload(b & 15, "RH")
            elif b & 1: x = s.X.payload((b >> 1) & 15, "R"); y = s.Y.payload((b >> 5) & 31, "R", b >> 10)
            elif b & 2: y = s.Y.payload((b >> 2) & 255, None, b >> 10)
            else: x = s.X.payload((b >> 2) & 255)
        f["ra"] = ra; f["rb"] = rb
        for names, p in ((XF, x), (YF, y)):
            for a, val in zip(names, p): f[a] = val
        return {a: val for a, val in f.items() if val}, (cnt + 1 if hold else 0), bool(nbl)

def check_roundtrip(L, w):
    v = L.encode(w); assert 0 <= v < 1 << 40
    f, h, nbl = L.decode(v)
    ref = {a: val for a, val in w.f.items() if val and a != "nb_last"}
    if "tgt" in ref:
        ref["tgt"] &= 0x7FF
        if not ref["tgt"]: ref.pop("tgt")
    assert f == ref and h == w.hold and nbl == bool(w.f.get("nb_last")), (lib.show(w.f, w.hold), f, ref, h, nbl)
    e = L.early(v); q = sq(w.f)
    assert e["disp"] == (q == "DISP") and e["post"] == posts(w.f) and e["erep"] == bool(w.f.get("e") and w.f.get("ea") == EA_REP), (lib.show(w.f), e)
    assert e["tki"] == (q == "TKI") or not TKI_CODES
    assert not w.f.get("e") or (v >> 35) in (0, 1, 8), "an E word's SEQ is NEXT, EREP or JMP"
    assert not e["kw"] or kw(w.f)
    return v, e
