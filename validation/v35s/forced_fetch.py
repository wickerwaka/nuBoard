"""Run the model with silicon's fetch and refresh times forced.

    python -m validation.v35s.forced_fetch [--spec JSON] [--table OUT.jsonl] [ENTRY ...]

From the first fetch of 10000h on, the model's bus unit starts each code
fetch and refresh when silicon did, instead of by its own rules; the EU's
data cycles still go when the model's EU asks. Silicon's times are mapped
onto the model's clock from the latest data cycle on (each data cycle
re-anchors the mapping), so an EU that drifts does not drag the fetches
with it.

With fetches fixed, what is left is the EU: the report gives, per wait
setting, how often the model's opening-to-closing marker time equals
silicon's, and the mean error. --table also logs the model's state at every
free bus clock inside the window, labelled with whether silicon started a
fetch there, for reading the bus unit's rule off the data. A row is "sync"
when the gap between the model's last two data cycles matched silicon's
and the next one is not overdue; window_error is its run's marker-window
error (0: the EU kept time over the whole window).
"""

from __future__ import annotations

import argparse
import collections
import json
from multiprocessing import Pool

from .corpus import load
from .fit import case_from_json, pages
from .model.costs import COSTS
from .model.machine import Cycle, Machine
from .runner import Transaction
from .timing import build, markers

ENTRIES = {"a6-timing": 0, "p2-release": 0, "p2-held": 0, "p2-eu": 0, "p2-follow": 0, "p2-stall": 0,
           "p2-regform": 0, "p2-held-w1": 1, "p2-eu-w1": 1, "p2-follow-w1": 1,
           "p2-held-w2": 2, "p2-eu-w2": 2, "p2-follow-w2": 2}
CODE = (0x10000, 0x20000)


class Forced(Machine):
    """A Machine whose code fetches and refreshes follow silicon's schedule."""

    def setup(self, si, table=False):
        self.si = si                  # silicon cycles: (tick, "fetch" / "refresh" / "eu", address, width)
        self.on = False
        self.table = table
        self.events = []
        self.rows = []
        self.eu_mo = []               # model clocks of the data cycles since forcing began
        self.eu_ticks = []            # silicon ticks of the same cycles
        self.anchor = None            # (silicon tick, model clock) of the latest data cycle
        self.local_ok = True
        self.last_end = None
        self.last_kind = None
        self.loads = []

    def _due(self, tick):
        return self.anchor[1] + round((tick - self.anchor[0]) / 8)

    def _finish(self, cycle):
        super()._finish(cycle)
        self.last_end = self.clock
        self.last_kind = cycle.kind if cycle.kind in ("fetch", "refresh") else f"{cycle.kind}-{cycle.space}"

    def _start(self, cycle):
        super()._start(cycle)
        if self.on and cycle.owner in ("eu", "posted"):
            n = len(self.eu_mo)
            self.eu_mo.append(self.clock)
            if n < len(self.eu_ticks):
                prev, self.anchor = self.anchor, (self.eu_ticks[n], self.clock)
                self.local_ok = round((self.eu_ticks[n] - prev[0]) / 8) == self.clock - prev[1]

    def _bus(self):
        if not self.on:
            super()._bus()
            c = self.cycle
            if c is not None and c.kind == "fetch" and c.address == CODE[0] and c.start == self.clock:
                self.on = True
                t0 = next(t[0] for t in self.si if t[1] == "fetch" and t[2] == CODE[0])
                self.events = [t for t in self.si if t[0] > t0 and t[1] in ("fetch", "refresh")]
                self.eu_ticks = [t[0] for t in self.si if t[0] > t0 and t[1] == "eu"]
                self.anchor = (t0, self.clock)
            return
        if self.cycle is not None:
            if self.clock - self.cycle.start + 1 >= self.cycle.length:
                cycle, self.cycle = self.cycle, None
                if cycle.space == "io":
                    self.bus_idle_until = self.clock + 1 + self.costs["io_recovery"]
                self._finish(cycle)
            return
        if self.clock < self.bus_idle_until:
            return
        if self.pending is not None and self.clock >= self.pending.not_before:
            cycle, self.pending = self.pending, None
            self._start(cycle)
            return
        ev = self.events[0] if self.events else None
        due = self._due(ev[0]) if ev else None
        if ev and ev[1] == "refresh" and due <= self.clock:
            self.events.pop(0)
            self._start(Cycle("refresh", "mem", 0, 2, owner="refresh"))
            return
        if ev and ev[1] == "fetch":
            if self.table and due >= self.clock:
                self.rows.append(self._features(int(due == self.clock)))
            if due <= self.clock:
                self.events.pop(0)
                self._start(Cycle("fetch", "mem", ev[2], ev[3]))
                self.fetch_linear = (ev[2] + ev[3]) & 0xFFFFF

    def _features(self, label):
        c = self.clock
        req = self._eu_request
        n = len(self.eu_mo)
        nxt = self.eu_ticks[n] if n < len(self.eu_ticks) else None
        lt, ld = self.last_take, (self.loads[-1] if self.loads else None)
        return {
            "y": label, "clock": c,
            "sync": self.local_ok and (nxt is None or self._due(nxt) >= c),
            "qw": self._queue_words(), "qb": len(self.queue), "iwr": len(self.iwr),
            "held": int(bool(self.iwr_held)), "eu_op": req[0] if req else "-",
            "since_take": c - lt[0] if lt else 99, "take_op": int(lt[1]) if lt else -1,
            "since_load": c - ld[0] if ld else 99, "load_pre": int(self.last_load_preload),
            "since_end": c - self.last_end if self.last_end is not None else 99,
            "last_kind": self.last_kind or "-", "boundary": int(self._last_was_boundary),
        }


def silicon_cycles(trace):
    out = []
    for t in trace:
        if t.kind == "refresh":
            out.append((t.start, "refresh", t.address, 0))
        elif t.kind == "mem-read" and CODE[0] <= t.address < CODE[1]:
            out.append((t.start, "fetch", t.address, 1 if t.address & 1 else 2))
        elif t.kind != "idle":
            out.append((t.start, "eu", t.address, 0))
    return out


def run(job):
    """One run: (entry, wait setting, name, odd, marker-window error or None, table rows)."""
    entry, waits, index, spec, table = job
    data = load(entry)
    r = data["runs"][index]
    case = case_from_json(r["case"])
    trace = [Transaction(**t) for t in r["socket_trace"]]
    m = Forced(pages(build(case, data["settings"])[0]), costs=dict(COSTS, **spec))
    m.setup(silicon_cycles(trace), table)
    m.run(60_000)
    found = markers(trace)
    result = (entry, waits, case.name, case.odd, None, [])
    if not m.on or len(found) < 2:
        return result
    idx = [k for k, t in enumerate(m.eu_ticks) if t in (found[0].start, found[1].start)]
    if len(idx) < 2 or len(m.eu_mo) <= idx[1]:
        return result
    a, b = idx[:2]
    error = (m.eu_mo[b] - m.eu_mo[a]) - round((m.eu_ticks[b] - m.eu_ticks[a]) / 8)
    lo, hi = m.eu_mo[a], m.eu_mo[b]
    rows = [dict(row, entry=entry, w=waits, run=index, name=case.name, odd=int(case.odd), window_error=error)
            for row in m.rows if lo <= row["clock"] <= hi]
    return entry, waits, case.name, case.odd, error, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entries", nargs="*")
    parser.add_argument("--spec", default="{}", help="JSON cost overrides")
    parser.add_argument("--table", help="write the free-clock decision table here")
    args = parser.parse_args()
    spec = json.loads(args.spec)
    entries = {e: ENTRIES.get(e, 0) for e in args.entries} if args.entries else ENTRIES
    jobs = [(e, w, i, spec, bool(args.table)) for e, w in entries.items() for i in range(len(load(e)["runs"]))]
    with Pool() as pool:
        results = pool.map(run, jobs, chunksize=4)
    for waits in sorted({r[1] for r in results}):
        errs = [r[4] for r in results if r[1] == waits and r[4] is not None]
        if errs:
            dist = collections.Counter(max(-6, min(6, e)) for e in errs)
            print(f"{waits} waits: {len(errs)} runs, window time exact {dist[0]}, mean error "
                  f"{sum(errs) / len(errs):+.2f}, spread {sorted(dist.items())}")
    if args.table:
        with open(args.table, "w") as f:
            for r in results:
                for row in r[5]:
                    f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
