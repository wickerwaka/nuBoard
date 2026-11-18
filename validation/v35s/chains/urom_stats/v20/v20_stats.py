"""Measurements of the V20 microcode listing (build/deps/nuV30/docs/V20UC.TXT). Read-only.
usage: python3 v20_stats.py            (run from the repo root)"""
import re, collections, sys
from pathlib import Path
SRC = Path("build/deps/nuV30/docs/V20UC.TXT")

def klass(page, op, reg=None):
    """One class label for a (page, opcode[, ModR/M reg field]); used for the V20 and for ours."""
    if page == "8080": return "8080 emulation"
    if page == "0f":
        if 0x10 <= op <= 0x1F: return "0F bit ops"
        if 0x20 <= op <= 0x27 and op not in (0x25,): return "0F BCD strings"
        if op in (0x28, 0x2A): return "0F digit rotates"
        if op in (0x31, 0x33, 0x39, 0x3B, 0x34, 0x3C): return "0F bit fields"
        if op == 0xFF: return "8080 emulation"
        return "V35 only"
    if page == "rep":
        if op in (0xA4,0xA5,0xA6,0xA7,0xAA,0xAB,0xAC,0xAD,0xAE,0xAF,0x6C,0x6D,0x6E,0x6F,0xF2,0xF3,0x64,0x65): return "strings"
        return "misc"
    if op < 0x40:
        lo = op & 7
        if lo < 6: return "ALU"
        if op in (0x26,0x2E,0x36,0x3E): return "misc"
        if op in (0x27,0x2F,0x37,0x3F): return "adjust / convert"
        if op == 0x0F: return "misc"
        return "PUSH / POP"
    if op < 0x50: return "unary (INC DEC NOT NEG)"
    if op < 0x62: return "PUSH / POP"
    if op == 0x62: return "misc"
    if op == 0x63: return "V35 only"
    if op in (0x64,0x65,0x66,0x67): return "misc"
    if op in (0x68,0x6A): return "PUSH / POP"
    if op in (0x69,0x6B): return "MUL / DIV"
    if op < 0x70: return "strings"
    if op < 0x80: return "transfers"
    if op < 0x86: return "ALU"
    if op < 0x8F: return "MOV / XCH"
    if op == 0x8F: return "PUSH / POP"
    if op < 0x98: return "MOV / XCH"
    if op in (0x98,0x99,0x9B,0x9E,0x9F): return "misc"
    if op == 0x9A: return "transfers"
    if op in (0x9C,0x9D): return "PUSH / POP"
    if op < 0xA4: return "MOV / XCH"
    if op in (0xA8,0xA9): return "ALU"
    if op < 0xB0: return "strings"
    if op < 0xC0: return "MOV / XCH"
    if op in (0xC0,0xC1,0xD0,0xD1,0xD2,0xD3): return "shifts"
    if op in (0xC2,0xC3,0xCA,0xCB,0xCC,0xCD,0xCE,0xCF): return "transfers"
    if op in (0xC4,0xC5,0xC6,0xC7): return "MOV / XCH"
    if op in (0xC8,0xC9): return "PUSH / POP"
    if op in (0xD4,0xD5): return "adjust / convert"
    if op == 0xD6: return "V35 only"
    if op == 0xD7: return "misc"
    if op < 0xE0: return "misc"
    if op in (0xE4,0xE5,0xE6,0xE7,0xEC,0xED,0xEE,0xEF): return "I/O"
    if op < 0xF0: return "transfers"
    if op in (0xF6,0xF7):
        if reg is None: return "group F6/F7"
        return "ALU" if reg < 2 else "unary (INC DEC NOT NEG)" if reg < 4 else "MUL / DIV"
    if op in (0xFE,0xFF):
        if reg is None: return "group FE/FF"
        return "unary (INC DEC NOT NEG)" if reg < 2 else "transfers" if reg < 6 else "PUSH / POP"
    if op == 0xF1: return "V35 only"
    return "misc"

INTERNAL = {"IRET":"transfers","INT":"transfers","INTEM":"8080 emulation","MULADJ":"MUL / DIV","MULX":"MUL / DIV",
    "IMUL":"MUL / DIV","IMULI":"MUL / DIV","REPX":"strings","SHIFT":"shifts","ENTER":"PUSH / POP","PUSHA":"PUSH / POP",
    "POPA":"PUSH / POP","CALLF":"transfers","INS":"0F bit fields","IDIV":"MUL / DIV","RETF":"transfers","IDIV2":"MUL / DIV"}
INT_BY_OP = {0x03:"misc", 0x00:"transfers", 0x02:"transfers", 0x11:"transfers", 0x19:"transfers", 0x31:"MUL / DIV", 0x71:"0F bit fields", 0x30:"MUL / DIV", 0x38:"MUL / DIV", 0x18:"8080 emulation"}

def expand(pat):
    """all bytes matching an 8-char 01? pattern"""
    return [b for b in range(256) if all(c == "?" or int(c) == (b >> (7 - i)) & 1 for i, c in enumerate(pat))]

def parse():
    blocks = []; cur = None
    for ln in SRC.read_text().splitlines():
        if ln.startswith("-------"):
            m = re.match(r"------- (\S+)\.(\S+)\.(\S+)\s*(.*)", ln)
            grp, opc, step, rest = m.groups()
            cur = dict(grp=grp, opc=opc, step=step, rest=rest, words=[]); blocks.append(cur)
        elif ln.strip():
            cur["words"].append(ln)
    return blocks

def block_class(b):
    g = b["grp"]; ops = expand(b["opc"])
    if g in ("00?", "000", "001"):
        page = None
        c = collections.Counter(klass("rep" if g == "001" else None, o) for o in ops)
    elif g == "010": c = collections.Counter(klass(None, 0xF6, (o >> 3) & 7) for o in ops)
    elif g == "011": c = collections.Counter(klass(None, 0xFE, (o >> 3) & 7) for o in ops)
    elif g == "100": c = collections.Counter(klass("0f", o) for o in ops)
    elif g in ("101", "110"): return "8080 emulation"
    else:
        m = re.search(r"<internal> (\w+)?", b["rest"]); nm = m.group(1) if m else None
        if nm in INTERNAL: return INTERNAL[nm]
        return INT_BY_OP.get(ops[0], "misc")
    return c.most_common(1)[0][0]

def wparse(ln):
    a = ln[:4]; body = ln[5:]
    mv = re.findall(r"(\S+)\s+-> (\S+)", body)
    const = "CONST" in body
    typ = "ALU" if " ALU " in body else "JMP" if " JMP " in body else "CTL"
    t = body.split(typ, 1)[1].split() if typ in body else []
    pre = body.split(typ, 1)[0]
    fl = pre[36:].replace(" ", "") if len(pre) > 36 else ""
    # flags sit in a 4-column field before the type; recover from the tail of `pre`
    fl = re.sub(r"[^FWER]", "", pre[-6:])
    empty = not mv and not fl and typ == "CTL" and not t
    return dict(a=a, mv=mv, typ=typ, t=t, fl=fl, empty=empty, raw=ln)

if __name__ == "__main__":
    B = parse(); W = [(b, wparse(w)) for b in B for w in b["words"]]
    print("blocks", len(B), "words", len(W))
    ne = [w for b, w in W if not w["empty"]]
    print("non-empty words", len(ne), "empty filler words", len(W) - len(ne))
    c = collections.Counter(w["typ"] for w in ne); print("type of non-empty words", dict(c))
    print("words with 0/1/2 moves:", sorted(collections.Counter(len(w["mv"]) for w in ne).items()))
    print("flag F", sum("F" in w["fl"] for w in ne), "W", sum("W" in w["fl"] for w in ne), "E", sum("E" in w["fl"] for w in ne), "R", sum("R" in w["fl"] for w in ne))
    ctl = collections.Counter(tok for w in ne if w["typ"] == "CTL" for tok in w["t"]); print("CTL tokens", ctl.most_common())
    jc = collections.Counter(w["t"][0] if len(w["t"]) > 1 else "(always)" for w in ne if w["typ"] == "JMP"); print("JMP conditions", jc.most_common())
    al = collections.Counter(w["t"][0] for w in ne if w["typ"] == "ALU"); print("ALU ops", al.most_common())
    print("ALU OPC (operation from the opcode):", al["OPC"], " JMP on OPC:", jc["OPC"], " JMP on OP8/OP8b:", jc["OP8"] + jc["OP8b"])
    src = collections.Counter(s for w in ne for s, d in w["mv"]); dst = collections.Counter(d for w in ne for s, d in w["mv"])
    print("move sources", src.most_common()); print("move destinations", dst.most_common())
    print("words reading Q:", sum(any(s == "Q" for s, d in w["mv"]) for w in ne), " M as source:", src["M"], " M as dest:", dst["M"], " R:", src["R"], dst["R"])
    # act-less words that still do something for sequencing only (a JMP with no move), or pure waits
    pure_jmp = [w for w in ne if w["typ"] == "JMP" and not w["mv"]]; print("JMP words with no move:", len(pure_jmp))
    onlyflag = [w for w in ne if not w["mv"] and w["typ"] == "CTL" and not w["t"]]; print("words with flags only (E / F / W alone):", len(onlyflag), collections.Counter(w["fl"] for w in onlyflag))
    # opcodes per block (sharing)
    per = collections.defaultdict(lambda: [0, 0, 0, set()])
    for b in B:
        k = block_class(b); n = sum(1 for w in b["words"] if not wparse(w)["empty"])
        per[k][0] += 1; per[k][1] += 4; per[k][2] += n
        if b["grp"] in ("00?", "000", "001"): per[k][3] |= set(expand(b["opc"]))
    print(f"\n{'class':28} blocks  rows  used  first-level opcodes")
    T = [0, 0, 0]
    for k, (nb, nr, nu, ops) in sorted(per.items(), key=lambda x: -x[1][2]):
        print(f"{k:28} {nb:5} {nr:5} {nu:5}  {len(ops)}"); T[0] += nb; T[1] += nr; T[2] += nu
    print(f"{'total':28} {T[0]:5} {T[1]:5} {T[2]:5}")
    nat = [b for b in B if b["grp"] in ("00?", "000", "001") and b["step"] == "00"]
    cov = collections.Counter(len(expand(b["opc"])) for b in nat)
    print("first blocks of native routines:", len(nat), " opcodes covered per entry block:", sorted(cov.items()))
    allops = set(o for b in nat for o in expand(b["opc"])); print("distinct native first-byte opcodes with a routine:", len(allops))
