"""tc23.py : r23c, the pin records (TC0 bit 18, DMAAK0 bit 17) in clocks from the DMA write's first clock."""
import json
d = json.load(open("build/validation/v35s/qprobe/socket/QPr23c-w0.json"))
for r in d["runs"]:
    tr = r["socket_trace"]
    w = next(x for x in tr if not x["flags"] & 0x203 and 0xD000 <= x["address"] < 0xE000)
    out = []
    for x in tr:
        if x["flags"] & 0x200:
            pins = x["address"] | x["data"] << 16
            out.append(f"{(x['start'] - w['start']) / 8:+.2f}:TC{pins >> 18 & 1}AK{pins >> 17 & 1}")
    print(r["chain"]["id"][4:], "write", (w["end"] - w["start"]) / 8, "clocks;", " ".join(out))
