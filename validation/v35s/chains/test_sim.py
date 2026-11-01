"""Offline tests of the cycle model (sim/) and the scorer against recorded silicon."""

from __future__ import annotations

import copy
import unittest

from validation.v35s.chains.families import FAMILIES, UNMODELLED, generate
from validation.v35s.chains.forms import DEFAULT_REGS as FORMS_REGS
from validation.v35s.chains.forms import FORMS, UNMODELLED_FORMS
from validation.v35s.chains.normalize import load_runs, normalize
from validation.v35s.chains.score import aligned, score, score_family
from validation.v35s.chains.sim.config import DEFAULT, OPTIONS, Config
from validation.v35s.chains.sim.machine import Machine, simulate, simulate_normalized
from validation.v35s.chains.sim.queue import QUEUE_BYTES, Queue, QueueOverflow
from validation.v35s.chains.sim.templates import decode

# (WP49) the families the simulator can run: F23 is generator-only (WP52: F25 is modelled)
MODELLED = [f for f in FAMILIES if f not in UNMODELLED]


# (WP91) the words F37's leads store, as execute's memory image keeps them (templates
# _execute_wp91): the pointer at 0C00h (PS at 0C02h; the same at 0800h for a [BW] form where BW
# is 0800h) and BRK 3's / BRK 5's vectors, so the transfers decode standalone
F37_WORDS = {"mem0C00": 0x58, "mem0C02": 0x1000, "mem0800": 0x58, "mem0802": 0x1000,
             "mem000C": 0x58, "mem000E": 0x1000, "mem0014": 0x58, "mem0016": 0x1000}


def _runs(family):
    try:
        return load_runs(family)
    except FileNotFoundError:
        raise unittest.SkipTest(f"no corpus entries for {family}")


class F0Reproduction(unittest.TestCase):
    """Acceptance 1: the hand-found DEFAULT reproduces every F0 run from t_fill on."""

    def test_ls_even_w0(self):
        run = next(r for r in _runs("F0") if r["chain"]["id"] == "F0-ls-pE-w0")
        s = normalize(run)
        m = simulate_normalized(s.chain, DEFAULT, s.chain_base)
        sc = score(s, m)
        self.assertTrue(sc.exact, sc.first_divergence)
        # The facts the brief names: restart +76, back to back, END write.
        a = aligned(m)
        self.assertEqual([e[0] for e in a], [-2, 76, 79, 87])
        self.assertEqual(a[-1][1:3], ("io_write", 0xFF00))

    def test_all_f0_exact(self):
        results = score_family(_runs("F0"), DEFAULT)
        self.assertEqual(len(results), 18)
        bad = [sc.run_id for _, _, sc in results if not sc.exact]
        self.assertEqual(bad, [])


class ScorerTests(unittest.TestCase):
    def setUp(self):
        run = next(r for r in _runs("F0") if r["chain"]["id"] == "F0-ls_nop_ls-pE-w1")
        self.s = normalize(run)

    def test_identical(self):
        sc = score(self.s, copy.deepcopy(self.s))
        self.assertTrue(sc.exact)
        self.assertIsNone(sc.first_divergence)
        self.assertEqual(sc.matched_prefix, sc.n_silicon)
        self.assertEqual(set(sc.residuals), {0})

    def test_shifted_copy(self):
        m = copy.deepcopy(self.s)
        k = m.fill_index + 2                  # third event from the fill fetch
        for e in m.events[k:]:
            e.clock += 3
        sc = score(self.s, m)
        self.assertFalse(sc.exact)
        self.assertEqual(sc.first_divergence[0], 2)
        self.assertEqual(sc.first_divergence[2][0] - sc.first_divergence[1][0], 3)
        self.assertEqual(sc.residuals, [0, 0] + [3] * (sc.n_silicon - 2))


class ModelRuns(unittest.TestCase):
    """Acceptance 3: every recorded F0/F0w/F1 chain simulates and normalises cleanly."""

    def test_recorded_families(self):
        for family in ("F0", "F0w", "F1"):
            for run in _runs(family):
                s = normalize(run)
                m = simulate_normalized(s.chain, DEFAULT, s.chain_base)
                markers = sum(1 for i in s.chain.instrs if i.role == "marker")
                with self.subTest(run=s.run_id):
                    self.assertIsNotNone(m.t_fill)
                    self.assertEqual(len(m.t_markers), markers)
                    self.assertIsNotNone(m.t_end)
                    self.assertEqual(m.checks, [])

    def test_every_generated_chain(self):
        for chain in generate(MODELLED, parities=("even",), waits=(0, 2)):
            with self.subTest(chain=chain.id):
                events = simulate(chain)
                self.assertEqual(events[-1].kind, "io_write")
                self.assertEqual(events[-1].addr, 0xFF00)

    def test_decoded_lengths_cover_forms(self):
        # (WP55) the F23 forms decode with their context: Z known (CMP AW,AW), a return
        # address at SP (a CALL before the RET)
        regs = {"AW": 0, "BW": 0x800, "CW": 0, "DW": 0x40, "SP": 0xF00, "BP": 0xA00,
                "IX": 0x100, "IY": 0x180, "Z": 1, "ret0F00": 0,
                "CY": 0, "S": 0, "V": 0, "P": 1,   # (WP88) every 70-7F condition known
                **F37_WORDS}                       # (WP91) F37's pointer and vectors
        for form in FORMS.values():
            if form.name in UNMODELLED_FORMS:
                continue                 # (WP49) generator-only forms (none since WP55)
            k = 0
            while k < form.length:
                k += decode(form.code, k, regs).length
            self.assertEqual(k, form.length, form.name)

    def test_odd_word_split(self):
        chain = next(c for c in generate(["F4"], waits=(0,), parities=("even",))
                     if c.id == "F4-push-ld_bw-k1-odd-pE-w0")
        data = [e for e in simulate(chain) if e.kind == "data_read"]
        self.assertEqual([(e.addr, e.width) for e in data], [(0x801, "hi"), (0x802, "lo")])


class ConfigTests(unittest.TestCase):
    def test_json_round_trip(self):
        cfg = DEFAULT.replace(room_ir=True, **{"imm.pre": 5, "ea.direct": 3})
        self.assertEqual(Config.from_json(cfg.to_json()), cfg)
        self.assertEqual(cfg.c("imm", "pre"), 5)
        self.assertEqual(DEFAULT.c("imm", "pre"), 3)

    def test_every_option_runs(self):
        chain = next(c for c in generate(["F1"], waits=(1,), parities=("odd",))
                     if c.id == "F1-store-m2-pO-w1")
        stalls = {("request_eval", "on_take")}      # refuted: stalls (test_stall_raises_fast)
        for name, values in OPTIONS.items():
            for value in values:
                if (name, value) in stalls:
                    continue
                with self.subTest(option=name, value=value):
                    simulate(chain, DEFAULT.replace(**{name: value}))

    def test_stall_raises_fast(self):
        # request_eval=on_take never re-requests after the first word lands with no take
        # (the start-up fill): the run stalls and is reported within STALL_CLOCKS, not
        # after MAX_CLOCKS.
        from validation.v35s.chains.sim.machine import STALL_CLOCKS
        m = Machine(_chain("F0", "F0-ls-pE-w0"), DEFAULT.replace(request_eval="on_take"))
        with self.assertRaises(RuntimeError) as cm:
            m.run()
        self.assertIn("no bus cycle", str(cm.exception))
        self.assertLess(m.bus.last_end, STALL_CLOCKS)

    def test_bad_option_rejected(self):
        with self.assertRaises(ValueError):
            DEFAULT.replace(release="never")


# The fourth fit's I/O structure: the OUT's EU waits for its I/O, posted on the port take
# and issuable after 6 fetch-free clocks.
FOURTH_IO = dict(io_release="issue", io_post="take", io_count="fetch_free", port_latch="none",
                 port_sync="sync", io_hold="hold_fetch", io_interlock="none", io_recover=0,
                 **{"out.pre": 3, "out.pre0": 1, "out.exec": 0, "out.setup": 6, "out.lead": 0,
                    "out.wbsync": 1})

# The structure the queue rework chose (fit stage 2-6): the IR is a seventh slot
# of the request rule, the request is re-evaluated on queue changes only, and an
# instruction does not start while the bus unit is committed to a fetch.
REWORK = dict(room_ir=True, request_eval="on_change", start_sync="b2b")


def _chain(family, cid):
    return next(c for c in generate([family]) if c.id == cid)


def _first_fetch_after_fill(cfg, cid="F0-ls-pE-w0"):
    n = simulate_normalized(_chain("F0", cid), cfg)
    return [e[0] for e in aligned(n) if e[1] == "fetch"][1]


class QueueStorage(unittest.TestCase):
    """The queue is six bytes of storage; the IR is a seventh byte outside it."""

    def _peak(self, cfg, chains):
        peak = 0
        for chain in chains:
            m = Machine(chain, cfg)
            m.run()
            peak = max(peak, m.queue.peak)
        return peak

    def test_never_more_than_six_bytes(self):
        # Every chain of the catalog under DEFAULT: the queue fills to six and no further.
        self.assertEqual(self._peak(DEFAULT, generate(MODELLED, parities=("even", "odd"), waits=(0, 2))),
                         QUEUE_BYTES)

    def test_ir_load_leaves_the_queue(self):
        m = Machine(_chain("F0", "F0-ls-pE-w0"), DEFAULT)
        q, d = m.queue, m.decoder
        q.arrive(0x10046, 0, 0)
        q.arrive(0x10048, 0, 0)                  # bytes from 10048 on (LS) are kept
        n = q.stored()
        d.load_ir(0)
        self.assertIsNotNone(d.ir)
        self.assertEqual(q.stored(), n - 1)
        self.assertEqual(q.room(), QUEUE_BYTES - q.stored())

    def test_room_ir_counts_the_ir(self):
        m = Machine(_chain("F0", "F0-ls-pE-w0"), DEFAULT.replace(room_ir=True))
        q, d = m.queue, m.decoder
        q.arrive(0x10048, 0, 0)
        q.arrive(0x1004A, 0, 0)
        self.assertEqual(q.room(), QUEUE_BYTES + 1 - 4)     # IR empty: a seventh free slot
        d.load_ir(0)
        self.assertEqual(q.room(), QUEUE_BYTES + 1 - 3 - 1)

    def test_overflow_raises(self):
        m = Machine(_chain("F0", "F0-ls-pE-w0"), DEFAULT)
        q = m.queue
        for k in range(4):
            q.arrive(0x10048 + 2 * k, 0, 0)
        with self.assertRaises(QueueOverflow):
            q.check(0)


class RequestRule(unittest.TestCase):
    """The new request-rule options, each on the trace that asked for it."""

    def test_on_change_keeps_the_fence_restart(self):
        # MOV DW,imm16 after the long shift (even parity): silicon restarts
        # fetching at +76, when the immediate's take commits. With the IR as a
        # seventh slot, a request evaluated every clock would fetch at the
        # instruction's start (+72); evaluated on queue changes it waits.
        cfg = DEFAULT.replace(room_ir=True)
        self.assertEqual(_first_fetch_after_fill(cfg), 72)
        self.assertEqual(_first_fetch_after_fill(cfg.replace(request_eval="on_change")), 76)

    def test_b2b_holds_the_start_during_a_committed_fetch(self):
        # With start_sync=b2b no instruction starts on the clock after a fetch whose
        # last clock left the request flag raised; with inflight some do.
        chain = _chain("F6", "F6-push-ld_bw-n4-pE-w2")

        def starts_on_b2b(cfg):
            m = Machine(chain, cfg)
            marked = []
            end_clock = m.queue.end_clock

            def spy(t, bus):
                end_clock(t, bus)
                if m.queue.b2b_at == t + 1:
                    marked.append(t + 1)
            m.queue.end_clock = spy
            m.run()
            starts = {t for t, _, _ in m.eu.trace}
            return marked, [t for t in marked if t in starts]

        marked, hit = starts_on_b2b(DEFAULT.replace(**REWORK))
        self.assertTrue(marked)
        self.assertEqual(hit, [])
        _, hit = starts_on_b2b(DEFAULT.replace(**{**REWORK, "start_sync": "inflight"}))
        self.assertTrue(hit)

    # The arbitration / sync options of the rework, each on the trace that asked
    # for it; the silicon order is quoted (clocks from the fill).
    def _events(self, cid, n=7, **kw):
        from validation.v35s.chains.fit import STAGE3_SEED
        cfg = DEFAULT.replace(**STAGE3_SEED).replace(**REWORK).replace(**kw)
        return [(e[0], e[1]) for e in aligned(simulate_normalized(_chain(cid.split("-")[0], cid),
                                                                   cfg))][1:n]

    def test_arbiter_b2b_store_train(self):
        # F1 store m2, 1 wait: silicon fetches twice between the writes (83 F, 87 F, 91 W).
        cid = "F1-store-m2-pE-w1"
        self.assertEqual(self._events(cid, arbiter="b2b")[2:5],
                         [(83, "fetch"), (87, "fetch"), (91, "data_write")])
        self.assertEqual(self._events(cid, arbiter="settled")[3], (87, "data_write"))

    def test_hold_run(self):
        # The closing PUSH starts right after a fetch: silicon fetches (95) before its write (101).
        cid = "F3-push-mov_aw_imm-k2-pO-w0"
        self.assertEqual(self._events(cid, arbiter="b2b", hold_run=True)[4:6],
                         [(95, "fetch"), (101, "stack_write")])
        self.assertEqual(self._events(cid, arbiter="b2b", hold_run=False)[4], (101, "stack_write"))

    def test_hold_fetch_le_q_io(self):
        # OUT after the fence at odd parity: silicon 82 F, 85 I with no IR-load delay
        # (out.nx 0), under the fourth fit's I/O structure (the EU waits for the issue).
        cid = "F1-out-m1-pO-w0"
        self.assertEqual(self._events(cid, 3, hold_fetch="le_q_io", **{**FOURTH_IO, "out.nx": 0}),
                         [(82, "fetch"), (85, "io_write")])
        self.assertEqual(self._events(cid, 2, hold_fetch="mem_le_q", **{**FOURTH_IO, "out.nx": 0}),
                         [(77, "fetch")])

    def test_take_sync_pending_end(self):
        # MOV AW,DW twice under PUSH markers: silicon's closing write at 96.
        cid = "F3-push-mov_aw_dw-k2-pE-w0"
        self.assertIn((96, "stack_write"), self._events(cid, 8, take_sync="pending_end"))
        self.assertIn((93, "stack_write"), self._events(cid, 8, take_sync="pending"))

    def test_request_hold_runs(self):
        chain = _chain("F2", "F2-push-nop-pE-w0")
        a = simulate(chain, DEFAULT.replace(**REWORK))
        b = simulate(chain, DEFAULT.replace(**{**REWORK, "request_hold": "hold"}))
        self.assertEqual(a[-1].addr, b[-1].addr)


# The second fit's structure and the integers the traces below depend on, then
# the storage options this round chose (F9 release series).
SECOND = dict(room_ir="arrival", request_eval="on_change", start_sync="b2b", take_sync="pending",
              arbiter="b2b", data_while_fetch="wait_before", hold_fetch="le_q_io", hold_run=True,
              write_wait="mem_end", post_on_take=True,
              **{"reg.exec": 0, "reg.nx": 1, "reg.pre0": 4, "push.post": 0, "push.setup": 7,
                 "push.setup_free": 3, "shift_cl.wb": 2, "out.exec": 0, "out.pre0": 1,
                 "out.setup": 6, "out.wbsync": 1})
STORAGE = dict(room_ir="arrival_idle", word_latch="byte_d", latch_read="commit", latch_hold=True,
               hold_run=False)


def _fetches(cid, n=4, **kw):
    """Fetch clocks (from the fill) after the fill fetch, under SECOND + STORAGE + kw."""
    cfg = DEFAULT.replace(**SECOND).replace(**STORAGE).replace(**kw)
    chain = _chain(cid.split("-")[0], cid)
    return [e[0] for e in aligned(simulate_normalized(chain, cfg)) if e[1] == "fetch"][1:n + 1]


class StorageOptions(unittest.TestCase):
    """The storage options of the F9 round, each on the silicon trace that asked for it
    (silicon's clocks quoted from the corpus, chains-F9-w<N>)."""

    def test_byte_latch_nop_train(self):
        # NOP train, even, 1 wait: silicon fetches at 72 and 76 (the word lands on 76 as
        # the IR loads, queue + IR one byte short of a word), then 91, 95.
        self.assertEqual(_fetches("F9-none-nop4-pE-w1"), [72, 76, 91, 95])
        self.assertEqual(_fetches("F9-none-nop4-pE-w1", word_latch="none")[:2], [72, 80])
        # A whole-word latch (port) fetches again at 80, where silicon does not.
        self.assertIn(80, _fetches("F9-none-nop4-pE-w1", word_latch="port"))

    def test_latch_read_commit(self):
        # ADD DW,imm16, even, 0 waits: the immediate's first byte is read on the delivery
        # clock (75) but committed on 76; silicon's second fetch is at 76.
        self.assertEqual(_fetches("F9-none-addi-pE-w0", 2), [72, 76])
        self.assertEqual(_fetches("F9-none-addi-pE-w0", 2, latch_read="read"), [72, 75])

    def test_latch_hold(self):
        # ES: NOP, even, 0 waits: a byte stuck in the latch since 78 goes in on 84, the
        # first clock the decoder leaves the port free; silicon fetches then.
        self.assertEqual(_fetches("F9-none-es_nop1-pE-w0", 3), [72, 75, 84])
        self.assertNotEqual(_fetches("F9-none-es_nop1-pE-w0", 3, latch_hold=False)[2], 84)

    def test_room_ir_arrival_idle(self):
        # MOV AW,DW, odd: the ModR/M is taken at 72 with the IR empty and no delivery:
        # silicon fetches at 72 (the idle half of the rule).
        self.assertEqual(_fetches("F9-none-movr_nop0-pO-w0", 1), [72])
        self.assertEqual(_fetches("F9-none-movr_nop0-pO-w0", 1, room_ir="arrival"), [73])
        # MOV AW,DW, even: MOV CL starts on the delivery clock 75 with its immediate
        # outstanding: silicon fetches at 75 (the arrival half).
        self.assertEqual(_fetches("F9-none-movr_nop0-pE-w0", 2), [72, 75])
        self.assertNotEqual(_fetches("F9-none-movr_nop0-pE-w0", 2, room_ir="idle")[1], 75)

    def test_hold_run_false(self):
        # PUSH after a NOP, even, 1 wait: the PUSH starts on the delivery clock 76;
        # silicon holds the fetch for the write (82) and fetches at 89.
        self.assertEqual(_fetches("F9-push-nop1-pE-w1", 2), [72, 89])
        self.assertEqual(_fetches("F9-push-nop1-pE-w1", 2, hold_run=True), [72, 76])

    def test_f2_release_one_byte_short(self):
        # The F2 cases the second fit lost: NOP NOP NOP at 1 wait and ES: CS: MOV AW,imm16.
        self.assertEqual(_fetches("F2-push-nop3-pE-w1", 2), [72, 76])
        self.assertEqual(_fetches("F2-push-pfx2_mov_aw_imm-pE-w0", 2), [72, 75])

    def test_storage_stays_physical(self):
        cfg = DEFAULT.replace(**SECOND).replace(**STORAGE)
        for chain in generate(["F2", "F9"], waits=(0, 1, 2)):
            m = Machine(chain, cfg)
            m.run()
            with self.subTest(chain=chain.id):
                self.assertLessEqual(m.queue.peak, QUEUE_BYTES)
                self.assertLessEqual(m.queue.latched, 1)


# The fourth fit's hand-fitted structure and integers (the staged refit starts its
# memory stage from these orders); the traces below are read under it alone.
FOURTH = dict(room_ir="arrival_idle", word_latch="byte_d", modrm_commit="byte",
              latch_read="commit", latch_hold=True, abort_fetch="retry",
              request_eval="on_change", start_sync="b2b", take_sync="pending", arbiter="b2b",
              data_while_fetch="wait_before", hold_fetch="le_q_io", write_wait="mem_end",
              post_on_take="write", mem_order="split", imm_order="after_issue", grp_mode="setup",
              rmw_shift="shift",
              **{"in.exec": 3, "in.post": 2, "in.pre": 0, "in.setup": 5, "load.pre0": 2,
                 "load_alu.grp": 2, "load_alu.grp_free": 2, "load_alu.rsetup": 2,
                 "mul.exec": 31, "mul.grp": 4, "mul.grp_free": 3, "out.exec": 0, "out.nx": 1,
                 "out.pre0": 1, "out.setup": 6, "out.wbsync": 1, "pop.exec": 2, "pop.setup": 7,
                 "pop.setup_free": 3, "pop_mem.exec": 3, "pop_mem.post": 0, "pop_mem.pre": 1,
                 "push.post": 0, "push.setup": 7, "push.setup_free": 3, "push_mem.exec": 6,
                 "push_mem.grp": 4, "push_mem.grp_free": 3, "push_mem.post": 0, "reg.exec": 0,
                 "reg.nx": 1, "reg.pre0": 4, "rmw.alu": 3, "rmw.grp": 4, "rmw.grp_free": 3,
                 "rmw.post": 0, "rmw_imm.alu": 0, "rmw_imm.grp": 1, "rmw_imm.grp_free": 3,
                 "rmw_imm.pre": 1, "rmw_imm.setup": 2, "shift_cl.exec": 7, "shift_cl.loop": 2,
                 "shift_cl.wb": 2, "shift_imm.exec": 6, "shift_imm.nx": 6, "store.post": 0,
                 "store.pre": 0, "store.pre0": 2, "store_imm.grp_free": 3, "store_imm.post": 0,
                 "store_imm.pre": 1, "store_imm.setup": 1, "ea.base_disp": 0,
                 "ea.base_index": 2, "ea.base_index_disp": 2})


def _events4(cid, n=8, **kw):
    """(clock, kind) from the fill, the fill fetch dropped, under FOURTH."""
    cfg = DEFAULT.replace(**FOURTH).replace(**kw)
    chain = _chain(cid.split("-")[0], cid)
    return [(e[0], e[1]) for e in aligned(simulate_normalized(chain, cfg))][1:n + 1]


class MemoryTemplates(unittest.TestCase):
    """The fourth fit's memory step orders and the aborted fetch, each on the silicon
    trace that asked for it (silicon's clocks quoted from the corpus)."""

    def test_split_direct_and_modrm_store(self):
        # One store template for both formats: MOV [BW],AW (89 07) after the PUSH
        # marker writes at 87; the direct store marker A3 after the fence fetches at
        # 75 and writes at 78 (its address bytes 2 clocks after its start, pre0).
        self.assertEqual(_events4("F5-push-st_bw-k1-pE-w0", 4)[1:4],
                         [(81, "fetch"), (84, "fetch"), (87, "data_write")])
        self.assertEqual(_events4("F1-store-m2-pE-w0", 2), [(75, "fetch"), (78, "data_write")])
        # The old order with the ModR/M store's pre 0 takes A3's bytes at once.
        self.assertEqual(_events4("F1-store-m2-pE-w0", 1, mem_order="pre_take"),
                         [(73, "fetch")])

    def test_split_displacement_follows_the_modrm(self):
        # MOV AW,[BW+d16], odd: the displacement leaves right after the ModR/M byte
        # (no take sync between them): silicon fetches back to back, 81 84, reads at 87.
        self.assertEqual(_events4("F4-push-ld_bw_d16-k1-pO-w0", 4)[1:4],
                         [(81, "fetch"), (84, "fetch"), (87, "data_read")])
        # [BW+IX+d16]: two EA clocks before the displacement: silicon's fetch is at 85.
        self.assertEqual(_events4("F4-push-ld_bw_ix_d16-k1-pO-w0", 4)[1:4],
                         [(81, "fetch"), (85, "fetch"), (88, "data_read")])

    def test_post_on_take_write(self):
        # MOV AW,[BW+d16], even: the read waits out the take sync and meets the fetch
        # raised on 87 (silicon F81 F84 F87 R90); posted on the take clock it wins at 87.
        cid = "F4-push-ld_bw_d16-k1-pE-w0"
        self.assertEqual(_events4(cid, 5)[1:5], [(81, "fetch"), (84, "fetch"), (87, "fetch"),
                                                 (90, "data_read")])
        self.assertIn((87, "data_read"), _events4(cid, 5, post_on_take=True))

    def test_imm_after_issue(self):
        # CMP [BW],imm16, odd: silicon reads first and fetches after (R88 F91 F94): the
        # immediate's bytes leave once the read is on the bus. Taken with the address
        # bytes they free a word before the read (the fetch goes first).
        cid = "F5-push-cmp_m_imm-k1-pO-w0"
        kinds = lambda ev: [k for _, k in ev[1:4]]
        self.assertEqual(kinds(_events4(cid, 4)), ["fetch", "data_read", "fetch"])
        self.assertEqual(kinds(_events4(cid, 4, imm_order="with_addr")),
                         ["fetch", "fetch", "data_read"])

    def test_group_setup(self):
        # INC [BW], even, 2 waits: the read issues 3 clocks after the second fetch
        # ends (silicon F83 F88 R95); as EU clocks the group decode overlaps it (R93).
        cid = "F5-push-inc_m-k1-pE-w2"
        self.assertEqual(_events4(cid, 4)[1:4], [(83, "fetch"), (88, "fetch"), (95, "data_read")])
        self.assertIn((93, "data_read"),
                      _events4(cid, 5, grp_mode="clocks", **{"rmw.grp": 3}))

    def test_rmw_shift(self):
        # SHL [BW],1, odd: the write comes 11 clocks after the read (silicon R89 W100).
        cid = "F5-push-shl_m1-k1-pO-w0"
        self.assertEqual(_events4(cid, 4)[2:4], [(89, "data_read"), (100, "data_write")])
        self.assertIn((94, "data_write"), _events4(cid, 4, rmw_shift="alu"))

    def test_abort_fetch(self):
        # Two MOV [BW],AW, even, 0 waits: the second starts, takes its ModR/M and loads
        # the IR on 90 with room for one word; silicon runs no fetch there and writes
        # at 95 (W87 W95 F98).
        cid = "F5-push-st_bw-k2-pE-w0"
        self.assertEqual(_events4(cid, 6)[1:6], [(81, "fetch"), (84, "fetch"),
                                                 (87, "data_write"), (95, "data_write"),
                                                 (98, "fetch")])
        self.assertIn((90, "fetch"), _events4(cid, 6, abort_fetch=False))
        # Two MOV AW,[BW], even: silicon fetches right after the second read (R97 F100);
        # one_word leaves the request down until the next queue change (102).
        cid = "F4-push-ld_bw-k2-pE-w0"
        self.assertEqual(_events4(cid, 6)[3:6], [(87, "data_read"), (97, "data_read"),
                                                 (100, "fetch")])
        self.assertIn((102, "fetch"), _events4(cid, 6, abort_fetch="one_word"))

    def test_shift_cl_loop(self):
        # MOV CL,0 ; SHL AW,CL: a zero count skips the loop clocks; LS (count 31) keeps
        # its 71 clocks (exec + loop + 2 x 31).
        from validation.v35s.chains.sim.templates import steps
        cfg = DEFAULT.replace(**FOURTH)
        for count, clocks in ((0, 7), (1, 9)):
            op = decode(bytes([0xD3, 0xE0]), 0, {**FORMS_REGS, "CW": count})
            self.assertIn(("clocks", clocks), steps(op, cfg))
        op = decode(bytes([0xD3, 0xE0]), 0, {**FORMS_REGS, "CW": 31})
        self.assertEqual(sum(s[1] for s in steps(op, cfg) if s[0] == "clocks"), 71)

    def test_group_and_modrm_formats(self):
        # The format properties the templates read: group opcode, ModR/M byte.
        regs = dict(FORMS_REGS)
        self.assertTrue(decode(bytes([0xFF, 0x07]), 0, regs).group)        # INC [BW]
        self.assertTrue(decode(bytes([0xC7, 0x07, 0, 0]), 0, regs).group)  # MOV [BW],imm16
        self.assertFalse(decode(bytes([0x01, 0x07]), 0, regs).group)       # ADD [BW],AW
        self.assertFalse(decode(bytes([0x85, 0x07]), 0, regs).group)       # TEST [BW],AW
        self.assertFalse(decode(bytes([0xA3, 0, 0x0C]), 0, regs).modrm)    # MOV [0C00h],AW

    def test_room_ir_arrival_ready(self):
        # The IR counts as room only once the loader may load it (past nx).
        m = Machine(_chain("F0", "F0-ls-pE-w0"), DEFAULT.replace(room_ir="arrival_ready"))
        q, d = m.queue, m.decoder
        q.arrive(0x10048, 0, 0)
        d.need, d.ready_at = 0, 10
        self.assertEqual(q.room(5), QUEUE_BYTES - 2)
        self.assertEqual(q.room(10), QUEUE_BYTES + 1 - 2)


# The fifth fit's I/O mechanism (fit.STAGE3_SEED), on top of FOURTH.
FIFTH_IO = dict(io_release="post", io_post="start", io_count="nowait", port_latch="relatch",
                port_sync="none", io_hold="posted_b2b", io_interlock="reg_pfx", io_recover=2,
                hold_fetch="le_q",
                **{"out.pre": 3, "out.pre0": 1, "out.exec": 2, "out.setup": 8, "out.lead": 2,
                   "out.relatch": 3, "out.nx": 1, "out.wbsync": 1, "in.pre": 3, "in.pre0": 0,
                   "in.setup": 8, "in.lead": 0, "in.post": 4, "in.relatch": 3})


def _events5(cid, n=8, **kw):
    """(clock, kind) from the fill, the fill fetch dropped, under FOURTH + FIFTH_IO."""
    cfg = DEFAULT.replace(**FOURTH).replace(**FIFTH_IO).replace(**kw)
    chain = _chain(cid.split("-")[0], cid)
    return [(e[0], e[1]) for e in aligned(simulate_normalized(chain, cfg))][1:n + 1]


def _io(cid, **kw):
    return [e[0] for e in _events5(cid, 12, **kw) if e[1] == "io_write" or e[1] == "io_read"]


class IOMechanism(unittest.TestCase):
    """The fifth fit's I/O rules, each on the silicon trace that asked for it and
    against the alternative it replaced (silicon clocks quoted from the corpus)."""

    def test_count_skips_wait_states(self):
        # OUT after NOP NOP, even, 1 wait, no fetch near: silicon I/O at 90, 10 clocks
        # after the OUT's start; the fourth fit's fetch-free count gives the END write 2 late.
        self.assertEqual(_io("F2-out-nop2-pE-w1"), [90, 189])
        self.assertEqual(_io("F2-out-nop2-pE-w1", io_count="fetch_free"), [90, 191])

    def test_count_from_the_start(self):
        # OUT after MOV AW,imm16, odd, 1 wait: the fetch at 80 has its wait state before the
        # port take and still delays the I/O (silicon 91); counted from the take, 90.
        self.assertEqual(_io("F2-out-mov_aw_imm-pO-w1")[0], 91)
        self.assertEqual(_io("F2-out-mov_aw_imm-pO-w1", io_post="take")[0], 90)

    def test_lead_lets_an_older_fetch_go_first(self):
        # OUT after NOP, even, 0 waits: the fetch held since the port take runs at 84 and
        # the I/O follows at 87 (silicon); with no lead the I/O goes first at 86.
        self.assertEqual(_events5("F2-out-nop-pE-w0", 3)[1:3], [(84, "fetch"), (87, "io_write")])
        self.assertEqual(_events5("F2-out-nop-pE-w0", 2, **{"out.lead": 0})[1], (86, "io_write"))

    def test_port_latch_relatch(self):
        # Two OUT markers, even, 0 waits: silicon I/O at 86 and 96 (one OUT marker: 84).
        self.assertEqual(_io("F1-out-m2-pE-w0")[:2], [86, 96])
        self.assertEqual(_io("F1-out-m2-pE-w0", port_latch="none")[:2], [84, 92])
        # the other branch: the take waits for the I/O, which then goes undelayed
        self.assertEqual(_io("F1-out-m2-pE-w0", port_latch="wait")[:2], [84, 91])

    def test_follower_queues_behind_the_io(self):
        # PUSH; OUT; PUSH, odd, 1 wait: the closing PUSH writes 6 clocks after the I/O
        # (silicon I 93, W 99): it was posted before the I/O issued and counted from it.
        self.assertEqual(_events5("F5-push-out_imm_al-k1-pO-w1", 4)[2:4],
                         [(93, "io_write"), (99, "stack_write")])
        self.assertEqual(_events5("F5-push-out_imm_al-k1-pO-w1", 4, io_release="issue")[2:4],
                         [(98, "io_write"), (105, "stack_write")])

    def test_interlock_register_only(self):
        # OUT; NOP; OUT, even, 0 waits: the NOP starts when the first I/O issues, so the
        # closing OUT's I/O is at 98 (silicon); without the interlock, 94.
        self.assertIn((98, "io_write"), _events5("F3-out-nop-k1-pE-w0", 6))
        self.assertIn((94, "io_write"), _events5("F3-out-nop-k1-pE-w0", 6, io_interlock="none"))

    def test_imm_latch_alternative(self):
        # OUT then MOV AW,imm16 drainers, even, 0 waits: silicon fetches at 88 (the
        # immediate taken after the I/O cycle). The interlock or the data-latch rule gives it.
        drain = "F6-out-push_aw-n2-pE-w0"
        self.assertEqual(_events5(drain, 3)[2], (88, "fetch"))
        self.assertEqual(_events5(drain, 3, io_interlock="none", imm_latch="wait")[2], (88, "fetch"))
        self.assertEqual(_events5(drain, 3, io_interlock="none")[2], (87, "fetch"))

    def test_io_recover(self):
        # OUT then MOV AW,[BW], odd, 0 waits: the read waits 2 clocks after the I/O cycle
        # (silicon I 85, R 90); without the recovery, R 88.
        self.assertEqual(_events5("F4-out-ld_bw-k1-pO-w0", 3)[1:3], [(85, "io_write"), (90, "data_read")])
        self.assertEqual(_events5("F4-out-ld_bw-k1-pO-w0", 3, io_recover=0)[2], (88, "data_read"))

    def test_back_to_back_fetch_not_held(self):
        # OUT after MOV AW,imm16, even, 1 wait: silicon fetches 76, 80, 84 back to back
        # then the I/O at 92; holding the committed fetch drops it.
        self.assertEqual(_events5("F2-out-mov_aw_imm-pE-w1", 4),
                         [(76, "fetch"), (80, "fetch"), (84, "fetch"), (92, "io_write")])
        self.assertNotIn((84, "fetch"), _events5("F2-out-mov_aw_imm-pE-w1", 4, io_hold="posted"))

    def test_write_back_from_the_end(self):
        # PUSH; MOV AW,[BW]; OUT, odd, 1 wait: the OUT waits for the load's write-back
        # (silicon I/O 107; none: 105). OUT; MOV AW,[BW]; OUT, odd, 1 wait: a fetch holds
        # the closing OUT's start past the write-back anyway (silicon 111): counted from
        # the load's end it is absorbed, counted from the OUT's start it adds 2.
        wb = {"load.wb": 2}
        self.assertEqual(_io("F7-push-ld_bw-out_imm_al-pO-w1", wb_from="end", **wb)[0], 107)
        self.assertEqual(_io("F7-push-ld_bw-out_imm_al-pO-w1")[0], 105)
        self.assertEqual(_io("F4-out-ld_bw-k1-pO-w1", wb_from="end", **wb)[1], 111)
        self.assertEqual(_io("F4-out-ld_bw-k1-pO-w1", wb_from="start", **wb)[1], 113)

    def test_end_marker_and_halt(self):
        # The END block's OUT DW,AL goes on before its I/O: the HALT then raises no fetch
        # and the run still ends on the I/O (F0 LS, silicon 76 F, 79 F, 87 I).
        self.assertEqual(_events5("F0-ls-pE-w0", 3), [(76, "fetch"), (79, "fetch"), (87, "io_write")])

    def test_default_keeps_f0(self):
        results = score_family(_runs("F0"), DEFAULT)
        self.assertEqual([sc.run_id for _, _, sc in results if not sc.exact], [])


# The sixth fit's data latch and IN template, on top of FOURTH + FIFTH_IO.
SIXTH = dict(wlatch=4, wlatch_cls="port", wlatch_hold=True, wlatch_src="write_imm_read",
             wlatch_imm="reg", grp_free_bus=True, **{"in.post": 2})


def _events6(cid, n=8, **kw):
    """(clock, kind) from the fill, the fill fetch dropped, under FOURTH + FIFTH_IO + SIXTH."""
    return _events5(cid, n, **{**SIXTH, **kw})


class DataLatch(unittest.TestCase):
    """The sixth fit: a datum occupies the bus unit's data latch for 4 clocks from entering
    it, and an I/O form with a port byte does not start while it is busy, holding fetches
    meanwhile. Each rule on the silicon trace that asked for it and against the
    alternative it replaced (silicon clocks quoted from the corpus)."""

    def test_write_holds_the_latch_past_a_zero_wait_cycle(self):
        # OUT; MOV [BW],AW; OUT, even, 0 waits: the write issues at 90 and ends at 92; the
        # closing OUT starts at 94 = issue+4 (port-take fetch 97, I/O 104), not at 93.
        self.assertEqual(_events6("F5-out-st_bw-k1-pE-w0", 6)[3:6],
                         [(90, "data_write"), (97, "fetch"), (104, "io_write")])
        self.assertEqual(_events6("F5-out-st_bw-k1-pE-w0", 6, wlatch=0)[4:6],
                         [(96, "fetch"), (103, "io_write")])
        # issue+4 and not 3 or 5
        self.assertNotEqual(_events6("F5-out-st_bw-k1-pE-w0", 6, wlatch=5)[4], (97, "fetch"))

    def test_waiting_io_holds_fetches(self):
        # OUT; MOV AW,[BW]; PUSH AW; OUT, even, 0 waits: PUSH writes at 101; silicon's pending
        # fetch waits for the OUT's start at 105 (fetch 105, port take 108, I/O 115). Without
        # the hold it goes at 104, the start waits for it and the I/O comes at 118.
        cid = "F7-out-ld_bw-push_aw-pE-w0"
        self.assertEqual(_events6(cid, 8)[4:8], [(101, "stack_write"), (105, "fetch"),
                                                 (108, "fetch"), (115, "io_write")])
        self.assertEqual(_events6(cid, 8, wlatch_hold=False)[5:8],
                         [(104, "fetch"), (115, "fetch"), (118, "io_write")])

    def test_in_waits_like_out_but_dw_forms_do_not(self):
        # PUSH; IN AL,imm, even, 0 waits: the IN starts at 82 (fetch 82, I/O 92) as an OUT
        # would; PUSH; IN AL,DW starts at once (fetch 81, I/O 88).
        self.assertEqual(_events6("F5-push-in_al_imm-k1-pE-w0", 4)[1:4],
                         [(82, "fetch"), (85, "fetch"), (92, "io_read")])
        self.assertEqual(_events6("F5-push-in_al_imm-k1-pE-w0", 4, wlatch_cls="out")[3],
                         (91, "io_read"))
        self.assertEqual(_events6("F5-push-in_al_dw-k1-pE-w0", 3)[1:3],
                         [(81, "fetch"), (88, "io_read")])
        self.assertEqual(_events6("F5-push-in_al_dw-k1-pE-w0", 3, wlatch_cls="io")[1:3],
                         [(82, "fetch"), (89, "io_read")])

    def test_immediate_enters_the_latch(self):
        # PUSH; MOV AW,imm16; IN AL,imm: at 0 waits the immediate's take at 85 holds the IN to
        # 89 (port-take fetch 92, I/O 99); at 1 wait the IN starts at the MOV's end anyway
        # (I/O 101), which an end-relative write-back (imm.wb 1) does not give.
        self.assertEqual(_events6("F6-push-in_al_imm-n1-pE-w0", 5)[3:5],
                         [(92, "fetch"), (99, "io_read")])
        self.assertEqual(_events6("F6-push-in_al_imm-n1-pE-w0", 5, wlatch_src="write")[3:5],
                         [(88, "fetch"), (98, "io_read")])
        self.assertEqual(_events6("F6-push-in_al_imm-n1-pE-w1", 5)[4], (101, "io_read"))

    def test_read_data_enters_the_latch(self):
        # PUSH; MOV AW,[BW]; OUT, odd, 1 wait: the read (88) delivers at 92 and holds the
        # latch to 96: the OUT starts then (port-take fetch 99, I/O 107). Without the read
        # source, and no load write-back (FOURTH + FIFTH_IO have none), the I/O is at 105.
        cid = "F7-push-ld_bw-out_imm_al-pO-w1"
        self.assertEqual(_io(cid, **SIXTH)[0], 107)
        self.assertEqual(_io(cid, **{**SIXTH, "wlatch_src": "write_imm"})[0], 105)

    def test_memory_immediate_is_not_latched(self):
        # OUT; MOV [BW+d16],imm16; OUT, even, 1 wait: the store's immediate is its write
        # data (W96); the closing OUT's I/O is at 112 (silicon). Latched on its take it is 114.
        st = {"store_imm.pre": 1, "store_imm.grp": 1, "store_imm.grp_free": 3,
              "store_imm.setup": 0, "store_imm.post": 0}
        cid = "F5-out-st_imm_bw_d16-k1-pE-w1"
        self.assertEqual(_events6(cid, 8, **st)[7], (112, "io_write"))
        self.assertEqual(_events6(cid, 8, wlatch_imm="all", **st)[7], (114, "io_write"))

    def test_in_ends_two_clocks_after_its_data(self):
        # PUSH; IN AL,imm; PUSH, even, 0 waits: the I/O at 92 delivers at 95; the PUSH writes
        # at 103 (start 97). With the fifth fit's in.post 4, 105.
        self.assertEqual(_events6("F5-push-in_al_imm-k1-pE-w0", 5)[3:5],
                         [(92, "io_read"), (103, "stack_write")])
        self.assertEqual(_events6("F5-push-in_al_imm-k1-pE-w0", 5, **{"in.post": 4})[4],
                         (105, "stack_write"))

    def test_group_clocks_wait_for_the_bus(self):
        # OUT; INC [BW], 1 wait: the read is 3 clocks after ADD [BW],AW's even behind the
        # OUT: odd 94 (after the I/O and its recovery), even 94 (after the fetch at 88).
        # Counted while the I/O waits, both come 2-3 clocks early.
        self.assertEqual(_events6("F5-out-inc_m-k1-pO-w1", 3)[2], (94, "data_read"))
        self.assertEqual(_events6("F5-out-inc_m-k1-pE-w1", 4)[3], (94, "data_read"))
        self.assertEqual(_events6("F5-out-inc_m-k1-pO-w1", 3, grp_free_bus=False)[2],
                         (91, "data_read"))
        self.assertEqual(_events6("F5-out-inc_m-k1-pE-w1", 4, grp_free_bus=False)[3],
                         (92, "data_read"))

    def test_default_has_no_latch(self):
        self.assertEqual(DEFAULT.wlatch, 0)
        results = score_family(_runs("F0"), DEFAULT)
        self.assertEqual([sc.run_id for _, _, sc in results if not sc.exact], [])


# The seventh fit's immediate memory forms and DW I/O forms, on top of FOURTH + FIFTH_IO +
# SIXTH (the integers are the hand fit's for the classes involved).
SEVENTH = dict(grp_read="rmw_slot_any", rmw_imm_issue="rmw", rmw_write_issue="immediate",
               imm_head="disp_ea", hold_count="ahead", sync_req="either", dw_count="bus",
               **{"rmw_imm.grp": 3, "rmw_imm.grp_free": 1, "rmw_imm.alu": 3,
                  "rmw_imm.setup_free": 0, "rmw_imm.pre": 0, "rmw_imm.post": 0,
                  "rmw_imm.setup": 0, "store_imm.grp": 3, "store_imm.grp_free": 1,
                  "store_imm.pre": 0, "store_imm.setup": 0, "store_imm.post": 0,
                  "out.pre0": 0, "out.setup0": 8, "in.setup0": 7, "ea.base_disp": 2})


def _events7(cid, n=8, **kw):
    """(clock, kind) from the fill, the fill fetch dropped, under the seventh fit's rules."""
    return _events6(cid, n, **{**SEVENTH, **kw})


class ImmediateAndDWForms(unittest.TestCase):
    """The seventh fit: CMP [BW],imm16 runs its group's RMW template with the write's bus
    slot kept, an immediate RMW posts its write at the start of its ALU step, a fetch hold
    does not count the running instruction's own queued bytes, an immediate form's
    displacement precedes its EA clocks, and a DW form's I/O loses its first clock to a
    bus cycle starting on it. Each against the alternative it replaced, silicon clocks
    quoted from the corpus."""

    def test_cmp_keeps_the_write_slot(self):
        # PUSH; CMP [BW],imm16, odd, 0 waits: R88 F91 F94, PUSH write 103 (ADD [BW],imm16
        # gives R88 F91 W94 S103: the fetch at 94 runs in the left-out write's slot with one
        # byte of room). As load_alu the read is at 89; a slot run only on the request rule
        # leaves 94 empty and the PUSH writes at 103 behind F91 alone.
        cid = "F5-push-cmp_m_imm-k1-pO-w0"
        self.assertEqual(_events7(cid, 6)[2:6], [(88, "data_read"), (91, "fetch"),
                                                 (94, "fetch"), (103, "stack_write")])
        self.assertEqual(_events7(cid, 3, grp_read="own")[2], (89, "data_read"))
        self.assertEqual(_events7(cid, 5, grp_read="rmw_slot")[3:5],
                         [(91, "fetch"), (103, "stack_write")])

    def test_immediate_rmw_posts_its_write_at_the_alu_step(self):
        # PUSH; ADD [BW],imm16, even, 0 waits: R88 W93 F96 (the posted write holds the
        # fetch); posted after the ALU step the fetch goes at 91 and the write at 94.
        cid = "F5-push-add_m_imm-k1-pE-w0"
        self.assertEqual(_events7(cid, 6)[3:6], [(88, "data_read"), (93, "data_write"),
                                                 (96, "fetch")])
        self.assertEqual(_events7(cid, 6, rmw_imm_issue="after_step")[4:6],
                         [(91, "fetch"), (94, "data_write")])

    def test_hold_counts_only_bytes_ahead(self):
        # OUT; ADD [BW],imm16, even, 0 waits: I/O 84, fetch 87, read 91. Counting the
        # instruction's own immediate (still queued) as queue bytes the posted read holds
        # the fetch at 87.
        cid = "F5-out-add_m_imm-k1-pE-w0"
        self.assertEqual(_events7(cid, 4), [(77, "fetch"), (84, "io_write"), (87, "fetch"),
                                            (91, "data_read")])
        self.assertEqual(_events7(cid, 3, hold_count="queue")[2], (91, "data_read"))

    def test_displacement_before_the_ea_and_its_sync(self):
        # PUSH; MOV [BW+d16],imm16, odd, 0 waits: F81 F84 W88. EA before the displacement
        # (split) gives W90; a sync that also waits for the request raised on the take
        # clock (the fetch at 84) gives W91. (The even 0-wait cell, W91, is a known miss
        # of this rule: it waits for the fetch at 84 there.)
        cid = "F5-push-st_imm_bw_d16-k1-pO-w0"
        self.assertEqual(_events7(cid, 4)[1:4], [(81, "fetch"), (84, "fetch"),
                                                 (88, "data_write")])
        self.assertEqual(_events7(cid, 4, imm_head="split")[3], (90, "data_write"))
        self.assertEqual(_events7(cid, 4, sync_req="take")[3], (91, "data_write"))

    def test_dw_io_loses_its_first_clock_to_a_bus_cycle(self):
        # IN AL,DW after PUSH: odd (no fetch on the start clock) I/O at s+6 = 87; even (a
        # fetch at its start, 81) at 88, 87 when the start clock counts. Behind an OUT's
        # I/O (84) the request moves into the slot on the I/O's first clock: I/O 91, 90 if
        # that clock counts.
        self.assertEqual(_events7("F5-push-in_al_dw-k1-pO-w0", 2)[1], (87, "io_read"))
        self.assertEqual(_events7("F5-push-in_al_dw-k1-pE-w0", 3)[1:3],
                         [(81, "fetch"), (88, "io_read")])
        self.assertEqual(_events7("F5-push-in_al_dw-k1-pE-w0", 3, dw_count="all")[2],
                         (87, "io_read"))
        self.assertEqual(_events7("F5-out-in_al_dw-k1-pE-w0", 3)[2], (91, "io_read"))
        self.assertEqual(_events7("F5-out-in_al_dw-k1-pE-w0", 3, dw_count="fetch")[2],
                         (90, "io_read"))
        # the END block's OUT DW,AW stays exact (fetch on its start clock 79, I/O 87)
        self.assertEqual(_events7("F0-ls-pE-w0", 3), [(76, "fetch"), (79, "fetch"),
                                                      (87, "io_write")])


# WP13 (F10, F11): the DW OUT's own setup equals IN's, the HALT after the END block's OUT
# takes a clock of its I/O, and the queue serves no double read on a fetch's late clocks.
WP13 = dict(halt_status=True, late_read=True, **{"out.setup0": 7})


def _events13(cid, n=8, **kw):
    """(clock, kind) from the fill, the fill fetch dropped, under the seventh fit + WP13."""
    return _events7(cid, n, **{**WP13, **kw})


class HaltAndLateRead(unittest.TestCase):
    """WP13, each rule against the alternative it replaced, silicon clocks quoted from the
    corpus (chains-F10-w<N>, chains-F11-w<N>, chains-F9-w<N>, chains-F0-w0)."""

    def test_halt_takes_a_clock_of_the_waiting_io(self):
        # MOV DW,0040h ; OUT DW,AL then MOV CL, even, 0 waits: F76 F79 I86 (s+7, OUT at 79,
        # as IN AL,DW); with port FF04h the same. The END block's MOV DW,0FF00h ; OUT DW,AL
        # then HALT, same fetches: I87 (s+8). Setup0 7 without the HALT clock gives the END
        # I86; the seventh fit's setup0 8 gives the free-standing pair I87.
        self.assertEqual(_events13("F10-none-movdwi-outdw-pE-w0", 3),
                         [(76, "fetch"), (79, "fetch"), (86, "io_write")])
        self.assertEqual(_events13("F10-none-movdwff-outdw-pO-w1", 3)[2], (88, "io_write"))
        self.assertEqual(_events13("F0-ls-pE-w0", 3), [(76, "fetch"), (79, "fetch"),
                                                       (87, "io_write")])
        self.assertEqual(_events13("F0-ls-pE-w0", 3, halt_status=False)[2], (86, "io_write"))
        self.assertEqual(_events13("F10-none-movdwi-outdw-pE-w0", 3, halt_status=False,
                                   **{"out.setup0": 8})[2], (87, "io_write"))

    def test_no_double_read_on_a_fetch_late_clock(self):
        # LS MOV AW,DW LS END, even, 1 wait: fetches 72 76 80, then the trailing shift ends
        # and the END's refill starts at 162 (MOV CL's immediate falls on the last clock of
        # the fetch at 76, with the next opcode loading: taken at 80 instead, its sync
        # waits for the fetch raised there). Taking it on that last clock: 159. The F9 pair
        # MOV AW,DW x2 the same at 166 / 163; MOV AW,DW NOP (the take on a fetch's issue
        # clock) is unchanged at 166.
        self.assertEqual(_events13("F11-none-n0-movr-pE-w1", 4),
                         [(72, "fetch"), (76, "fetch"), (80, "fetch"), (162, "fetch")])
        self.assertEqual(_events13("F11-none-n0-movr-pE-w1", 4, late_read=False)[3],
                         (159, "fetch"))
        self.assertEqual(_events13("F11-none-n0-movr-pE-w2", 4)[3], (165, "fetch"))
        self.assertEqual(_events13("F9-none-movr2-pE-w1", 5)[4], (166, "fetch"))
        self.assertEqual(_events13("F9-none-movr2-pE-w1", 5, late_read=False)[4],
                         (163, "fetch"))
        for late in (True, False):
            self.assertEqual(_events13("F9-none-movr_nop1-pE-w1", 5, late_read=late)[4],
                             (166, "fetch"))


# WP16 (F12): the OUT after a register form, the ModR/M start on a back-to-back fetch, the
# shift forms, the 4-byte immediate form's fetch and sync, and the IR that cannot load.
WP16 = dict(room_ir_ready=True, wlatch_imm="reg_last", start_sync="b2b_modrm",
            latch_midtake=True, imm_landed=True, shift_count="late",
            **{"shift_imm.exec": 6, "shift_imm.exec0": 5, "shift_imm.cpre": 2,
               "shift_imm.wb": 2, "shift_imm.nx": 0})


def _events16(cid, n=8, **kw):
    """(clock, kind) from the fill, the fill fetch dropped, under WP13 + WP16."""
    return _events13(cid, n, **{**WP16, **kw})


class OutAfterRegisterForm(unittest.TestCase):
    """WP16, the F12 rules, each against the alternative it replaced; silicon clocks from
    the fill quoted from the corpus (chains-F12-w<N>, chains-F3-w<N>, chains-F11-w<N>)."""

    def test_register_result_passes_the_data_latch(self):
        # OUT; NOP NOP; MOV AW,DW; OUT, even, 0 waits: M0 84, MOV AW,DW's ModR/M taken at 92
        # (fetch 92), silicon has no fetch at 95, the OUT starts at 96: fetch 99, I/O 106.
        # Without the latch (wlatch_imm=reg) the OUT starts at take+3: fetch 95, I/O 105.
        # The PUSH twin is no I/O form: its write is at 98 under both.
        cid = "F12-a-out-n2-movr-pE-w0"
        self.assertEqual(_events16(cid, 6)[3:6], [(92, "fetch"), (99, "fetch"),
                                                  (106, "io_write")])
        self.assertEqual(_events16(cid, 6, wlatch_imm="reg")[4:6], [(95, "fetch"),
                                                                    (105, "io_write")])
        for v in ("reg", "reg_last"):
            self.assertEqual(_events16("F12-a-push-n2-movr-pE-w0", 5, wlatch_imm=v)[4],
                             (98, "stack_write"))

    def test_a_modrm_form_alone_waits_out_the_back_to_back_fetch(self):
        # OUT; NOP; MOV AW,DW; OUT, even, 1 wait: ModR/M taken at 89, the fetch back to back
        # at 93, the OUT starts there: fetch 97, I/O 105. b2b holds it to 97 (I/O 109).
        # PUSH; MOV AW,DW x2, even, 0 waits: the second MOV AW,DW is held to the end of the
        # back-to-back fetch (PUSH write 96); not holding it (inflight) gives 93.
        cid = "F12-a-out-n1-movr-pE-w1"
        self.assertEqual(_events16(cid, 6)[3:6], [(93, "fetch"), (97, "fetch"),
                                                  (105, "io_write")])
        self.assertEqual(_events16(cid, 6, start_sync="b2b")[4:6], [(105, "fetch"),
                                                                    (109, "io_write")])
        cid = "F3-push-mov_aw_dw-k2-pE-w0"
        self.assertEqual(_events16(cid, 5)[4], (96, "stack_write"))
        self.assertEqual(_events16(cid, 5, start_sync="inflight")[4], (93, "stack_write"))

    def test_shift_without_a_count_byte_is_a_clock_shorter(self):
        # OUT; NOP NOP; SHL AW,1; OUT, even, 0 waits: the port-take fetch at 107, I/O 114;
        # PUSH; SHL AW,1 x2, odd, 0 waits: fetch 91, PUSH write 107. With SHL AW,1 at
        # SHL AW,4's exec (6): 108/115 and 92/109. Taking the clock from the OUT's write-back
        # sync instead (shift_imm.wb 1) fixes the OUT and leaves the PUSH late.
        cid = "F12-a-out-n2-shl1-pE-w0"
        self.assertEqual(_events16(cid, 6)[4:6], [(107, "fetch"), (114, "io_write")])
        self.assertEqual(_events16(cid, 6, **{"shift_imm.exec0": 6})[4:6],
                         [(108, "fetch"), (115, "io_write")])
        cid = "F3-push-shl1-k2-pO-w0"
        self.assertEqual(_events16(cid, 4)[2:4], [(91, "fetch"), (107, "stack_write")])
        self.assertEqual(_events16(cid, 4, **{"shift_imm.exec0": 6})[2:4],
                         [(92, "fetch"), (109, "stack_write")])

    def test_shift_count_byte_two_clocks_after_the_modrm(self):
        # NOP x3; SHL AW,4 marker-less, even, 0 waits: fetches 72 80 87 107; the count byte
        # with the ModR/M gives 85 105.
        cid = "F12-b-none-n3-shli-pE-w0"
        self.assertEqual(_events16(cid, 4), [(72, "fetch"), (80, "fetch"), (87, "fetch"),
                                             (107, "fetch")])
        self.assertEqual(_events16(cid, 4, shift_count="with_modrm")[2:4],
                         [(85, "fetch"), (105, "fetch")])

    def test_latched_byte_counts_while_mid_take(self):
        # NOP x2; ADD DW,imm16 marker-less, even, 1 wait: the ModR/M taken on the delivery
        # clock 80 with the immediate outstanding: no fetch there, fetches 72 76 84 88. The
        # uncounted latched byte fetches at 80. MOV AW,DW in the same slot (nothing
        # outstanding) fetches at 80 under both.
        cid = "F12-b-none-n2-addi-pE-w1"
        self.assertEqual(_events16(cid, 4), [(72, "fetch"), (76, "fetch"), (84, "fetch"),
                                             (88, "fetch")])
        self.assertEqual(_events16(cid, 3, latch_midtake=False)[2], (80, "fetch"))
        for v in (True, False):
            self.assertEqual(_events16("F11-none-n2-movr-pE-w1", 3, latch_midtake=v)[2],
                             (80, "fetch"))

    def test_immediate_landed_with_the_word_syncs_a_clock_later(self):
        # PUSH; ADD DW,imm16; PUSH, even, 1 wait: the immediate completes at 86 as the word
        # of the fetch at 82 lands; fetches 82 86 90 and the PUSH write at 100 (the ADD
        # waits for the fetch issued at 90). Counting the fetches pending on the take clock
        # gives the write at 96.
        cid = "F12-b-push-n0-addi-pE-w1"
        self.assertEqual(_events16(cid, 5), [(78, "stack_write"), (82, "fetch"),
                                             (86, "fetch"), (90, "fetch"),
                                             (100, "stack_write")])
        self.assertEqual(_events16(cid, 5, imm_landed=False)[4], (96, "stack_write"))

    def test_dw_out_does_not_wait_for_the_shift_write_back(self):
        # LS ; OUT DW,AL marker-less, even, 0 waits: fetch 76, I/O 79 (the OUT's own fetch
        # pattern after the long shift, as the END block's). Waiting out the shift's 2-clock
        # write-back as the port form does (wbsync0 = wbsync = 1): fetch 72, I/O 80.
        cid = "F10-none-none-outdw-pE-w0"
        self.assertEqual(_events16(cid, 3, **{"out.wbsync0": 0})[:2], [(76, "fetch"),
                                                                       (79, "io_write")])
        self.assertEqual(_events16(cid, 3, **{"out.wbsync0": 1})[:2], [(72, "fetch"),
                                                                       (80, "io_write")])

    def test_an_ir_that_cannot_load_is_no_room(self):
        # OUT; NOP x3; SHL AW,1; OUT, odd, 1 wait: with the shift's next-opcode load held 10
        # clocks (the eighth fit's shift_imm.nx) the empty IR counted as room raised a fetch
        # whose word found the queue full: QueueOverflow. With room_ir_ready the same
        # integers run within six bytes; at nx 0 the rule changes nothing.
        cid = "F12-a-out-n3-shl1-pO-w1"
        with self.assertRaises(QueueOverflow):
            _events16(cid, 6, room_ir_ready=False, **{"shift_imm.nx": 10})
        _events16(cid, 6, **{"shift_imm.nx": 10})
        self.assertEqual(_events16(cid, 8), _events16(cid, 8, room_ir_ready=False))
        self.assertEqual(_events16(cid, 6)[:4], [(82, "fetch"), (86, "io_write"),
                                                 (90, "fetch"), (94, "fetch")])


WP14 = dict(refresh_eu="shift", refresh_accept="micro_bus", refresh_stall=3,
            refresh_stall_exec=4)
_F8 = {}


def _f8(cid):
    if not _F8:
        for r in _runs("F8"):
            n = normalize(r)
            _F8[n.run_id] = n
    return _F8[cid]


def _events14(cid, n=12, **kw):
    """(clock, kind) from the fill of a recorded F8 run (refresh on), the fill fetch
    dropped, simulated with the timer aligned on the run's first refresh, under the
    seventh fit + WP13 + WP14, and the silicon list the same way."""
    from validation.v35s.chains.sim.machine import refresh_anchor

    s = _f8(cid)
    cfg = (DEFAULT.replace(**FOURTH).replace(**FIFTH_IO).replace(**SIXTH).replace(**SEVENTH)
           .replace(**WP13).replace(**{**WP14, **kw}))
    m = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


def _refs(events):
    return [c for c, k in events if k == "refresh"]


class Refresh(unittest.TestCase):
    """WP14, the refresh controller (sim/refresh.py), each rule against its alternative on
    a named F8 run (RFM FCh), silicon clocks from t_fill quoted from chains-F8-w<N>. The
    first long shift of F8-push-empty-pO-w1: refreshes 1 16 31 48 63 80 96, the PUSH
    marker's write at 101 (78 with refresh off)."""

    SIL = [1, 16, 31, 48, 63, 80, 96]

    def test_timer_runs_from_the_previous_request(self):
        # refresh_timer=grid: 15/17 alternating around 16.0; counted from the previous
        # cycle's start every gap is >= 16 (1 18 35 ...), from its end >= 20 (1 22 43 ...)
        got, sil = _events14("F8-push-empty-pO-w1", 8)
        self.assertEqual(_refs(sil), self.SIL)
        self.assertEqual(got, sil)
        self.assertEqual(_refs(_events14("F8-push-empty-pO-w1", 8, refresh_timer="start")[0])[:3],
                         [1, 18, 35])
        self.assertEqual(_refs(_events14("F8-push-empty-pO-w1", 8, refresh_timer="end")[0])[:3],
                         [1, 22, 43])

    def test_refresh_stalls_the_shift(self):
        # refresh_eu=shift: each refresh taken in the shift's count loop adds 3 clocks, one
        # in its exec clocks 4 (the alternation needs an even shift there): the PUSH write
        # at 101; without a stall it is at 78 (as with refresh off), stalling the loop only
        # at 93, the exec by 3 puts every later refresh a clock early (15 30 47 ...)
        got, _ = _events14("F8-push-empty-pO-w1", 8)
        self.assertEqual(got[7], (101, "stack_write"))
        self.assertEqual(_events14("F8-push-empty-pO-w1", 8, refresh_eu="none")[0][5],
                         (78, "stack_write"))
        self.assertEqual(_events14("F8-push-empty-pO-w1", 8, refresh_eu="loop")[0][6],
                         (93, "stack_write"))
        self.assertEqual(_refs(_events14("F8-push-empty-pO-w1", 8, refresh_stall_exec=3)[0]),
                         [1, 15, 30, 47, 62, 79, 95])
        # NOP trains are hardly stalled: F8-push-nop-k4-pO-w0, M0 101, M1 127 = 101 + 26
        # (25 with refresh off). Stalling only the shift the model writes M1 at 126 (a fetch
        # at 120 that silicon does not make, unresolved); stalling every clocks step
        # (refresh_eu=clocks) M1 comes after 129
        got, sil = _events14("F8-push-nop-k4-pO-w0", 13)
        self.assertEqual(sil[11], (127, "stack_write"))
        self.assertEqual(got[12], (126, "stack_write"))
        clocks = _events14("F8-push-nop-k4-pO-w0", 13, refresh_eu="clocks")[0]
        self.assertNotIn("stack_write", [k for c, k in clocks if 101 < c < 129])

    def test_loop_takes_a_request_on_its_iteration_boundaries(self):
        # refresh_accept: in the count loop a request is taken an even number of clocks
        # before the loop ends: 15 -> 16, 47 -> 48, 79 -> 80 (the 3-clock stall flips the
        # parity, so the next one is on time). Taken on any clock: 16 32 48 64; on the odd
        # clocks: 15 30 47 ...
        self.assertEqual(_refs(_events14("F8-push-empty-pO-w1", 8, refresh_accept="bus")[0]),
                         [1, 16, 32, 48, 64, 80, 96])
        self.assertEqual(_refs(_events14("F8-push-empty-pO-w1", 8,
                                         refresh_accept="loop_odd")[0])[:3], [1, 15, 30])

    def test_waiting_eu_takes_it_on_odd_clocks_unless_the_bus_unit_has_a_cycle(self):
        # F8-push-empty-pE-w0: the request at 87 comes as the PUSH starts (88): the refresh
        # goes at 89, write 94; taken at once (loop_even) it goes at 88. F8-push-empty-pE-w1:
        # the second PUSH's write is issuable at 111 with the request: the refresh first,
        # write 116 (micro_bus, micro_data); the odd-clock rule alone gives write 111.
        got, sil = _events14("F8-push-empty-pE-w0", 10)
        self.assertEqual(got, sil)
        self.assertEqual(sil[5:7], [(89, "refresh"), (94, "stack_write")])
        self.assertEqual(_events14("F8-push-empty-pE-w0", 10, refresh_accept="loop_even")[0][5],
                         (88, "refresh"))
        got, sil = _events14("F8-push-empty-pE-w1", 12)
        self.assertEqual(got, sil)
        self.assertEqual(sil[9:11], [(111, "refresh"), (116, "stack_write")])
        self.assertEqual(_events14("F8-push-empty-pE-w1", 12, refresh_accept="micro")[0][9],
                         (111, "stack_write"))
        # a fetch request: F8-push-nop-k4-pO-w0 X112 F117 under micro_bus; micro_data
        # agrees here (the fetch was raised before the refresh's clock) and loses elsewhere
        got, sil = _events14("F8-push-nop-k4-pO-w0", 11)
        self.assertEqual(got, sil)

    def test_refresh_beats_a_pending_fetch_and_data_cycle(self):
        # refresh_fetch=refresh: F8-push-nop-k4-pO-w0 X112 F117 (fetch first: F112 X115);
        # refresh_data=refresh: F8-push-empty-pE-w0 X103 W108 (data first: W103 X106)
        self.assertEqual(_events14("F8-push-nop-k4-pO-w0", 11)[1][9:11],
                         [(112, "refresh"), (117, "fetch")])
        self.assertEqual(_events14("F8-push-nop-k4-pO-w0", 11, refresh_fetch="fetch")[0][9:11],
                         [(112, "fetch"), (115, "refresh")])
        got, sil = _events14("F8-push-empty-pE-w0", 10)
        self.assertEqual(sil[8:10], [(103, "refresh"), (108, "stack_write")])
        self.assertEqual(_events14("F8-push-empty-pE-w0", 10, refresh_data="data")[0][8:10],
                         [(103, "stack_write"), (106, "refresh")])

    def test_back_to_back_and_dropped_requests(self):
        # refresh_b2b: no F8 run tells the two apart before its first difference (the same
        # events on F8-push-empty-pO-w1). refresh_drop: silicon F8-push-empty-pO-w1 has no
        # fetch between the refresh at 128 and 217 (the fetch raised as the shift starts on
        # 128 is lost); kept, the model fetches at 133; dropped, it reproduces that gap
        sil = _events14("F8-push-empty-pO-w1", 20)[1]
        self.assertEqual(sil[12:14], [(128, "refresh"), (143, "refresh")])
        self.assertEqual(_events14("F8-push-empty-pO-w1", 14)[0],
                         _events14("F8-push-empty-pO-w1", 14, refresh_b2b=True)[0])
        self.assertEqual(_events14("F8-push-empty-pO-w1", 14)[0][13], (133, "fetch"))
        dropped = _events14("F8-push-empty-pO-w1", 20, refresh_drop=True)[0]
        self.assertNotIn("fetch", [k for c, k in dropped if 128 < c < 200])

    def test_refresh_rows_and_the_anchor(self):
        # the row address advances by 200h per refresh, numbered from the anchor's; the
        # timer phase sets the first refresh at or after t_fill, nothing else: with the
        # alternatives that do not stall the EU no F8 run gets its first long shift
        from validation.v35s.chains.sim.machine import refresh_anchor

        s = _f8("F8-push-empty-pO-w1")
        cfg = (DEFAULT.replace(**FOURTH).replace(**FIFTH_IO).replace(**SIXTH)
               .replace(**SEVENTH).replace(**WP13).replace(**WP14))
        m = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
        a, b = aligned(s), aligned(m)
        self.assertEqual([e[2] for e in a if e[1] == "refresh"][:7],
                         [e[2] for e in b if e[1] == "refresh"][:7])
        for cid in ("F8-push-empty-pE-w0", "F8-push-empty-pO-w0", "F8-push-empty-pE-w2"):
            got, sil = _events14(cid, 9, refresh_eu="none", refresh_accept="bus")
            self.assertNotEqual(got, sil, cid)

    def test_refresh_off_reads_no_refresh_field(self):
        # every family but F8 has RFM ECh: the refresh machine does not exist and no
        # refresh option is read (the fit cache keys on the fields a run reads)
        from validation.v35s.chains import fit

        chain = _chain("F5", "F5-push-st_bw-k1-pE-w0")
        rc = fit.recording(DEFAULT.replace(**WP14))
        simulate_normalized(chain, rc)
        self.assertFalse([n for n in rc._reads if n.startswith("refresh")])


# WP17 (F13, the refresh machine's EU side) on the ninth fit (the WP16 configuration, saved
# as fit-wp16.json before WP17 changed fit.json).
WP17 = dict(refresh_eu="hold", refresh_accept="boundary_bus", refresh_exec="every2",
            refresh_loop_entry="open", refresh_clk_start="after_wait", refresh_hold_take="port",
            refresh_after="fetch_next", refresh_mul="loop_odd", refresh_align="phase_eu")
_NINTH = []


def _ninth():
    import json
    from pathlib import Path
    if not _NINTH:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp16.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _NINTH.append(Config.from_json(json.loads(path.read_text())))
    return _NINTH[0]


_RUNS17 = {}


def _events17(cid, n=12, **kw):
    """(clock, kind) from the fill of a recorded F8 or F13 run (refresh on), the fill fetch
    dropped, under the ninth fit + WP17 (+ kw), and the silicon list the same way."""
    from validation.v35s.chains.sim.machine import refresh_anchor

    family = cid.split("-")[0]
    if family not in _RUNS17:
        _RUNS17[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS17[family][cid])
    cfg = _ninth().replace(**{**WP17, **kw})
    m = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class RefreshHold(unittest.TestCase):
    """WP17, the EU side of the refresh machine, each rule against its alternative on a
    named F13 or F8 run, silicon clocks from t_fill quoted from chains-F13-w<N> and
    chains-F8-w<N>."""

    def test_rfm_fields(self):
        # RFM.RFW sets the refresh cycle to 3 + RFW clocks (RFW 3 as 2), RFM.RFT the
        # interval to 16 << RFT; RFEN (bit 4) turns it on
        from validation.v35s.chains.types import refresh_length, refresh_on, refresh_rft
        self.assertEqual([refresh_length(r) for r in (0xF0, 0xF4, 0xF8, 0xFC)], [3, 4, 5, 5])
        self.assertEqual([refresh_rft(r) for r in (0xFC, 0xFD, 0xFE, 0xFF)], [0, 1, 2, 3])
        self.assertEqual([refresh_on(r) for r in (0xEC, 0xFC, 0xFF, 0xF0)],
                         [False, True, True, True])
        s = normalize(next(r for r in _runs("F13") if r["chain"]["id"] == "F13-r-rfw-0-pE-w2"))
        self.assertEqual({e.length for e in s.events if e.kind == "refresh"}, {3})
        # RFT 2 (64 clocks): the empty frame exact, refreshes 19 86 147
        got, sil = _events17("F13-r-rfm-f2-pE-w1", 8)
        self.assertEqual(got, sil)
        self.assertEqual([c for c, k in sil if k == "refresh"], [19, 86, 147])

    def test_refresh_holds_the_eu_at_its_next_boundary(self):
        # the first LS with a 4-clock refresh (RFW 1): each refresh costs the count loop 2
        # (held at the next iteration start until the cycle ends), the gaps stay 16, the
        # restart fetch at 87; the WP14 rule (3 per refresh, 4 in the exec) gives 32 64 ..
        # and 93
        got, sil = _events17("F13-r-rfw-1-pO-w1", 8)
        self.assertEqual(got, sil)
        self.assertEqual(sil[5:7], [(80, "refresh"), (87, "fetch")])
        old = _events17("F13-r-rfw-1-pO-w1", 8, refresh_eu="shift", refresh_accept="micro_bus")[0]
        self.assertEqual([c for c, k in old if k == "refresh"][2:5], [32, 49, 64])
        self.assertEqual(old[6], (93, "fetch"))
        # 5-clock refresh: 3 per refresh, restart 93 (shift: 94)
        got, sil = _events17("F13-r-rfm-f0-pO-w1", 8)
        self.assertEqual(got, sil)
        self.assertEqual(_events17("F13-r-rfm-f0-pO-w1", 8, refresh_eu="shift",
                                   refresh_accept="micro_bus")[0][6], (94, "fetch"))

    def test_shift_exit_and_exec_boundaries(self):
        # MOV CL,7 ; SHL AW,CL after the first LS, pE 2 waits: refresh 112 in the shift's
        # exec (2 clocks before its loop: costs 1), refresh 127 on the loop's last
        # iteration (costs 2), X's end fetch 137. The exit's boundary 1 or 3 clocks before
        # its end gives 136 / 135; an exit of 2 clocks moves the first LS's end to 94; no
        # boundary in the exec gives refresh 114 and the end fetch 140
        cid = "F13-s-shlcl7-pE-w2"
        got, sil = _events17(cid, 12)
        self.assertEqual(got, sil)
        self.assertEqual(sil[9:12], [(112, "refresh"), (127, "refresh"), (137, "fetch")])
        self.assertEqual(_events17(cid, 12, refresh_tail_bound=3)[0][11], (135, "fetch"))
        self.assertEqual(_events17(cid, 12, refresh_tail_bound=1)[0][11], (136, "fetch"))
        self.assertEqual(_events17(cid, 12, shift_tail=2)[0][6], (94, "fetch"))
        plain = _events17(cid, 12, refresh_exec="plain")[0]
        self.assertEqual((plain[9], plain[11]), ((114, "refresh"), (140, "fetch")))
        # one more count: the refresh at 127 is two iterations from the end and costs 3
        got, sil = _events17("F13-s-shlcl8-pE-w2", 12)
        self.assertEqual(got, sil)
        self.assertEqual(sil[11], (140, "fetch"))

    def test_loop_entry_takes_a_request(self):
        # the second LS of MOV CL,3 ; SHL AW,CL, pE 0 waits: its count loop starts at 135
        # and the request due then goes at once (closed: 137)
        got, sil = _events17("F13-s-shlcl3-pE-w0", 13)
        self.assertEqual(got, sil)
        self.assertEqual(sil[12], (135, "refresh"))
        self.assertEqual(_events17("F13-s-shlcl3-pE-w0", 13, refresh_loop_entry="closed")[0][12],
                         (137, "refresh"))

    def test_waiting_push_takes_it_in_its_fetch_free_window(self):
        # F8-push-empty-pE-w0: PUSH starts at 85, the request at 87 waits for start + 4
        # (the first of its setup's 3 fetch-free clocks): refresh 89, write 94; taken on
        # any waiting clock (boundary) the write is at 100. pE-w2: refresh 96, write 101
        # (boundary_micro, odd clocks: 95, 100)
        got, sil = _events17("F8-push-empty-pE-w0", 10)
        self.assertEqual(got, sil)
        self.assertEqual(sil[5:7], [(89, "refresh"), (94, "stack_write")])
        self.assertEqual(_events17("F8-push-empty-pE-w0", 10, refresh_accept="boundary")[0][6],
                         (100, "stack_write"))
        got, sil = _events17("F8-push-empty-pE-w2", 10)
        self.assertEqual(got, sil)
        self.assertEqual(_events17("F8-push-empty-pE-w2", 10,
                                   refresh_accept="boundary_micro")[0][6:8],
                         [(95, "refresh"), (100, "stack_write")])

    def test_out_after_the_first_ls(self):
        # F8-out-empty-pE-w0: refresh 87 on the OUT's pre clocks, its port take (which posts
        # the I/O) held to the refresh's end: fetch 92, I/O 101 (takes free: 95, 108)
        got, sil = _events17("F8-out-empty-pE-w0", 8)
        self.assertEqual(got, sil)
        self.assertEqual(sil[5:8], [(87, "refresh"), (92, "fetch"), (101, "io_write")])
        self.assertEqual(_events17("F8-out-empty-pE-w0", 8, refresh_hold_take="free")[0][6:8],
                         [(95, "fetch"), (103, "refresh")])
        # an operand take is no hold point: END's MOV DW,imm16 under the refresh at 239 in
        # F13-s-shlcl8-pE-w2 fetches at 244 (hold: 245)
        got, sil = _events17("F13-s-shlcl8-pE-w2", 21)
        self.assertEqual(sil[19:21], [(239, "refresh"), (244, "fetch")])
        self.assertEqual(got, sil)
        self.assertEqual(_events17("F13-s-shlcl8-pE-w2", 21, refresh_hold_take="hold")[0][20],
                         (245, "fetch"))
        # F8-out-empty-pO-w0: the 2 clocks after the port take take no refresh: the request
        # at 96 goes at 98 (a boundary at every clocks step's start: 96)
        got, sil = _events17("F8-out-empty-pO-w0", 7)
        self.assertEqual(got, sil)
        self.assertEqual(sil[6], (98, "refresh"))
        self.assertEqual(_events17("F8-out-empty-pO-w0", 7, refresh_clk_start="any")[0][6],
                         (96, "refresh"))
        # F8-out-empty-pE-w2: the fetch the refresh at 95 beat goes at 100, ahead of the
        # OUT's posted I/O (arbitrate: 102)
        got, sil = _events17("F8-out-empty-pE-w2", 8)
        self.assertEqual(got, sil)
        self.assertEqual(sil[6:8], [(95, "refresh"), (100, "fetch")])
        self.assertEqual(_events17("F8-out-empty-pE-w2", 8, refresh_after="arbitrate")[0][7],
                         (102, "fetch"))

    def test_mulu_is_a_count_loop(self):
        # MULU DW twice after a PUSH, pO 1 wait: refreshes 111 128 inside the multiplies
        # (boundaries an odd number of clocks before the exec ends); even: 112 127; no
        # boundary in its exec: the requests pile up to 140 145 150
        cid = "F13-u-push-mulu-k2-pO-w1"
        got, sil = _events17(cid, 11)
        self.assertEqual(got, sil)
        self.assertEqual(sil[9:11], [(111, "refresh"), (128, "refresh")])
        self.assertEqual(_events17(cid, 11, refresh_mul="loop")[0][9:11],
                         [(112, "refresh"), (127, "refresh")])
        self.assertEqual(_events17(cid, 11, refresh_mul="plain")[0][9:11],
                         [(140, "refresh"), (145, "refresh")])

    def test_first_ls_alignment(self):
        # the first LS's end depends on the prelude's refreshes, which the model does not
        # run: F13-r-rfm-f0-pE-w0 refresh 88 and restart 93 need the first LS's exec 2
        # clocks shorter (refresh_align=phase_eu); with the phase alone 87, 92
        got, sil = _events17("F13-r-rfm-f0-pE-w0", 8)
        self.assertEqual(got, sil)
        self.assertEqual(sil[5:7], [(88, "refresh"), (93, "fetch")])
        self.assertEqual(_events17("F13-r-rfm-f0-pE-w0", 8, refresh_align="phase")[0][5:7],
                         [(87, "refresh"), (92, "fetch")])

    def test_hold_reads_nothing_with_refresh_off(self):
        # the WP17 fields are read only by a chain with refresh on
        from validation.v35s.chains import fit

        chain = _chain("F5", "F5-push-st_bw-k1-pE-w0")
        rc = fit.recording(DEFAULT.replace(**WP14).replace(**WP17))
        simulate_normalized(chain, rc)
        self.assertFalse([n for n in rc._reads if n.startswith("refresh") or n == "shift_tail"])


class StorageUnits(unittest.TestCase):
    """Queue-level behaviour of each storage option."""

    def _q(self, **kw):
        m = Machine(_chain("F0", "F0-ls-pE-w0"), DEFAULT.replace(**kw))
        return m.queue, m.decoder

    def test_byte_latch_counts(self):
        for latch, later in (("byte", 1), ("byte_d", 0)):
            q, d = self._q(word_latch=latch)
            q.arrive(0x10048, 0, 0)
            q.check(0)
            q.take(1)                            # the decoder reads on clock 1
            q.commit(1)
            q.arrive(0x1004A, 0, 1)              # ... as a word lands: its second byte waits
            self.assertEqual(q.latched, 1)
            self.assertEqual(q.room(1), QUEUE_BYTES - 2)   # 3 bytes, one uncounted
            q.check(1)
            self.assertEqual(q.latched, 1)                 # read on 1: still latched
            q.read_t = q.removed_t = 1
            self.assertEqual(q.room(2), QUEUE_BYTES - 3 + later)
            q.check(2)                                     # no read on 2: it goes in
            self.assertEqual((q.latched, q.stored()), (0, 3))

    def test_latch_read_commit_and_ir(self):
        q, _ = self._q(word_latch="byte", latch_read="commit")
        q.arrive(0x10048, 0, 0)
        q.check(0)
        q.read_t, q.removed_t, q.ir_t = 1, None, None
        q.arrive(0x1004A, 0, 1)
        self.assertFalse(q._port_busy(1))
        self.assertEqual(q._latched_now(1), 0)            # a read that did not commit
        q.removed_t = 1
        self.assertTrue(q._port_busy(1))
        q2, _ = self._q(word_latch="byte", latch_read="ir")
        q2.removed_t = 1
        self.assertFalse(q2._port_busy(1))
        q2.ir_t = 1
        self.assertTrue(q2._port_busy(1))

    def test_port_and_uncounted_latch_the_word(self):
        for latch in ("port", "uncounted", "counted"):
            q, _ = self._q(word_latch=latch)
            q.read_t = q.removed_t = 1
            q.arrive(0x10048, 0, 1)
            self.assertEqual(q.latched, 2, latch)
            self.assertEqual(q.room(1), QUEUE_BYTES - (2 if latch == "counted" else 0), latch)

    def test_latch_full_raises(self):
        q, _ = self._q(word_latch="byte")
        for k in range(3):
            q.arrive(0x10048 + 2 * k, 0, 0)
            q.check(0)
        q.take(1)
        q.commit(1)
        q.arrive(0x1004E, 0, 1)
        q.check(1)                               # 7 bytes: one stays latched
        self.assertEqual((q.stored(), q.latched), (6, 1))
        with self.assertRaises(QueueOverflow):
            q.arrive(0x10050, 0, 2)              # a word into a full latch

    def test_latch_hold_blocks_while_stuck(self):
        q, _ = self._q(word_latch="byte", latch_hold=True)
        for k in range(3):
            q.arrive(0x10048 + 2 * k, 0, 0)
            q.check(0)
        q.take(1)
        q.commit(1)
        q.arrive(0x1004E, 0, 1)
        self.assertFalse(q.latch_blocks(1))      # its own delivery clock never blocks
        q.check(1)
        self.assertTrue(q.latch_blocks(2))       # queue full: stuck
        q.take(3)
        q.commit(3)
        self.assertTrue(q.latch_blocks(3))       # room now, but the decoder holds the port
        self.assertFalse(q.latch_blocks(4))      # the byte goes in on 4

    def test_room_ir_idle(self):
        q, d = self._q(room_ir="idle")
        q.arrive(0x10048, 0, 0)
        d.need = 0
        self.assertEqual(q.room(5), QUEUE_BYTES + 1 - 2)
        d.need = 1                               # mid-take: the IR is not room
        self.assertEqual(q.room(5), QUEUE_BYTES - 2)
        q2, d2 = self._q(room_ir="arrival_idle")
        q2.arrive(0x10048, 0, 5)
        d2.need = 1
        self.assertEqual(q2.room(5), QUEUE_BYTES + 1 - 2)   # delivery clock
        self.assertEqual(q2.room(6), QUEUE_BYTES - 2)

    def test_request_sample_before_take(self):
        q, d = self._q(request_sample="before_take")
        q.arrive(0x10048, 0, 0)
        q.begin_clock(1)
        q.take(1)
        q.commit(1)
        self.assertEqual(q.room(1), QUEUE_BYTES - 2)     # as the clock began
        self.assertEqual(q.room(2), QUEUE_BYTES - 1)

    def test_request_eval_on_take(self):
        q, _ = self._q(request_eval="on_take")
        self.assertTrue(q._evaluates(0))
        q.arrived_t = 3
        self.assertFalse(q._evaluates(3))        # a delivery alone does not re-evaluate
        q.removed_t = 4
        self.assertTrue(q._evaluates(4))
        q2, _ = self._q(request_eval="on_change")
        q2.arrived_t = 3
        self.assertTrue(q2._evaluates(3))

    def test_modrm_commit_byte(self):
        # MOV AW,[BW+d8] (8B 47 10): the ModR/M byte leaves the occupancy when taken.
        for mode, after_first in (("step", 3), ("byte", 2)):
            q, d = self._q(modrm_commit=mode)
            q.arrive(0x10048, 0, 0)
            q.arrive(0x1004A, 0, 0)
            d.start(3, 0, 0, modrm=True)
            d.take(1, 2)                         # first operand byte: the ModR/M
            self.assertEqual(q.occupancy(), 4 - 1 + (after_first - 2), mode)
            d.take(2, 1)
            d.commit(2)
            self.assertEqual(q.occupancy(), 2, mode)

    def test_ir_port(self):
        for port, loads in ((False, True), (True, False)):
            q, d = self._q(ir_port=port)
            q.arrive(0x10048, 0, 0)
            q.arrive(0x1004A, 0, 0)
            d.start(2, 0, 0)
            d.take(1, 1)                         # the operand byte, on clock 1
            d.commit(1)
            d.load_ir(1)
            self.assertEqual(d.ir is not None, loads, port)
            d.load_ir(2)
            self.assertIsNotNone(d.ir)

    def test_quiescent_start(self):
        # The EU holds the first LS until no word lands or waits in the latch, so a
        # latch never changes the fill: F0 stays exact under every latch.
        for latch in OPTIONS["word_latch"]:
            if latch == "uncounted":
                continue                         # never re-requests: refuted on F0
            cfg = DEFAULT.replace(word_latch=latch, latch_read="commit")
            with self.subTest(latch=latch):
                self.assertEqual(_first_fetch_after_fill(cfg), 76)


if __name__ == "__main__":
    unittest.main()


# WP19 (F14): the TEST/XCH format properties, the group memory forms and the OUT after a
# register form, on top of the ninth fit (fit-wp18.json, the ninth fit with refresh).
WP19 = dict(grp_ops="fixed", dest_route="d0ro_latch", wlatch_ir=True, wlatch_mul="none",
            io_ir_hold=True, shift_cl_mem="count",
            **{"load_alu.grp": 4, "load_alu.grp_free": 3, "load_alu.dclk": 2, "rmw.dclk": 2,
               "rmw.grpcl": 3, "mul.grp": 4, "mul.mexec": 29, "mul.mwb": 2, "div.grp": 4,
               "div.grp_free": 3, "div.pre": 0, "div.mexec": 37, "div.mwb": 2})
_NINTH_R = []
_RUNS19 = {}


def _events19(cid, n=6, **kw):
    """(model, silicon) (clock, kind) lists from the fill, the fill fetch dropped, under the
    ninth fit (fit-wp18.json) + WP19 (+ kw)."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _NINTH_R:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp18.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _NINTH_R.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS19:
        _RUNS19[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS19[family][cid])
    cfg = _NINTH_R[0].replace(**{**WP19, **kw})
    m = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class FormatProperties(unittest.TestCase):
    """WP19, the F14 rules, each against the alternative it replaced; silicon clocks from
    the fill quoted from the corpus (chains-F14-w<N>, chains-F3-w<N>, chains-F12-w<N>)."""

    def test_decode_f14_forms(self):
        regs = dict(FORMS_REGS, CW=31)
        for name, cls, length in (("test_m_imm", "load_alu", 4), ("divu_m", "div", 2),
                                  ("shl_m_cl", "rmw", 2), ("cmp_m_aw", "load_alu", 2),
                                  ("test_m_al", "load_alu", 2), ("xch_m_al", "rmw", 2),
                                  ("add_m_al", "rmw", 2), ("mulu_aw", "mul", 2),
                                  ("test_dir_aw", "load_alu", 4)):
            op = decode(FORMS[name].code, 0, regs)
            self.assertEqual((op.cls, op.length), (cls, length), name)
            self.assertEqual(op.width, FORMS[name].width or 2, name)
        self.assertTrue(decode(FORMS["test_m_imm"].code, 0, regs).nowrite)
        self.assertEqual(decode(FORMS["shl_m_cl"].code, 0, regs).count, 31)
        self.assertEqual([decode(FORMS[n].code, 0, regs).dbit for n in
                          ("add_m_aw", "add_aw_m", "cmp_m_aw", "cmp_aw_m", "test_m_aw",
                           "xch_m_aw")], [0, 1, 0, 1, None, None])
        self.assertTrue(decode(FORMS["test_m_aw"].code, 0, regs).fixed_alu)
        self.assertTrue(decode(FORMS["xch_cw_m"].code, 0, regs).swap)

    def test_test_reads_as_a_group_form(self):
        # PUSH; TEST [BW],AW, even, 0 waits: F81 F84 R89 (with NOT [BW] and INC [BW]), the
        # PUSH write at 100; as a plain load_alu (grp_ops=modrm) R87 w98, CMP [BW],AW's clocks
        m, s = _events19("F14-t-push-test_bw_aw-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:5], [(89, "data_read"), (100, "stack_write")])
        m, _ = _events19("F14-t-push-test_bw_aw-pE-w0", 5, grp_ops="modrm")
        self.assertEqual(m[3:5], [(87, "data_read"), (98, "stack_write")])

    def test_direction_bit_against_the_write(self):
        # PUSH; CMP [BW],AW (39), even, 0 waits: R87, PUSH write 100 (CMP AW,[BW] (3B): 98);
        # PUSH; XCH [BW],AW: R87 W94 w103 (ADD [BW],AW: W92 w101); without the routing
        # clocks (dest_route=none) CMP writes at 98 and XCH at W92 w101
        for cid, n, tail, none in (
                ("F14-t-push-cmp_bw_aw-pE-w0", 5, [(87, "data_read"), (100, "stack_write")],
                 [(87, "data_read"), (98, "stack_write")]),
                ("F14-t-push-xch_bw_aw-pE-w0", 6, [(94, "data_write"), (103, "stack_write")],
                 [(92, "data_write"), (101, "stack_write")])):
            m, s = _events19(cid, n)
            self.assertEqual(m, s, cid)
            self.assertEqual(s[-2:], tail, cid)
            self.assertEqual(_events19(cid, n, dest_route="none")[0][-2:], none, cid)
        # OUT; CMP [BW],AW; OUT, even, 0 waits: R90, the closing OUT's port-take fetch 102,
        # I/O 109: the read datum enters the data latch after the routing clocks
        # (d0ro_latch); entering it on its delivery (d0ro_swap) gives 100/107
        m, s = _events19("F14-t-out-cmp_bw_aw-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[4:6], [(102, "fetch"), (109, "io_write")])
        m, _ = _events19("F14-t-out-cmp_bw_aw-pE-w0", 6, dest_route="d0ro_swap")
        self.assertEqual(m[4:6], [(100, "fetch"), (107, "io_write")])

    def test_out_in_the_ir_waits_for_the_register_latch(self):
        # OUT; MOV AW,DW; OUT, even, 0 waits: I/O 84, fetches 88 (the closing OUT's start)
        # and 91, I/O 98, as after a NOP. Without wlatch_ir MOV's take sync waits for the
        # fetch raised by its ModR/M take: 87, 90, I/O 100
        m, s = _events19("F14-o-out-movr-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(84, "io_write"), (88, "fetch"), (91, "fetch"),
                                 (98, "io_write")])
        m, _ = _events19("F14-o-out-movr-pE-w0", 5, wlatch_ir=False)
        self.assertEqual(m[2:], [(87, "fetch"), (90, "fetch"), (100, "io_write")])
        # OUT; MULU DW; OUT, even, 0 waits: fetches 87 and 124, I/O 131; with MULU's ModR/M
        # in the latch (wlatch_mul=take) the sync lapses and the multiply ends 5 early
        m, s = _events19("F3-out-mulu_dw-k1-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(124, "fetch"), (131, "io_write")])
        m, _ = _events19("F3-out-mulu_dw-k1-pE-w0", 5, wlatch_mul="take")
        self.assertEqual(m[3:], [(119, "fetch"), (126, "io_write")])

    def test_ir_load_on_the_io_clock_waits_for_the_next_start(self):
        # OUT; NOP; MOV AW,imm16; OUT, even, 0 waits: NOP starts on the I/O clock 84 and the
        # IR loads MOV there; fetches 88 (MOV's start) 92 99, I/O 106; without the hold the
        # request is raised by MOV's immediate take: 92 96 99
        m, s = _events19("F12-a-out-n1-imm-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[2:4], [(88, "fetch"), (92, "fetch")])
        m, _ = _events19("F12-a-out-n1-imm-pE-w0", 6, io_ir_hold=False)
        self.assertEqual(m[2:4], [(92, "fetch"), (96, "fetch")])

    def test_shift_by_cl_on_memory(self):
        # PUSH; SHL [BW],CL (CL = 31), even, 0 waits: R93 W164 (SHL [BW],1: R89 W100);
        # shift_cl_mem=plain reads at 89
        m, s = _events19("F14-g-push-shl_bw_cl-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(93, "data_read"), (164, "data_write")])
        m, _ = _events19("F14-g-push-shl_bw_cl-pE-w0", 5, shift_cl_mem="plain")
        self.assertEqual(m[3:], [(89, "data_read"), (160, "data_write")])

    def test_memory_multiply(self):
        # PUSH; MULU [BW], odd, 0 waits: R89 at the group clock, the PUSH write 127; with the
        # register form's exec (31) and mul.grp 3: R88 w128. OUT; MULU [BW]; OUT, even:
        # R92, port-take fetch 129, I/O 136 (the result's write-back mwb 2; 0 gives 127/134)
        m, s = _events19("F14-g-push-mulu_bw-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(89, "data_read"), (127, "stack_write")])
        m, _ = _events19("F14-g-push-mulu_bw-pO-w0", 4, **{"mul.mexec": 31, "mul.grp": 3})
        self.assertEqual(m[2:], [(88, "data_read"), (128, "stack_write")])
        m, s = _events19("F14-g-out-mulu_bw-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[4:], [(129, "fetch"), (136, "io_write")])
        m, _ = _events19("F14-g-out-mulu_bw-pE-w0", 6, **{"mul.mwb": 0})
        self.assertEqual(m[4:], [(127, "fetch"), (134, "io_write")])
        # PUSH; DIVU [BW] (5678h:0000h / 9090h), even, 0 waits: R89, the PUSH write 135
        m, s = _events19("F14-g-push-divu_bw-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(89, "data_read"), (135, "stack_write")])

    def test_wp19_defaults_are_the_old_model(self):
        for name in ("grp_ops", "dest_route", "wlatch_ir", "wlatch_mul", "io_ir_hold",
                     "shift_cl_mem"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


# WP20 (F15): POP and PUSH r/m, the TEST immediate and direct forms, the imm8 group forms,
# the start and take sync on an OUT's issue clock, on top of the tenth fit (fit-wp19.json).
WP20 = dict(pop_mem_order="stack_post", push_mem_write="at_data", grp_fixed="test",
            fixed_lookup="decoder_nowait", imm8_grp="own", io_busy_start="issue", sync_io="latch",
            **{"pop_mem.rsetup": 7, "pop_mem.rfree": 3, "pop_mem.setup": 4, "pop_mem.grp": 0,
               "pop_mem.pre": 2, "pop_mem.post": 0, "load_alu.fgrp": 2,
               "load_alu.fgrp_free": 2, "load_alu.fdisp": 5, "rmw_imm.grp1": 2,
               "reg.nx": 2})
_TENTH = []
_RUNS20 = {}


def _events20(cid, n=6, **kw):
    """(model, silicon) (clock, kind) lists from the fill, the fill fetch dropped, under the
    tenth fit (fit-wp19.json) + WP20 (+ kw)."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _TENTH:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp19.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _TENTH.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS20:
        _RUNS20[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS20[family][cid])
    cfg = _TENTH[0].replace(**{**WP20, **kw})
    m = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class StackFirstAndLookups(unittest.TestCase):
    """WP20, the F15 rules, each against the alternative it replaced; silicon clocks from
    the fill quoted from the corpus (chains-F15-w<N>, chains-F3-w<N>)."""

    def test_decode_f15_forms(self):
        regs = dict(FORMS_REGS, IX=0x0900)
        for name, cls, length, imm in (
                ("and_m_aw", "rmw", 2, 0), ("and_aw_m", "load_alu", 2, 0),
                ("or_m_aw", "rmw", 2, 0), ("xor_aw_m", "load_alu", 2, 0),
                ("sub_m_aw", "rmw", 2, 0), ("and_m_imm", "rmw_imm", 4, 2),
                ("add_m_imm8", "rmw_imm", 3, 1), ("and_m_imm8", "rmw_imm", 3, 1),
                ("cmp_dir_aw", "load_alu", 4, 0), ("and_dir_aw", "rmw", 4, 0),
                ("test_al_imm", "imm", 2, 1), ("test_aw_imm", "imm", 3, 2),
                ("pop_m_dir", "pop_mem", 4, 0), ("pop_m_d8", "pop_mem", 3, 0),
                ("pop_m_ix", "pop_mem", 2, 0), ("pop_cw", "pop", 1, 0)):
            op = decode(FORMS[name].code, 0, regs)
            self.assertEqual((op.cls, op.length, op.imm_bytes), (cls, length, imm), name)
        self.assertEqual(decode(FORMS["pop_m_ix"].code, 0, regs).ea, 0x0900)
        self.assertFalse(decode(FORMS["and_m_aw"].code, 0, regs).fixed_alu)
        self.assertTrue(decode(FORMS["test_m_imm"].code, 0, regs).fixed_alu)

    def test_pop_reads_the_stack_first(self):
        # PUSH; POP [0C00h], odd, 0 waits: F81 r87 F93 W96 w105, the stack read before the
        # displacement's fetch; ModR/M, displacement and EA first: F83 F86 r89 W97 w106
        m, s = _events20("F15-p-push-pop_dir-pO-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(81, "fetch"), (87, "stack_read"), (93, "fetch"),
                                 (96, "data_write"), (105, "stack_write")])
        m, _ = _events20("F15-p-push-pop_dir-pO-w0", 6, pop_mem_order="modrm_first")
        self.assertEqual(m[1:4], [(83, "fetch"), (86, "fetch"), (89, "stack_read")])
        # OUT; POP [BW], odd, 0 waits: I/O 85, r91 W99 F103: the memory write is posted on
        # the stack data and holds the fetch; posted after the EA (stack_lead): r91 F94 W104
        m, s = _events20("F15-p-out-pop_bw-pO-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(91, "stack_read"), (99, "data_write"), (103, "fetch")])
        m, _ = _events20("F15-p-out-pop_bw-pO-w0", 5, pop_mem_order="stack_lead")
        self.assertEqual(m[2:], [(91, "stack_read"), (94, "fetch"), (104, "data_write")])

    def test_push_posts_its_stack_write_on_the_data(self):
        # OUT; PUSH [BW], odd, 0 waits: I/O 85, R93 w102 F106; posted after its exec clocks
        # the write lets a fetch go first: R93 F96 w102
        m, s = _events20("F15-p-out-push_bw-pO-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[2:5], [(93, "data_read"), (102, "stack_write"), (106, "fetch")])
        m, _ = _events20("F15-p-out-push_bw-pO-w0", 6, push_mem_write="after_exec")
        self.assertEqual(m[2:5], [(93, "data_read"), (96, "fetch"), (102, "stack_write")])

    def test_test_immediate_adds_the_group_decode(self):
        # PUSH; TEST [BW],imm16 (F7 /0), even, 0 waits: F81 F84 R91 F96, 2 after TEST
        # [BW],AW's R89; with the group's setup alone (CMP [BW],imm16's): R88 F93
        m, s = _events20("F15-a-push-test_bw_imm-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(91, "data_read"), (96, "fetch")])
        m, _ = _events20("F15-a-push-test_bw_imm-pE-w0", 5, grp_fixed="one")
        self.assertEqual(m[3:], [(88, "data_read"), (93, "fetch")])

    def test_test_lookup_holds_the_displacement(self):
        # PUSH; TEST [0C00h],AW, even, 0 waits: F81 F87 R90 (AND/CMP [0C00h],AW F81 F84 R87);
        # the lookup as the read's setup only: F81 F84 R90
        m, s = _events20("F15-a-push-test_dir_aw-pO-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:4], [(81, "fetch"), (87, "fetch"), (90, "data_read")])
        m, _ = _events20("F15-a-push-test_dir_aw-pO-w0", 5, fixed_lookup="setup")
        self.assertEqual(m[1:4], [(81, "fetch"), (84, "fetch"), (90, "data_read")])
        # at 2 waits the lookup's clocks skip the fetch's wait states: F83 F91 R96; counted
        # on every clock (decoder, fdisp 4): F83 F89 R94
        m, s = _events20("F15-a-push-test_dir_aw-pO-w2", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:4], [(83, "fetch"), (91, "fetch"), (96, "data_read")])
        m, _ = _events20("F15-a-push-test_dir_aw-pO-w2", 5, fixed_lookup="decoder",
                         **{"load_alu.fdisp": 4})
        self.assertEqual(m[1:4], [(83, "fetch"), (89, "fetch"), (94, "data_read")])

    def test_one_byte_immediate_group_setup(self):
        # PUSH; AND [BW],imm8 (83 /4), even, 0 waits: F81 R87 W92 F95; with 81 /4's setup
        # R88 W93 F96
        m, s = _events20("F15-a-push-and_bw_imm8-pO-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(87, "data_read"), (92, "data_write"), (95, "fetch")])
        m, _ = _events20("F15-a-push-and_bw_imm8-pO-w0", 5, imm8_grp="same")
        self.assertEqual(m[2:], [(88, "data_read"), (93, "data_write"), (96, "fetch")])

    def test_take_on_the_io_issue_clock(self):
        # OUT; MOV AW,DW; MOV AW,[BW], even, 0 waits: I/O 84, F87 F90 R93; MOV waiting for
        # the fetch its take raised under the I/O: R95
        m, s = _events20("F15-o-out-movr_ld-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[1:5], [(84, "io_write"), (87, "fetch"), (90, "fetch"),
                                  (93, "data_read")])
        m, _ = _events20("F15-o-out-movr_ld-pE-w0", 6, sync_io="none")
        self.assertEqual(m[4], (95, "data_read"))
        # OUT; MULU DW; OUT, even, 0 waits (MULU's ModR/M does not enter the latch): it
        # still waits, fetches 87 and 124, I/O 131
        m, s = _events20("F3-out-mulu_dw-k1-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(124, "fetch"), (131, "io_write")])

    def test_register_form_after_the_io_issue_clock(self):
        # OUT; ES: MOV AW,imm16; OUT, even, 0 waits: I/O 84-86, the prefix at 84, MOV at 87:
        # F87 F91 F98 I105; MOV starting at 86 under the I/O: F87 F90 F97 I104
        m, s = _events20("F3-out-pfx_mov_aw_imm-k1-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(87, "fetch"), (91, "fetch"), (98, "fetch"),
                                 (105, "io_write")])
        m, _ = _events20("F3-out-pfx_mov_aw_imm-k1-pE-w0", 6, io_busy_start="any")
        self.assertEqual(m[2:], [(87, "fetch"), (90, "fetch"), (97, "fetch"),
                                 (104, "io_write")])

    def test_wp20_defaults_are_the_old_model(self):
        for name in ("pop_mem_order", "pop_read_hold", "push_mem_write", "grp_fixed",
                     "fixed_lookup", "imm8_grp", "sync_io", "io_busy_start"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


WP21 = dict(count_latch=True, abort_unit="loop", free_run="run", io_exec="after_io",
            **{"mul.smexec": 49, "mul.bmexec": 21, "div.smexec": 58, "div.exec": 39,
               # (WP22) mtail is counted from the end the exec would have had from the early
               # read (2), the twelfth fit's 3 from the moved end: the same clock
               "mul.mtail": 2, "div.mtail": 2})
_ELEVENTH = []
_RUNS21 = {}


def _events21(cid, n=6, **kw):
    """(model, silicon) (clock, kind) lists from the fill, the fill fetch dropped, under the
    eleventh fit (fit-wp20.json) + WP21 (+ kw)."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _ELEVENTH:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp20.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _ELEVENTH.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS21:
        _RUNS21[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS21[family][cid])
    cfg = _ELEVENTH[0].replace(**{**WP21, **kw})
    m = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class UnitFormsAndFetchRuns(unittest.TestCase):
    """WP21, the F16 rules, each against the alternative it replaced; silicon clocks from
    the fill quoted from the corpus (chains-F16-w<N>)."""

    def test_decode_f16_forms(self):
        regs = dict(FORMS_REGS)
        for name, cls, width, signed in (
                ("rol_m1", "rmw", 2, False), ("sar_m1", "rmw", 2, False),
                ("shlb_m1", "rmw", 1, False), ("mul_m", "mul", 2, True),
                ("div_m", "div", 2, True), ("mulub_m", "mul", 1, False),
                ("dec_m", "rmw", 2, False), ("divu_ix", "div", 2, False)):
            op = decode(FORMS[name].code, 0, regs)
            self.assertEqual((op.cls, op.width, op.signed), (cls, width, signed), name)
        self.assertTrue(decode(FORMS["ror_m1"].code, 0, regs).shift)
        self.assertEqual(decode(FORMS["shl_aw_cl"].code, 0, dict(regs, CW=4)).count, 4)

    def test_count_byte_latched_on_its_delivery(self):
        # NOP ; SHL AW,4 (C1), even, 1 wait: the count byte taken at 80 on fetch 76's
        # delivery: F72 F76 F99 F103, no fetch during the shift; as any take: F80 F103
        m, s = _events21("F16-s-none-n1-shli4-pE-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s, [(72, "fetch"), (76, "fetch"), (99, "fetch"), (103, "fetch")])
        m, _ = _events21("F16-s-none-n1-shli4-pE-w1", 4, count_latch=False)
        self.assertEqual(m[2:], [(80, "fetch"), (103, "fetch")])
        # NOP NOP ; SHL AW,4, even, 1 wait: the ModR/M taken at 80 on a delivery with the
        # queue full, the count byte at 83: no fetch until the shift's last clock, F97 F104
        # (as any take: F83)
        m, s = _events21("F16-s-none-n2-shli4-pE-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(97, "fetch"), (104, "fetch")])
        m, _ = _events21("F16-s-none-n2-shli4-pE-w1", 4, count_latch=False)
        self.assertEqual(m[2], (83, "fetch"))
        # the count in CL (MOV CL,4 ; SHL AW,CL) fetches during the shift: F79 F83 F107
        m, s = _events21("F16-s-none-n1-shlcl4-pE-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(79, "fetch"), (83, "fetch"), (107, "fetch")])

    def test_unit_form_after_an_aborted_start(self):
        # PUSH; INC [BW]; ROL [BW],1, even, 0 waits: ROL starts on the aborted cycle at 97,
        # R104 W115 (none: R105 W116); NOT [BW] in its place reads at 105 either way, and
        # with every group form early (all) 1 too soon
        m, s = _events21("F16-r-push-rol-inc_x-pE-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[5:], [(104, "data_read"), (115, "data_write")])
        m, _ = _events21("F16-r-push-rol-inc_x-pE-w0", 7, abort_unit="none")
        self.assertEqual(m[5:], [(105, "data_read"), (116, "data_write")])
        m, s = _events21("F16-r-push-not-inc_x-pE-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[5:], [(105, "data_read"), (110, "data_write")])
        m, _ = _events21("F16-r-push-not-inc_x-pE-w0", 7, abort_unit="all")
        self.assertEqual(m[5:], [(104, "data_read"), (109, "data_write")])

    def test_multiply_holds_the_dropped_request(self):
        # PUSH; INC [BW]; MULU [BW], even, 0 waits: R104 and no fetch until 134, 3 clocks
        # before the multiply ends; raised again after the read (early): F107
        m, s = _events21("F16-r-push-mulu-inc_x-pE-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[5:], [(104, "data_read"), (134, "fetch")])
        m, _ = _events21("F16-r-push-mulu-inc_x-pE-w0", 7, abort_unit="early")
        self.assertEqual(m[6], (107, "fetch"))

    def test_shift_raises_the_dropped_request_on_its_last_iteration(self):
        # MOV CL,4 ; NOP ; SHL AW,CL, even, 0 waits: the shift starts on an aborted cycle at
        # 82; the dropped request goes as its last count iteration starts: F100 F106; raised
        # again only by the next take (early): F105 F108
        m, s = _events21("F16-s-none-cl4-n1-shlcl-pE-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(100, "fetch"), (106, "fetch")])
        m, _ = _events21("F16-s-none-cl4-n1-shlcl-pE-w0", 4, abort_unit="early")
        self.assertEqual(m[2:], [(105, "fetch"), (108, "fetch")])

    def test_fetch_run_into_a_free_setup(self):
        # PUSH; POP [BW], even, 1 wait: the word of the fetch at 82 lands at 86, on the stack
        # read's first fetch-free setup clock: F82 F86 r90 (none: F82 r88 W97 F101); at 0
        # waits the request comes at 84, before them, and is held: F81 r87
        m, s = _events21("F16-p-push-n0-pop_bw-pE-w1", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:4], [(82, "fetch"), (86, "fetch"), (90, "stack_read")])
        m, _ = _events21("F16-p-push-n0-pop_bw-pE-w1", 5, free_run="none")
        self.assertEqual(m[1:3], [(82, "fetch"), (88, "stack_read")])
        m, s = _events21("F16-p-push-n0-pop_bw-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:3], [(81, "fetch"), (87, "stack_read")])

    def test_register_form_exec_after_the_io_cycle(self):
        # OUT; SHL AW,1; OUT, even, 0 waits: SHL starts on the I/O's issue clock 84, its
        # exec after the cycle: F87 F99 I106 (any: F97 I104)
        m, s = _events21("F16-l-out-shl1-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(87, "fetch"), (99, "fetch"), (106, "io_write")])
        m, _ = _events21("F16-l-out-shl1-pE-w0", 5, io_exec="any")
        self.assertEqual(m[3:], [(97, "fetch"), (104, "io_write")])

    def test_signed_byte_and_register_divide_integers(self):
        # PUSH; X; PUSH, even, 0 waits, the read at 89: MUL [BW] (AW = 0 x 9090h) w147, 20
        # after MULU [BW]'s 127; MULU byte [BW] w119; DIV [BW] (DW = 0100h) w156; odd:
        # DIVU IX (IX = 9090h) w129, 8 after MULU AW's w121
        for cid, w in (("F16-r-push-mul-pE-w0", 147), ("F16-r-push-mulub-pE-w0", 119),
                       ("F16-r-push-div-pE-w0", 156)):
            m, s = _events21(cid, 5)
            self.assertEqual(m, s)
            self.assertEqual(s[3:], [(89, "data_read"), (w, "stack_write")])
        m, s = _events21("F16-l-push-divu_ix-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s[2], (129, "stack_write"))
        m, s = _events21("F16-l-push-mulu_aw-pO-w0", 3)
        self.assertEqual(s[2], (121, "stack_write"))

    def test_wp21_defaults_are_the_old_model(self):
        for name in ("count_latch", "abort_unit", "free_run", "io_exec"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


WP22 = dict(reg_div=True, io_take="unit", retry_first=True, unit_hold=True, abort_reg=True,
            sync_io="unit", slot_fetch="slot", disp_take="end",
            **{"shift_imm.hphase": 1, "shift_cl.hphase": 2, "mul.hphase": 2, "div.hphase": 2,
               "mul.wb": 2, "div.wb": 2, "mul.mtail": 2, "div.mtail": 2,
               "pop_mem.setup_free": 1})
_TWELFTH = []
_RUNS22 = {}


def _events22(cid, n=6, **kw):
    """(model, silicon) (clock, kind) lists from the fill, the fill fetch dropped, under the
    twelfth fit (fit-wp21-hand.json) + WP22 (+ kw)."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _TWELFTH:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp21-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _TWELFTH.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS22:
        _RUNS22[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS22[family][cid])
    cfg = _TWELFTH[0].replace(**{**WP22, **kw})
    m = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class OutFrameOdd(unittest.TestCase):
    """WP22, the OUT frame's remainder (no new acquisition), each rule against the alternative
    it replaced; silicon clocks from the fill quoted from the corpus (chains-F3/F14/F15/F16)."""

    def test_register_divide_is_register_only(self):
        # OUT; DIVU IX; OUT, even, 0 waits: DIVU starts on the marker's I/O clock 84 as MULU
        # AW does: F87 F132 I139, 8 after MULU AW's F124 I131; outside the register-only
        # classes it starts on the marker's port take: F126 I133
        m, s = _events22("F16-l-out-divu_ix-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(87, "fetch"), (132, "fetch"), (139, "io_write")])
        m, _ = _events22("F16-l-out-divu_ix-pE-w0", 5, reg_div=False)
        self.assertEqual(m[3:], [(126, "fetch"), (133, "io_write")])

    def test_request_under_the_io_on_a_latched_delivery(self):
        # OUT; MOV CL,4; SHL AW,CL; OUT, odd, 0 waits: the marker's I/O at 90 on fetch 87's
        # delivery, SHL takes its ModR/M there: no fetch until its last iteration, F108
        # F120 I123; as any request: F93 F121 I124
        m, s = _events22("F16-l-out-shlcl4-pO-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(108, "fetch"), (120, "fetch"), (123, "io_write")])
        m, _ = _events22("F16-l-out-shlcl4-pO-w0", 6, io_take="none")
        self.assertEqual(m[3:], [(93, "fetch"), (121, "fetch"), (124, "io_write")])
        # OUT; MULU [BW]; OUT, odd, 0 waits: the request fetch 82's delivery raises on the
        # I/O clock 85 waits for the multiply's loop exit: R93 F123 (drop: F96)
        m, s = _events22("F14-g-out-mulu_bw-pO-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:4], [(93, "data_read"), (123, "fetch")])
        m, _ = _events22("F14-g-out-mulu_bw-pO-w0", 5, io_take="drop")
        self.assertEqual(m[3], (96, "fetch"))
        # OUT; MULU AW; OUT, odd, 1 wait: F118 F130 I134; an aborted cycle after the I/O for
        # the multiply's dropped request (abort, refuted) holds its exec: F131 I135
        m, s = _events22("F16-l-out-mulu_aw-pO-w1", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(118, "fetch"), (130, "fetch"), (134, "io_write")])
        m, _ = _events22("F16-l-out-mulu_aw-pO-w1", 5, io_take="abort")
        self.assertEqual(m[3:], [(131, "fetch"), (135, "io_write")])

    def test_one_iteration_loop_raises_on_its_first_clock(self):
        # OUT; SHL AW,1; OUT, odd, 0 waits: the loop runs 93-94, the dropped request goes
        # at 93 (False: 94)
        m, s = _events22("F16-l-out-shl1-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[2], (93, "fetch"))
        m, _ = _events22("F16-l-out-shl1-pO-w0", 4, retry_first=False)
        self.assertEqual(m[2], (94, "fetch"))
        # MOV CL,1 ; NOP ; SHL AW,CL marker-less, even, 0 waits (the shift started on an
        # aborted cycle): F94 F100 (False: F95 F101)
        m, s = _events22("F16-s-none-cl1-n1-shlcl-pE-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(94, "fetch"), (100, "fetch")])
        m, _ = _events22("F16-s-none-cl1-n1-shlcl-pE-w0", 4, retry_first=False)
        self.assertEqual(m[2:], [(95, "fetch"), (101, "fetch")])

    def test_register_unit_held_by_a_fetch(self):
        # OUT; SHL AW,4; OUT, even, 1 wait: the exec from 92 with the back-to-back fetch
        # 92-95 costs its wait state: F117 I121 (False: F116 I120)
        m, s = _events22("F16-l-out-shli4-pE-w1", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[4:], [(117, "fetch"), (121, "io_write")])
        m, _ = _events22("F16-l-out-shli4-pE-w1", 6, unit_hold=False)
        self.assertEqual(m[4:], [(116, "fetch"), (120, "io_write")])
        # PUSH; MULU AW; PUSH, even, 1 wait: the back-to-back fetch 86-89 in the multiply's
        # exec costs its wait state + 1: w125 (False: w123)
        m, s = _events22("F16-l-push-mulu_aw-pE-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[3], (125, "stack_write"))
        m, _ = _events22("F16-l-push-mulu_aw-pE-w1", 4, unit_hold=False)
        self.assertEqual(m[3], (123, "stack_write"))
        # OUT; MOV CL,4; SHL AW,CL; OUT, even, 1 wait: the exec from the I/O's end 93 with
        # the fetch issued there: F117 I125 (False: F115 I123)
        m, s = _events22("F16-l-out-shlcl4-pE-w1", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[4:], [(117, "fetch"), (125, "io_write")])
        m, _ = _events22("F16-l-out-shlcl4-pE-w1", 6, unit_hold=False)
        self.assertEqual(m[4:], [(115, "fetch"), (123, "io_write")])

    def test_register_unit_started_on_an_aborted_cycle(self):
        # PUSH; MULU DW; MULU DW; PUSH, even, 0 waits: the second multiply on the aborted
        # cycle keeps its end and raises the request from the early start: F147 w156
        # (False: F150 w156)
        m, s = _events22("F3-push-mulu_dw-k2-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(147, "fetch"), (156, "stack_write")])
        m, _ = _events22("F3-push-mulu_dw-k2-pE-w0", 5, abort_reg=False)
        self.assertEqual(m[3:], [(150, "fetch"), (156, "stack_write")])
        # PUSH; SHL AW,1 twice; PUSH, even, 0 waits: F98 w107 (False: F99 w108)
        m, s = _events22("F3-push-shl1-k2-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(98, "fetch"), (107, "stack_write")])
        m, _ = _events22("F3-push-shl1-k2-pE-w0", 5, abort_reg=False)
        self.assertEqual(m[3:], [(99, "fetch"), (108, "stack_write")])

    def test_multiply_after_the_io_and_its_write_back(self):
        # OUT; MULU AW; NOP; OUT, even, 0 waits: the multiply's take on the I/O clock does
        # not wait for the fetch raised under the I/O; the NOP starts at 119 (F119); latch:
        # F121 F133 I136
        m, s = _events22("F16-l-out-mulu_aw_nop-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(119, "fetch"), (131, "fetch"), (134, "io_write")])
        m, _ = _events22("F16-l-out-mulu_aw_nop-pE-w0", 6, sync_io="latch")
        self.assertEqual(m[3:], [(121, "fetch"), (133, "fetch"), (136, "io_write")])
        # OUT; NOP; MULU AW; OUT, even, 0 waits: the closing OUT waits for the multiply's
        # write-back: F133 I136 (wb 0: F131 I134)
        m, s = _events22("F16-l-out-nop_mulu_aw-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[4:], [(133, "fetch"), (136, "io_write")])
        m, _ = _events22("F16-l-out-nop_mulu_aw-pE-w0", 6, **{"mul.wb": 0})
        self.assertEqual(m[4:], [(131, "fetch"), (134, "io_write")])

    def test_held_fetch_runs_in_the_moved_request_free_clocks(self):
        # OUT; POP [BW]; OUT, even, 0 waits: the stack read moves into the slot at the I/O's
        # issue 84; the fetch POP's ModR/M take requested at 80 runs on its first fetch-free
        # clock and the read counts through it: F88 r91 W99 (none: F87 r92 W100)
        m, s = _events22("F15-p-out-pop_bw-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(88, "fetch"), (91, "stack_read"), (99, "data_write")])
        m, _ = _events22("F15-p-out-pop_bw-pE-w0", 5, slot_fetch="none")
        self.assertEqual(m[2:], [(87, "fetch"), (92, "stack_read"), (100, "data_write")])

    def test_one_byte_displacement_taken_where_a_two_byte_one_ends(self):
        # OUT; POP [BW+d8]; OUT, odd, 0 waits: r91, the displacement taken at 97 (as the
        # direct form's second byte), F97 W100 (start: F96 W99)
        m, s = _events22("F15-p-out-pop_bw_d8-pO-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(91, "stack_read"), (97, "fetch"), (100, "data_write")])
        m, _ = _events22("F15-p-out-pop_bw_d8-pO-w0", 5, disp_take="start")
        self.assertEqual(m[3:], [(96, "fetch"), (99, "data_write")])
        # PUSH; NOP; POP [0C00h]; PUSH, odd, 0 waits: F97 W100 either way
        for take in ("end", "start"):
            m, s = _events22("F16-p-push-n1-pop_dir-pO-w0", 5, disp_take=take)
            self.assertEqual(m, s)
            self.assertEqual(s[2:4], [(91, "stack_read"), (97, "fetch")])

    def test_wp22_defaults_are_the_old_model(self):
        for name in ("reg_div", "io_take", "retry_first", "unit_hold", "abort_reg",
                     "slot_fetch", "disp_take"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        self.assertEqual(DEFAULT.sync_io, "none")


# WP23 (F17, the refresh fill phase made observable): the thirteenth fit plus the WP23
# rules, saved as fit-wp23-hand.json.
_WP23 = []
_RUNS23 = {}


def _wp23():
    import json
    from pathlib import Path
    if not _WP23:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp23-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP23.append(Config.from_json(json.loads(path.read_text())))
    return _WP23[0]


def _events23(cid, n=None, **kw):
    """(clock, kind) from the fill of a recorded run (F8, F13, F17), the fill fetch dropped,
    under the WP23 hand fit (+ kw), and the silicon list the same way."""
    from validation.v35s.chains.sim.machine import refresh_anchor

    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    cfg = _wp23().replace(**kw)
    m = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    got = [(e[0], e[1]) for e in aligned(m)][1:]
    sil = [(e[0], e[1]) for e in aligned(s)][1:]
    return (got, sil) if n is None else (got[:n], sil[:n])


def _clocks(events, kind):
    return [c for c, k in events if k == kind]


class RefreshFillPhase(unittest.TestCase):
    """WP23: the chain writes RFM itself after a refresh-off prelude (F17), so the first LS
    and its fill are the refresh-off model's; each rule against its alternative on a named
    run, silicon clocks from t_fill quoted from chains-F17-w<N>, chains-F13-w<N>."""

    def test_rfmon_is_an_on_chip_store(self):
        # 26 C6 06 E1 FF ii = DS1: MOV byte [0FFE1h],ii; with DS1 = F000h the store reaches
        # RFM (FFFE1h) and makes no bus cycle on the pins; it holds the bus unit 3 clocks at
        # every memory wait setting. F17-e-n0-empty-pE-w1 (refresh stays off): F72 F76 F80
        # F90 F94 F173; with the memory-wait length (bus) F91 F95 F174
        self.assertEqual(FORMS["rfm_fc"].code, bytes.fromhex("26c606e1fffc"))
        op = decode(FORMS["rfm_fc"].code, 1, dict(FORMS_REGS))
        self.assertEqual((op.cls, op.length, op.width, op.ea, op.imm_bytes),
                         ("store_imm", 5, 1, 0xFFE1, 1))
        got, sil = _events23("F17-e-n0-empty-pE-w1")
        self.assertEqual(got, sil)
        self.assertNotIn("data_write", [k for _, k in sil])
        self.assertEqual(_clocks(sil, "fetch")[:5], [72, 76, 80, 90, 94])
        bus = _events23("F17-e-n0-empty-pE-w1", sfr_cycle="bus")[0]
        self.assertEqual(_clocks(bus, "fetch")[3:6], [91, 95, 174])

    def test_timer_runs_free_through_the_write(self):
        # the timer is not restarted by the RFM write: F17-d-n0-empty-pE-w1 (FDh) refreshes
        # 106 139 170, F181; a timer restarted on the write gives 104 135 168
        got, sil = _events23("F17-d-n0-empty-pE-w1")
        self.assertEqual(got, sil)
        self.assertEqual(_clocks(sil, "refresh")[:3], [106, 139, 170])
        write = _events23("F17-d-n0-empty-pE-w1", refresh_restart="write")[0]
        self.assertEqual(_clocks(write, "refresh")[:3], [104, 135, 168])

    def test_counter_phase_is_the_preludes(self):
        # no per-run alignment: the counter's value at clock 0 is a constant of the prelude
        # (refresh.PRELUDE_COUNTER): the W series moves the write 4 clocks per NOP and every
        # run keeps one grid (n0 and n4, 16 clocks apart, exact with the same constant);
        # F13-r-rfm-f2-pE-w1
        # (the FCh prelude's table entry for RFT 2) as the per-run alignment: X147 F167
        from validation.v35s.chains.sim.refresh import PRELUDE_COUNTER, SILICON_FILL
        self.assertEqual(PRELUDE_COUNTER[(0xEC, 0)], 16)
        self.assertEqual(SILICON_FILL[(0xEC, 0, "even")], 28)
        for cid in ("F17-w-fc-n0-pE-w0", "F17-w-fc-n4-pE-w0"):
            got, sil = _events23(cid)
            self.assertEqual(got, sil)
        self.assertEqual(_clocks(_events23("F17-w-fc-n0-pE-w0")[1], "refresh")[1:4],
                         [108, 125, 140])
        got, sil = _events23("F13-r-rfm-f2-pE-w1")
        self.assertEqual(got, sil)
        self.assertEqual(got, _events23("F13-r-rfm-f2-pE-w1", refresh_align="phase")[0])

    def test_rft_write_raises_a_request_on_the_selected_bit(self):
        # the request is the rising edge of the counter bit RFT selects, against the previous
        # clock's selected bit: switching to RFT 1 while bit 4 is high and bit 3 low raises
        # one at once. F17-w-fd-n6-pE-w0: X108 F113 F116 X133 (due: F111 F114 X133);
        # F17-w-fd-n4-pE-w2: X108 (due: none until 135)
        for cid, x in (("F17-w-fd-n6-pE-w0", 108), ("F17-w-fd-n4-pE-w2", 108)):
            got, sil = _events23(cid)
            self.assertEqual(got, sil)
            self.assertEqual(_clocks(sil, "refresh")[0], x)
            due = _events23(cid, refresh_counter="due")[0]
            self.assertNotIn(x, _clocks(due, "refresh"))

    def test_rfen_takes_effect_three_clocks_after_the_store(self):
        # F17-s-n0-st-pO-w1: the request at 84 comes before RFEN, the first refresh at 100
        # after MOV [BW],AW's write at 93; 2 clocks: a refresh at 85
        got, sil = _events23("F17-s-n0-st-pO-w1")
        self.assertEqual(got, sil)
        self.assertEqual(sil[4:6], [(93, "data_write"), (100, "refresh")])
        self.assertEqual(_events23("F17-s-n0-st-pO-w1", rfm_delay=2)[0][2], (85, "refresh"))

    def test_halted_queue_runs_the_fetches_a_refresh_held(self):
        # the END block: the refresh at 259 beats the fetch MOV DW's take raised, HALT starts
        # meanwhile; silicon F264 F269 then the I/O at 279 (none: I269).
        # F13-s-shlcl12-pE-w2
        got, sil = _events23("F13-s-shlcl12-pE-w2")
        self.assertEqual(got, sil)
        self.assertEqual(sil[-5:], [(259, "refresh"), (264, "fetch"), (269, "fetch"),
                                    (274, "refresh"), (279, "io_write")])
        none = _events23("F13-s-shlcl12-pE-w2", halt_refresh="none")[0]
        self.assertEqual(none[-1], (269, "io_write"))

    def test_beaten_request_lost_at_odd_room_and_raised_at_the_loop_exit(self):
        # a refresh that beats a request raised on a word's delivery clock with its second
        # byte latched and an odd room loses it; a count loop running raises it again as its
        # exit starts. F13-s-shlcl2-pO-w1: X97 X113 F118 (kept: F102); F13-c-out-shlcl5-pO-w1:
        # X128 F138 X145 (queue: no fetch until 152; the last iteration's start: F135)
        got, sil = _events23("F13-s-shlcl2-pO-w1")
        self.assertEqual(got, sil)
        self.assertEqual(sil[7:10], [(97, "refresh"), (113, "refresh"), (118, "fetch")])
        self.assertEqual(_events23("F13-s-shlcl2-pO-w1", refresh_drop=False)[0][8],
                         (102, "fetch"))
        got, sil = _events23("F13-c-out-shlcl5-pO-w1")
        self.assertEqual(got, sil)
        self.assertIn((138, "fetch"), sil)
        self.assertNotIn((138, "fetch"), _events23("F13-c-out-shlcl5-pO-w1",
                                                   refresh_reraise="queue")[0])
        self.assertIn((135, "fetch"), _events23("F13-c-out-shlcl5-pO-w1", reraise_off=-2)[0])
        # only an odd room: F13-s-shlcl12-pE-w2 keeps the request (X98 F103); dropping every
        # request raised by a delivery (arrival) gives X98 X111
        got, sil = _events23("F13-s-shlcl12-pE-w2")
        self.assertEqual(sil[7:9], [(98, "refresh"), (103, "fetch")])
        self.assertEqual(_events23("F13-s-shlcl12-pE-w2", refresh_drop_on="arrival")[0][8],
                         (111, "refresh"))

    def test_take_of_several_bytes_takes_the_refresh_on_its_last(self):
        # the END's MOV DW,0FF00h takes its immediate over two clocks; the refresh goes on
        # the second. F17-s-n1-empty-pE-w0: X190 F195 F198 (any: X189 F194 F197)
        got, sil = _events23("F17-s-n1-empty-pE-w0")
        self.assertEqual(got, sil)
        self.assertIn((190, "refresh"), sil)
        self.assertIn((189, "refresh"), _events23("F17-s-n1-empty-pE-w0", refresh_take="any")[0])

    def test_refuted_holds(self):
        # a refresh taken on a count loop's first clock holding the loop there (hold), or an
        # instruction's first clocks step begun on the refresh's first clock waiting for it
        # (start_hold): F17-s-n1-rmw-pE-w0 F209 (hold: F213); F13-s-shlcl12-pE-w2 F264 F269
        # (start: F264 X271)
        got, sil = _events23("F17-s-n1-rmw-pE-w0")
        self.assertEqual(got, sil)
        self.assertIn((209, "fetch"), sil)
        self.assertNotIn((209, "fetch"), _events23("F17-s-n1-rmw-pE-w0",
                                                   refresh_loop_entry="hold")[0])
        self.assertNotIn((269, "fetch"), _events23("F13-s-shlcl12-pE-w2",
                                                   refresh_start_hold="start")[0])

    def test_refresh_off_reads_no_wp23_field(self):
        # the WP23 fields are read only by a chain with refresh on or an RFM store
        from validation.v35s.chains import fit

        chain = _chain("F5", "F5-push-st_bw-k1-pE-w0")
        rc = fit.recording(_wp23())
        simulate_normalized(chain, rc)
        wp23 = {"sfr_cycle", "refresh_restart", "refresh_counter", "halt_refresh",
                "refresh_take", "refresh_start_hold", "rfm_delay", "reraise_off"}
        self.assertFalse([n for n in rc._reads if n.startswith("refresh") or n in wp23])


_WP24 = []


def _wp24():
    import json
    from pathlib import Path
    if not _WP24:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp24-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP24.append(Config.from_json(json.loads(path.read_text())))
    return _WP24[0]


def _events24(cid, **kw):
    """(clock, kind) from the fill of a recorded run (F2, F17, F18) under the WP24 hand fit
    (+ kw), the fill fetch dropped, and the silicon list the same way."""
    from validation.v35s.chains.sim.machine import refresh_anchor

    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    m = simulate_normalized(s.chain, _wp24().replace(**kw), s.chain_base,
                            refresh=refresh_anchor(s))
    return [(e[0], e[1]) for e in aligned(m)][1:], [(e[0], e[1]) for e in aligned(s)][1:]


class RefreshLadderAndPrelude(unittest.TestCase):
    """WP24 (F18): the prelude marker, the exec-boundary ladder; each rule against its
    alternative on a named run, silicon clocks from t_fill quoted from chains-F18-w<N>,
    chains-F17-w<N> and chains-F2-w<N>."""

    def test_prelude_tail_reproduces_the_fill_and_the_marker(self):
        # prelude_tail=segs (refuted for a refresh-on prelude, kept as an option): the model
        # runs the prelude from its segment loads and finds silicon's t_fill and prelude
        # marker clock (rel clock 0) with refresh off and no SILICON_FILL: PUSH AW at pE w0
        # t_fill 27, write 16; OUT 20h,AL at pO w2 t_fill 40, I/O 28; no marker pE w1 28/32
        from validation.v35s.chains.families import generate
        from validation.v35s.chains.image import build_image
        cfg = _wp24().replace(prelude_tail="segs", wlatch_ir_at="start")
        chains = {c.id: c for c in generate(["F18", "F0"])}
        for cid, fill, mark in (("F18-a-push-ec-empty-pE-w0", 27, 16),
                                ("F18-a-out-ec-empty-pO-w2", 40, 28),
                                ("F0-ls-pE-w1", 32, None)):
            c = chains[cid]
            n = simulate_normalized(c, cfg, build_image(c).chain_base)
            self.assertEqual((n.t_fill, n.t_pre_marker), (fill, mark), cid)
            stand = simulate_normalized(c, _wp24(), build_image(c).chain_base)
            self.assertNotEqual(stand.t_fill, fill, cid)     # the stand-in's own fill

    def test_latch_sync_lapse_needs_the_latch_busy_at_the_io_start(self):
        # wlatch_ir_at=start: under the prelude tail the first LS's SHL AW,CL runs with the
        # OUT marker in the IR; silicon F2-out-empty-pE-w0: the OUT's port-take fetch 77,
        # I/O 84 rel t_fill (busy, the shift's take sync lapsing: 75, 82)
        got, sil = _events24("F2-out-empty-pE-w0", prelude_tail="segs", wlatch_ir_at="start")
        self.assertEqual(got, sil)
        self.assertEqual(_clocks(sil, "io_write")[0], 84)
        busy = _events24("F2-out-empty-pE-w0", prelude_tail="segs", wlatch_ir_at="busy")[0]
        self.assertEqual(_clocks(busy, "io_write")[0], 82)
        self.assertEqual(_events24("F2-out-empty-pE-w0", wlatch_ir_at="busy")[0], got)

    def test_the_divider_is_the_multipliers_count_loop(self):
        # refresh_unit=muldiv: F18-b-n0-divu-pE-w0 refreshes 93 108 125 inside DIVU IX's
        # exec (mul: the first refresh after the divide, 126)
        got, sil = _events24("F18-b-n0-divu-pE-w0")
        self.assertEqual(_clocks(got, "refresh")[:3], [93, 108, 125])
        self.assertEqual(_clocks(sil, "refresh")[:3], [93, 108, 125])
        mul = _events24("F18-b-n0-divu-pE-w0", refresh_unit="mul")[0]
        self.assertEqual(_clocks(mul, "refresh")[0], 126)

    def test_the_memory_shift_takes_refreshes_in_its_loop(self):
        # refresh_rmw_loop=loop, span all: F18-b-n1-shlmcl-pE-w2 (SHL [BW],CL, CL 31) read
        # 108, refreshes 113 128 143 160 175 before the write (silicon 198); plain: 179;
        # the loop's clocks only: the first at 121
        got, sil = _events24("F18-b-n1-shlmcl-pE-w2")
        self.assertEqual(_clocks(sil, "refresh")[1:6], [113, 128, 143, 160, 175])
        self.assertEqual(_clocks(got, "refresh")[1:6], [113, 128, 143, 160, 175])
        self.assertEqual(_clocks(_events24("F18-b-n1-shlmcl-pE-w2",
                                           refresh_rmw_loop="plain")[0], "refresh")[1], 179)
        self.assertEqual(_clocks(_events24("F18-b-n1-shlmcl-pE-w2",
                                           refresh_rmw_span="loop")[0], "refresh")[1], 121)

    def test_the_loop_eve_boundary_follows_a_recent_refresh(self):
        # refresh_exec=every2_recent (refresh_recent 18): F17-d-n1-shlcl16-pE-w0, the first
        # request after RFEN at the shift's exec + 3: silicon refresh 103 on the loop's first
        # clock, the closing LS's fetches 147 150 (every2: 101, 145 148); F17-s-n0-shlcl4-pE-w2,
        # a request at exec + 3 14 clocks after the previous refresh: 112, the eve's boundary
        # (every2_early: 113)
        got, sil = _events24("F17-d-n1-shlcl16-pE-w0")
        self.assertEqual(got, sil)
        self.assertEqual(_clocks(sil, "refresh")[0], 103)
        e2 = _events24("F17-d-n1-shlcl16-pE-w0", refresh_exec="every2")[0]
        self.assertEqual(_clocks(e2, "refresh")[0], 101)
        got, sil = _events24("F17-s-n0-shlcl4-pE-w2")
        self.assertEqual(_clocks(got, "refresh")[:2], _clocks(sil, "refresh")[:2])
        early = _events24("F17-s-n0-shlcl4-pE-w2", refresh_exec="every2_early")[0]
        self.assertNotEqual(_clocks(early, "refresh")[:2], _clocks(sil, "refresh")[:2])


# WP25 (F19, the immediate memory forms and the DW I/O forms): the fifteenth fit
# (fit-wp24.json) plus the WP25 rules, saved as fit-wp25-hand.json.
WP25 = dict(imm_count="start", dw_port="hold", dw_slot="behind",
            **{"store_imm.istart": 5, "rmw_imm.istart": 5, "store_imm.grp1": 2})
_FIFTEENTH = []
_RUNS25 = {}


def _events25(cid, n=4, **kw):
    """(model, silicon) (clock, kind) lists from the fill, the fill fetch dropped, under the
    fifteenth fit + WP25 (+ kw)."""
    import json
    from pathlib import Path

    if not _FIFTEENTH:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp24.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _FIFTEENTH.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS25:
        _RUNS25[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS25[family][cid])
    m = simulate_normalized(s.chain, _FIFTEENTH[0].replace(**{**WP25, **kw}), s.chain_base)
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class ImmediateAndDwForms(unittest.TestCase):
    """WP25 (F19), each rule against the alternative it replaced; silicon clocks from the
    fill quoted from the corpus (chains-F19-w0..w2)."""

    def test_decode_f19_forms(self):
        regs = {**FORMS_REGS, "DW": 0x40}
        for name, cls, length, imm in (("st_imm8_bw", "store_imm", 3, 1),
                                       ("st_imm_bw_d8", "store_imm", 5, 2),
                                       ("cmp_m_imm8", "load_alu", 3, 1)):
            op = decode(FORMS[name].code, 0, regs)
            self.assertEqual((op.cls, op.length, op.imm_bytes), (cls, length, imm), name)
        for name, cls, width in (("out_dw_b", "out", 1), ("in_aw_dw", "in", 2),
                                 ("out_dw_al", "out", 2)):
            op = decode(FORMS[name].code, 0, regs)
            self.assertEqual((op.cls, op.length, op.width, op.port), (cls, 1, width, 0x40))

    def test_immediate_form_counts_from_its_start(self):
        # PUSH; NOP; MOV [BW],imm16; PUSH, odd, 0 waits: no fetch in the head, the write at
        # s+7 = 92 as with one at even parity (none: W90)
        m, s = _events25("F19-i-push-n1-stimm-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s, [(78, "stack_write"), (81, "fetch"), (92, "data_write")])
        m, _ = _events25("F19-i-push-n1-stimm-pO-w0", 3, imm_count="none")
        self.assertEqual(m[2], (90, "data_write"))
        # CMP [BW],imm16 reads on the same clock (none: R90)
        m, s = _events25("F19-i-push-n1-cmpimm-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s[2], (92, "data_read"))
        m, _ = _events25("F19-i-push-n1-cmpimm-pO-w0", 3, imm_count="none")
        self.assertEqual(m[2], (90, "data_read"))
        # marker-less, odd: W79 = s+7 (none: W77)
        m, s = _events25("F19-i-none-l0-stimm-pO-w0", 2)
        self.assertEqual(m, s)
        self.assertEqual(s, [(79, "data_write"), (82, "fetch")])
        m, _ = _events25("F19-i-none-l0-stimm-pO-w0", 2, imm_count="none")
        self.assertEqual(m[0], (77, "data_write"))
        # 1 wait, no fetch in the head: s+7 at every wait (none: W95)
        m, s = _events25("F19-i-push-n2-stimm-pO-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[3], (97, "data_write"))
        m, _ = _events25("F19-i-push-n2-stimm-pO-w1", 4, imm_count="none")
        self.assertEqual(m[3], (95, "data_write"))
        # the one-byte immediate: s+6 (none: W89)
        m, s = _events25("F19-i-push-n1-stimm8-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s[2], (91, "data_write"))
        m, _ = _events25("F19-i-push-n1-stimm8-pO-w0", 3, imm_count="none")
        self.assertEqual(m[2], (89, "data_write"))

    def test_byte_store_immediate_group_setup(self):
        # PUSH; MOV byte [BW],imm8; PUSH, odd, 1 wait: C6 /0 takes 83's one-byte group setup
        # (grp1 2): F82 W89 F93 (grp1 0: W88 F92)
        m, s = _events25("F19-i-push-l0-stimm8-pO-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(82, "fetch"), (89, "data_write"), (93, "fetch")])
        m, _ = _events25("F19-i-push-l0-stimm8-pO-w1", 4, **{"store_imm.grp1": 0})
        self.assertEqual(m[2:], [(88, "data_write"), (92, "fetch")])

    def test_port_form_waits_behind_a_dw_form(self):
        # OUT 20h; OUT DW,AL; OUT 21h, odd, 0 waits: the marker's I/O at 85 unheld, the DW
        # I/O at 94 (the closing OUT's port take at 91 + 3); latch: I88 F93 I96
        m, s = _events25("F19-d-out-none-outb-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s, [(82, "fetch"), (85, "io_write"), (94, "io_write"), (97, "fetch")])
        m, _ = _events25("F19-d-out-none-outb-pO-w0", 4, dw_port="latch")
        self.assertEqual(m[1:], [(88, "io_write"), (93, "fetch"), (96, "io_write")])
        # OUT 20h; OUT DW,AL twice; OUT 21h, even: I84 F89 I92 I101 (latch: I92 F97 I100)
        m, s = _events25("F19-d-out-pair-outb-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(92, "io_write"), (101, "io_write")])
        m, _ = _events25("F19-d-out-pair-outb-pE-w0", 5, dw_port="latch")
        self.assertEqual(m[4], (97, "fetch"))

    def test_dw_request_in_the_slot_holds_the_lead_fetch(self):
        # PUSH; OUT DW,AL twice; PUSH, odd, 0 waits: 4 bytes queued and the marker's write
        # posted behind the second DW I/O: I88 I95 (bus: F93 I96)
        m, s = _events25("F19-d-push-pair-outb-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(85, "fetch"), (88, "io_write"), (95, "io_write")])
        m, _ = _events25("F19-d-push-pair-outb-pO-w0", 4, dw_slot="bus")
        self.assertEqual(m[3], (93, "fetch"))
        # OUT 20h; OUT DW,AL twice, odd: the second DW form posted behind: I85 I92 (bus: F90)
        m, s = _events25("F19-d-out-pair-outb-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[1:3], [(85, "io_write"), (92, "io_write")])
        m, _ = _events25("F19-d-out-pair-outb-pO-w0", 4, dw_slot="bus")
        self.assertEqual(m[2], (90, "fetch"))
        # with 3 bytes queued, or nothing posted behind, the fetch runs first
        for cid in ("F19-d-push-pair-outb-pE-w0", "F19-d-none-outimm-outb-pE-w0"):
            m, s = _events25(cid, 4)
            self.assertEqual(m, s, cid)
            self.assertEqual(s[3], (93, "fetch") if "push" in cid else (92, "io_write"))
            self.assertEqual(s[2][1], "io_write" if "push" in cid else "fetch")

    def test_wp25_defaults_are_the_old_model(self):
        for name in ("imm_count", "dw_slot", "dw_port"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


# WP26 (F20, finding 4: the register form before a load, a store, an RMW, an I/O form or
# another register form): the sixteenth fit (fit-wp25.json) plus the WP26 rules, saved as
# fit-wp26-hand.json.
WP26 = dict(request_reissue="no_mem", modrm_mate="imm", io_b2b="all", io_b2b_q=3,
            dw_count_b2b=True, port_landed=True)
_SIXTEENTH = []
_RUNS26 = {}


def _events26(cid, n=4, **kw):
    """(model, silicon) (clock, kind) lists from the fill, the fill fetch dropped, under the
    sixteenth fit + WP26 (+ kw)."""
    import json
    from pathlib import Path

    if not _SIXTEENTH:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp25.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _SIXTEENTH.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS26:
        _RUNS26[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS26[family][cid])
    m = simulate_normalized(s.chain, _SIXTEENTH[0].replace(**{**WP26, **kw}), s.chain_base)
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class RegisterFormBeforeDw(unittest.TestCase):
    """WP26 (F20), each rule against the alternative it replaced; silicon clocks from the
    fill quoted from the corpus (chains-F20-w0..w2, F19, F6, F4, F7, F1, F3)."""

    def test_request_raised_again_after_the_issue(self):
        # OUT 20h; MOV AW,imm16; MOV AW,[BW], even, 0 waits (the F6 n1 drain): the last
        # immediate byte taken and the load into the IR on fetch 88's issue clock; the fetch
        # 91 back to back holds the load (b2b_modrm): R99 (none: R97, the same fetches)
        for cid in ("F6-out-ld_bw-n1-pE-w0", "F20-r-out-l0-movawi-ld-pE-w0"):
            m, s = _events26(cid, 6)
            self.assertEqual(m, s, cid)
            self.assertEqual(s[2:], [(88, "fetch"), (91, "fetch"), (94, "fetch"),
                                     (99, "data_read")])
            m, _ = _events26(cid, 6, request_reissue="none")
            self.assertEqual(m[5], (97, "data_read"))

    def test_not_while_a_memory_request_waits(self):
        # the A3 store marker after the fence: the write posted on the address take on fetch
        # 75's issue clock goes first: F75 W78 F81 (always: F75 F78 W81)
        m, s = _events26("F1-store-m1-pE-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s, [(75, "fetch"), (78, "data_write"), (81, "fetch")])
        m, _ = _events26("F1-store-m1-pE-w0", 3, request_reissue="always")
        self.assertEqual(m, [(75, "fetch"), (78, "fetch"), (81, "data_write")])

    def test_modrm_word_mate_keeps_the_word(self):
        # PUSH; ADD DW,0 (81 C2 at an odd address, the ModR/M even); OUT DW,AL, 0 waits: the
        # immediate's first byte taken on fetch 81's delivery clock 84: no fetch there,
        # w78 F81 F85 F88 I95 (False: F84 F87 I96)
        m, s = _events26("F19-d-push-adddwi-outb-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s, [(78, "stack_write"), (81, "fetch"), (85, "fetch"), (88, "fetch"),
                             (95, "io_write")])
        m, _ = _events26("F19-d-push-adddwi-outb-pE-w0", 5, modrm_mate=False)
        self.assertEqual(m[2:], [(84, "fetch"), (87, "fetch"), (96, "io_write")])
        # a displacement byte in the same place frees the word: MOV AW,[BW+d16] after the
        # PUSH, F81 F84 F87 R90 (any: F85 F88 R91)
        m, s = _events26("F4-push-ld_bw_d16-k1-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(81, "fetch"), (84, "fetch"), (87, "fetch"), (90, "data_read")])
        m, _ = _events26("F4-push-ld_bw_d16-k1-pE-w0", 5, modrm_mate="any")
        self.assertEqual(m[2], (85, "fetch"))

    def test_shallow_queue_holds_a_start_off_the_back_to_back_clock(self):
        # OUT 20h; MOV AW,DW twice; OUT 21h, even, 1 wait: the closing OUT due on fetch 92's
        # issue clock with 2 bytes stored starts on fetch 96's: I107 (False: I104)
        m, s = _events26("F7-out-mov_aw_dw-mov_aw_dw-pE-w1", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(88, "fetch"), (92, "fetch"), (96, "fetch"), (107, "io_write")])
        m, _ = _events26("F7-out-mov_aw_dw-mov_aw_dw-pE-w1", 6, io_b2b=False)
        self.assertEqual(m[5], (104, "io_write"))
        # OUT 20h; ADD DW,0; IN AL,DW, even, 0 waits: the IN due on fetch 91's issue clock
        # with 2 stored: i101 (False: i99)
        m, s = _events26("F19-d-out-adddwi-inb-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[5], (101, "io_read"))
        m, _ = _events26("F19-d-out-adddwi-inb-pE-w0", 6, io_b2b=False)
        self.assertEqual(m[5], (99, "io_read"))
        # the NOP between is held the same way (io: only the I/O forms, i105)
        m, s = _events26("F19-d-out-adddwi_nop-inb-pE-w1", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[5], (107, "io_read"))
        m, _ = _events26("F19-d-out-adddwi_nop-inb-pE-w1", 6, io_b2b="io")
        self.assertEqual(m[5], (105, "io_read"))
        # with 3 bytes stored the OUT starts on the back-to-back clock: MOV AW,imm16 then
        # OUT 21h, F89 F93 F97 I105
        m, s = _events26("F3-out-mov_aw_imm-k1-pE-w1", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(89, "fetch"), (93, "fetch"), (97, "fetch"), (105, "io_write")])

    def test_dw_count_skips_a_back_to_back_fetch(self):
        # OUT 20h; MOV AW,DW; IN AL,DW, even, 0 waits: the IN starts on fetch 87's issue
        # clock, fetch 90 back to back: i95 (False: i94)
        m, s = _events26("F19-d-out-movawdw-inb-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(87, "fetch"), (90, "fetch"), (95, "io_read")])
        m, _ = _events26("F19-d-out-movawdw-inb-pE-w0", 5, dw_count_b2b=False)
        self.assertEqual(m[4], (94, "io_read"))

    def test_port_byte_landed_relatches_a_clock_later(self):
        # OUT 20h; MOV AW,DW; OUT DW,AL; OUT 21h, even, 0 waits: the closing OUT's port byte
        # taken at 93 on fetch 90's delivery clock: the DW I/O at 97 (False: I96)
        m, s = _events26("F19-d-out-movawdw-outb-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(87, "fetch"), (90, "fetch"), (97, "io_write")])
        m, _ = _events26("F19-d-out-movawdw-outb-pE-w0", 5, port_landed=False)
        self.assertEqual(m[4], (96, "io_write"))

    def test_wp26_defaults_are_the_old_model(self):
        for name in ("request_reissue", "modrm_mate", "io_b2b", "dw_count_b2b", "port_landed"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


# WP27 (F21, the effective-address path): the seventeenth fit (fit-wp26.json) plus the WP27
# rules and integers, saved as fit-wp27-hand.json.
WP27 = {"disp16": "word", "ea_disp16": "own", "ea_direct": "base_disp",
        "ea.base_index_disp16": 3, "load_alu.fdisp": 4, "pop_mem.setup_free": 0,
        "imm_head": "split", "sync_req": "disp", "store_imm.dadd": 1}
_SEVENTEENTH = []
_RUNS27 = {}


def _events27(cid, n=4, **kw):
    """(model, silicon) (clock, kind) lists from the fill, the fill fetch dropped, under the
    seventeenth fit + WP27 (+ kw)."""
    import json
    from pathlib import Path

    if not _SEVENTEENTH:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp26.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _SEVENTEENTH.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS27:
        _RUNS27[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS27[family][cid])
    m = simulate_normalized(s.chain, _SEVENTEENTH[0].replace(**{**WP27, **kw}), s.chain_base)
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class DisplacementForms(unittest.TestCase):
    """WP27 (F21), each rule against the alternative it replaced; silicon clocks from the
    fill quoted from the corpus (chains-F21-w0..w2, F4, F15)."""

    def test_two_byte_displacement_in_one_clock(self):
        # NOP; MOV AW,[BW+200h], marker-less, 0 waits: the d16 taken in one clock after the
        # EA clocks, the same clocks as [BW+10h]: F76 F79 R82 (byte: F80 R83)
        m, s = _events27("F21-none-n1-ld-bw_d16-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s, [(76, "fetch"), (79, "fetch"), (82, "data_read")])
        m, _ = _events27("F21-none-n1-ld-bw_d16-pO-w0", 3, disp16="byte")
        self.assertEqual(m[1:], [(80, "fetch"), (83, "data_read")])
        # F4's PUSH-frame base+d16 load at pO: F81 F84 R87 (byte: F85 R88)
        m, s = _events27("F4-push-ld_bw_d16-k1-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(81, "fetch"), (84, "fetch"), (87, "data_read")])
        m, _ = _events27("F4-push-ld_bw_d16-k1-pO-w0", 4, disp16="byte")
        self.assertEqual(m[2:], [(85, "fetch"), (88, "data_read")])

    def test_base_index_with_d16_has_its_own_ea(self):
        # PUSH; MOV AW,[BW+IX+200h], pO, 0 waits: one clock after base+d16's F84 R87:
        # w78 F81 F85 R88 (same: F84 R87)
        m, s = _events27("F21-push-l0-ld-bw_ix_d16-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s, [(78, "stack_write"), (81, "fetch"), (85, "fetch"), (88, "data_read")])
        m, _ = _events27("F21-push-l0-ld-bw_ix_d16-pO-w0", 4, ea_disp16="same")
        self.assertEqual(m[2:], [(84, "fetch"), (87, "data_read")])
        # POP [BW+IX+200h], marker-less: the extra clock before the displacement leaves the
        # queue: r78 F85 W88 (same: F84 W87)
        m, s = _events27("F21-none-l0-pop-bw_ix_d16-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s, [(78, "stack_read"), (85, "fetch"), (88, "data_write")])
        m, _ = _events27("F21-none-l0-pop-bw_ix_d16-pO-w0", 3, ea_disp16="same")
        self.assertEqual(m[1:], [(84, "fetch"), (87, "data_write")])

    def test_modrm_direct_address_is_a_d16(self):
        # ES: NOP; MOV AW,[0C00h] (8B 06), marker-less, pE, 0 waits: [BW+200h]'s clocks,
        # F82 R85 (own, EA 0: F81 R84)
        for cid in ("F21-none-es-ld-dir-pE-w0", "F21-none-es-ld-bw_d16-pE-w0"):
            m, s = _events27(cid, 4)
            self.assertEqual(m, s, cid)
            self.assertEqual(s[2:], [(82, "fetch"), (85, "data_read")])
        m, _ = _events27("F21-none-es-ld-dir-pE-w0", 4, ea_direct="own")
        self.assertEqual(m[2:], [(81, "fetch"), (84, "data_read")])
        # POP [0C00h] under PUSH, pE, 1 wait: W99 (own: W97)
        m, s = _events27("F15-p-push-pop_dir-pE-w1", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[4], (99, "data_write"))
        m, _ = _events27("F15-p-push-pop_dir-pE-w1", 5, ea_direct="own")
        self.assertEqual(m[4], (97, "data_write"))

    def test_integers_moved_with_the_rules(self):
        # direct TEST's lookup (fdisp 4 with the d16 taken in one clock): F81 F87 R90 (5: F88)
        m, s = _events27("F15-a-push-test_dir_aw-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s, [(78, "stack_write"), (81, "fetch"), (87, "fetch")])
        m, _ = _events27("F15-a-push-test_dir_aw-pO-w0", 3, **{"load_alu.fdisp": 5})
        self.assertEqual(m[2], (88, "fetch"))
        # POP [BW+200h]'s memory write counts its setup through the fetch the displacement
        # raised (setup_free 0): r78 F84 W87 (1: F84 F87 W90)
        m, s = _events27("F21-none-l0-pop-bw_d16-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s, [(78, "stack_read"), (84, "fetch"), (87, "data_write")])
        m, _ = _events27("F21-none-l0-pop-bw_d16-pO-w0", 3, **{"pop_mem.setup_free": 1})
        self.assertEqual(m[2], (87, "fetch"))

    def test_immediate_store_takes_its_displacement_after_the_ea(self):
        # MOV [BW+10h],imm16 at an odd ModR/M word, marker-less, 0 waits: the d8 taken after
        # the EA clocks with the fetch it frees at s+3, the write at s+7: F75 W79
        # (disp_ea: the d8 right after the ModR/M byte, F73)
        m, s = _events27("F21-none-l0-sti-bw_d8-pO-w0", 2)
        self.assertEqual(m, s)
        self.assertEqual(s, [(75, "fetch"), (79, "data_write")])
        m, _ = _events27("F21-none-l0-sti-bw_d8-pO-w0", 2, imm_head="disp_ea")
        self.assertEqual(m[0], (73, "fetch"))
        # no take sync after the displacement on the fetch it raised (either: W81)
        m, _ = _events27("F21-none-l0-sti-bw_d8-pO-w0", 2, sync_req="either")
        self.assertEqual(m[1], (81, "data_write"))

    def test_displacement_on_a_late_fetch_clock_and_the_store_clock(self):
        # NOP; MOV [BW+10h],imm16, pE, 1 wait: the d8 due on fetch 76's last clock 79 is
        # taken at its delivery 80, the write a clock after the take plus the group setup:
        # F76 W84 (either: W83; dadd 0: W83)
        m, s = _events27("F21-none-n1-sti-bw_d8-pE-w1", 3)
        self.assertEqual(m, s)
        self.assertEqual(s, [(72, "fetch"), (76, "fetch"), (84, "data_write")])
        for kw in ({"sync_req": "either"}, {"store_imm.dadd": 0}):
            m, _ = _events27("F21-none-n1-sti-bw_d8-pE-w1", 3, **kw)
            self.assertEqual(m[2], (83, "data_write"), kw)

    def test_wp27_defaults_are_the_old_model(self):
        self.assertEqual(DEFAULT.c("store_imm", "dadd"), 0)
        for name in ("disp16", "ea_disp16", "ea_direct"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


# (WP28) the nineteenth fit's displacement-take rules over the eighteenth fit
WP28 = {"ir_load": "disp_data", "late_disp": "all", "disp_floor": "take", "latch_disp": True,
        **{f"{c}.dfloor": 2 for c in ("load", "load_alu", "store", "store_imm", "rmw",
                                      "rmw_imm", "push_mem", "pop_mem")}}
_EIGHTEENTH: list = []


def _events28(cid, n=4, **kw):
    """(model, silicon) (clock, kind) lists from the fill, the fill fetch dropped, under the
    eighteenth fit (fit-wp27-hand.json) + WP28 (+ kw)."""
    import json
    from pathlib import Path

    if not _EIGHTEENTH:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp27-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _EIGHTEENTH.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS27:
        _RUNS27[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS27[family][cid])
    m = simulate_normalized(s.chain, _EIGHTEENTH[0].replace(**{**WP28, **kw}), s.chain_base)
    return ([(e[0], e[1]) for e in aligned(m)][1:n + 1],
            [(e[0], e[1]) for e in aligned(s)][1:n + 1])


class DisplacementTake(unittest.TestCase):
    """WP28 (F21 re-read, no new data), each rule against the alternative it replaced;
    silicon clocks from the fill quoted from the corpus (chains-F21-w0..w2)."""

    def test_ir_held_until_the_data_cycle(self):
        # MOV AW,[BW+200h], marker-less, pO, 0 waits: the d16 taken at 75 with 5 bytes
        # queued and no fetch in flight: F75 R78 F81 F87 (take: the IR loads at 75, the
        # request stays raised through fetch 75 and its back-to-back fetch beats the read:
        # F75 F78 R81 F89)
        m, s = _events28("F21-none-l0-ld-bw_d16-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s, [(75, "fetch"), (78, "data_read"), (81, "fetch"), (87, "fetch")])
        m, _ = _events28("F21-none-l0-ld-bw_d16-pO-w0", 4, ir_load="take")
        self.assertEqual(m, [(75, "fetch"), (78, "fetch"), (81, "data_read"), (89, "fetch")])
        # the control: PUSH; MOV AW,[BW+200h], pE, the d16 taken on fetch 81's delivery
        # clock 84 with the same bytes left: the back-to-back fetch first, F84 F87 R90
        # (exact under both: the hold is not taken on a delivery clock)
        for irl in ("disp_data", "take"):
            m, s = _events28("F21-push-l0-ld-bw_d16-pE-w0", 4, ir_load=irl)
            self.assertEqual(m, s, irl)
        self.assertEqual(s[1:], [(81, "fetch"), (84, "fetch"), (87, "fetch")])

    def test_late_take_for_every_displacement(self):
        # NOP; MOV AW,[BW+10h], pO, 1 wait: the d8 due on fetch 76's last clock 79 is taken
        # on its delivery 80: F76 F80 R84 (imm: taken at 79, F76 R81 F85)
        m, s = _events28("F21-none-n1-ld-bw_d8-pO-w1", 3)
        self.assertEqual(m, s)
        self.assertEqual(s, [(76, "fetch"), (80, "fetch"), (84, "data_read")])
        m, _ = _events28("F21-none-n1-ld-bw_d8-pO-w1", 3, late_disp="imm")
        self.assertEqual(m, [(76, "fetch"), (81, "data_read"), (85, "fetch")])

    def test_data_cycle_two_clocks_after_the_displacement(self):
        # ES: NOP; MOV AW,[BW+10h], pE, 1 wait: 6 bytes queued at the d8's take (83), no
        # fetch before the read: F72 F76 R85 F89 (disp_floor none: R84 F88; dfloor 1 and 3
        # as none and R86)
        m, s = _events28("F21-none-es-ld-bw_d8-pE-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s, [(72, "fetch"), (76, "fetch"), (85, "data_read"), (89, "fetch")])
        m, _ = _events28("F21-none-es-ld-bw_d8-pE-w1", 4, disp_floor="none")
        self.assertEqual(m[2:], [(84, "data_read"), (88, "fetch")])
        for n, r in ((1, 84), (3, 86)):
            m, _ = _events28("F21-none-es-ld-bw_d8-pE-w1", 4, **{"load.dfloor": n})
            self.assertEqual(m[2], (r, "data_read"), n)

    def test_latched_byte_counted_on_the_displacement_take(self):
        # NOP; MOV AW,[BW+10h], pE, 1 wait: the d8 taken on fetch 76's delivery clock 80
        # with 5 bytes stored after it, one of them the latched byte: no fetch, F72 F76 R82
        # F91 (False: the latched byte uncounted, F80 R84)
        m, s = _events28("F21-none-n1-ld-bw_d8-pE-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s, [(72, "fetch"), (76, "fetch"), (82, "data_read"), (91, "fetch")])
        m, _ = _events28("F21-none-n1-ld-bw_d8-pE-w1", 4, latch_disp=False)
        self.assertEqual(m[2:], [(80, "fetch"), (84, "data_read")])

    def test_wp28_defaults_are_the_old_model(self):
        for name in ("ir_load", "late_disp", "disp_floor", "latch_disp"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        for c in ("load", "store", "rmw"):
            self.assertEqual(DEFAULT.c(c, "dfloor"), 0, c)


WP29 = {"free_hold": "delivery", "free_idle": True, "io_older": "io_modrm",
        "disp_floor": "posted", "ea_floor": True}


def _events29(cid, n=4, **kw):
    """_events28 under WP28 + WP29 (+ kw): the twentieth fit's rules."""
    return _events28(cid, n, **{**WP29, **kw})


class FreeClocksAndFloors(unittest.TestCase):
    """WP29 (item 10 a-c re-read, no new data), each rule against the alternative it replaced;
    silicon clocks from the fill quoted from the corpus (chains-F21, F19, F5)."""

    def test_delivery_fetch_held_at_the_free_clocks_eve(self):
        # MOV [BW+200h],imm16, marker-less, pO, 0 waits: the write posted at 76 (grp 3, the last
        # fetch-free) is at count 2 when fetch 75 delivers at 78: no fetch there, W79 F82
        # (none: hold_count=ahead lets it go, F78 W81)
        m, s = _events29("F21-none-l0-sti-bw_d16-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s, [(75, "fetch"), (79, "data_write"), (82, "fetch"), (85, "fetch")])
        m, _ = _events29("F21-none-l0-sti-bw_d16-pO-w0", 4, free_hold="none")
        self.assertEqual(m[1:3], [(78, "fetch"), (81, "data_write")])
        # the 1-wait twin: the delivery clock 79 is the write's last setup clock (issuable):
        # the fetch requested there goes first under both, F79 W83
        for fh in ("delivery", "none"):
            m, s = _events29("F21-none-l0-sti-bw_d16-pO-w1", 4, free_hold=fh)
            self.assertEqual(m, s, fh)
        self.assertEqual(s[:3], [(75, "fetch"), (79, "fetch"), (83, "data_write")])

    def test_held_fetch_runs_next_and_counts_through(self):
        # MOV [BW],imm16 ; PUSH, pO, 0 waits: PUSH at count 4 of 7 when fetch 95 delivers at
        # 98 (3 bytes, nothing outstanding): F95 F99 w102 (none: F95 F98 w103)
        m, s = _events29("F19-i-push-n1-stimm-pO-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(95, "fetch"), (99, "fetch"), (102, "stack_write")])
        m, _ = _events29("F19-i-push-n1-stimm-pO-w0", 6, free_hold="none")
        self.assertEqual(m[4:], [(98, "fetch"), (103, "stack_write")])
        # POP [BW+10h] after PUSH, pE: its stack read at count 4 of 7 on fetch 81's delivery
        # 84: F81 r87 F93 W96 (none: F84 r89 W97)
        m, s = _events29("F21-push-l0-pop-bw_d8-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(81, "fetch"), (87, "stack_read"), (93, "fetch"),
                                 (96, "data_write")])
        m, _ = _events29("F21-push-l0-pop-bw_d8-pE-w0", 5, free_hold="none")
        self.assertEqual(m[2:4], [(84, "fetch"), (89, "stack_read")])
        # the OUT frame, pE, 3 bytes at the hold: the held fetch beats the write issuable at
        # 91, F91 W94 (none: F90 W93)
        m, s = _events29("F21-out-l0-sti-bw_d16-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[3:5], [(91, "fetch"), (94, "data_write")])
        m, _ = _events29("F21-out-l0-sti-bw_d16-pE-w0", 6, free_hold="none")
        self.assertEqual(m[3:5], [(90, "fetch"), (93, "data_write")])

    def test_run_fetch_leaves_an_idle_clock(self):
        # PUSH ; MOV [BW+200h],imm16, pE, 0 waits: fetches 81, 84 (the d16 taken on 81's
        # delivery) and 87 on 84's delivery, a run, with the write at count 2: the fetch runs
        # (not held) and the write comes a clock after it ends, W91 (False: W90)
        m, s = _events29("F21-push-l0-sti-bw_d16-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[1:], [(81, "fetch"), (84, "fetch"), (87, "fetch"),
                                 (91, "data_write"), (94, "fetch")])
        m, _ = _events29("F21-push-l0-sti-bw_d16-pE-w0", 6, free_idle=False)
        self.assertEqual(m[4], (90, "data_write"))

    def test_io_form_waits_out_an_older_fetch(self):
        # MOV [BW],imm16 ; OUT, pO, 0 waits: the OUT due at 96 beside fetch 96 (held by the
        # busy latch) with 2 bytes stored: it waits the fetch out, I109 (False: I106); pE,
        # 3 stored, it starts beside fetch 95: I105 either way
        m, s = _events29("F19-i-out-l0-stimm-pO-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(96, "fetch"), (99, "fetch"), (102, "fetch"), (109, "io_write")])
        m, _ = _events29("F19-i-out-l0-stimm-pO-w0", 7, io_older=False)
        self.assertEqual(m[6], (106, "io_write"))
        for io in ("io_modrm", False):
            m, s = _events29("F19-i-out-l0-stimm-pE-w0", 7, io_older=io)
            self.assertEqual(m, s, io)
        # 1 wait, no latch wait: the OUT starts at 97 beside fetch 97 requested at 95: I113
        # (False: I110)
        m, s = _events29("F21-out-l0-sti-bw-pO-w1", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[6], (113, "io_write"))
        m, _ = _events29("F21-out-l0-sti-bw-pO-w1", 7, io_older=False)
        self.assertEqual(m[6], (110, "io_write"))
        # a ModR/M form: the second MOV [BW+200h],imm16 beside fetch 104 with 2 stored, W108
        # (io: W107)
        m, s = _events29("F21-out-l0-sti-bw_d16-k2-pO-w0", 9)
        self.assertEqual(m, s)
        self.assertEqual(s[7:], [(104, "fetch"), (108, "data_write")])
        m, _ = _events29("F21-out-l0-sti-bw_d16-k2-pO-w0", 9, io_older="io")
        self.assertEqual(m[8], (107, "data_write"))

    def test_pop_write_floored_at_its_displacement(self):
        # NOP ; POP [BW+IX+200h], pE, 1 wait: the d16 taken at 90 (the extra EA clock first),
        # the write posted at the stack data: W92 F96, two clocks after the take (take: the
        # write issuable at 91, the request the take raised goes first, F91 W95); the d16
        # twin, taken at 89, W91 F95
        m, s = _events29("F21-none-n1-pop-bw_ix_d16-pE-w1", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:], [(82, "stack_read"), (92, "data_write"), (96, "fetch")])
        m, _ = _events29("F21-none-n1-pop-bw_ix_d16-pE-w1", 5, disp_floor="take")
        self.assertEqual(m[3:], [(91, "fetch"), (95, "data_write")])
        m, s = _events29("F21-none-n1-pop-bw_d16-pE-w1", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:], [(91, "data_write"), (95, "fetch")])

    def test_mod00_floor_from_the_address_step(self):
        # ES: NOP ; MOV AW,[BW], pE, 0 waits: X starts at 79 with 7 bytes stored (one
        # latched), no room, no aborted cycle, no fetch: R84 = s + 5 (False: R82 = s + 3);
        # the pO twin with 6 stored aborts and reads at 83 = s + 5
        m, s = _events29("F21-none-es-ld-bw-pE-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s, [(72, "fetch"), (75, "fetch"), (84, "data_read"), (92, "fetch")])
        m, _ = _events29("F21-none-es-ld-bw-pE-w0", 4, ea_floor=False)
        self.assertEqual(m[2:], [(82, "data_read"), (90, "fetch")])
        for ef in (True, False):
            m, s = _events29("F21-none-es-ld-bw-pO-w0", 4, ea_floor=ef)
            self.assertEqual(m, s, ef)
        self.assertEqual(s[1], (83, "data_read"))

    def test_hold_count_ahead_run_still_exact(self):
        # the run hold_count=ahead was adopted on: the read in I/O recovery at count 0, a
        # fetch requested long before: I/O 84, F87, R91
        m, s = _events29("F5-out-add_m_imm-k1-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:4], [(84, "io_write"), (87, "fetch"), (91, "data_read")])

    def test_wp29_defaults_are_the_old_model(self):
        for name in ("free_hold", "free_idle", "io_older", "disp_floor", "ea_floor"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


WP30 = {"disp_io": "extend", "ea_ir_room": True, "rmw_alu": "through", "imm_start": "wait"}


def _events30(cid, n=4, **kw):
    """_events29 under WP30 (+ kw): the twenty-first fit's rules."""
    return _events29(cid, n, **{**WP30, **kw})


class BaseIndexDisplacement(unittest.TestCase):
    """WP30 (item 10 a-c re-read, no new data), each rule against the alternative it replaced;
    silicon clocks from the fill quoted from the corpus (chains-F21, F4, F14, F15, F17, F5)."""

    def test_take_on_the_io_issue_clock_holds_the_bus_a_clock(self):
        # OUT ; MOV AW,[BW+IX+200h], pE, 1 wait: the d16 taken at 85 (the extra EA clock
        # first), the marker's I/O 85-87: nothing on 88, F89 R93 (none: F88 R92); the d16
        # twin takes at 84, a clock before the issue, and is F88 R92 under both
        m, s = _events30("F21-out-l0-ld-bw_ix_d16-pE-w1", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[1:4], [(85, "io_write"), (89, "fetch"), (93, "data_read")])
        m, _ = _events30("F21-out-l0-ld-bw_ix_d16-pE-w1", 6, disp_io="none")
        self.assertEqual(m[2:4], [(88, "fetch"), (92, "data_read")])
        for di in ("extend", "none"):
            m, s = _events30("F21-out-l0-ld-bw_d16-pE-w1", 6, disp_io=di)
            self.assertEqual(m, s, di)
        self.assertEqual(s[2:4], [(88, "fetch"), (92, "data_read")])
        # pO, 2 waits, the take on fetch 82's delivery = the I/O issue: F91 R96 (none: F90)
        m, s = _events30("F4-out-ld_bw_ix_d16-k1-pO-w2", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:4], [(87, "io_write"), (91, "fetch"), (96, "data_read")])
        m, _ = _events30("F4-out-ld_bw_ix_d16-k1-pO-w2", 5, disp_io="none")
        self.assertEqual(m[2], (90, "fetch"))
        # the immediate store: its write's group setup counts from the held clock, the
        # fetch at the free clocks' eve held: F88 F92 W95 (none: F87 F91 W94)
        m, s = _events30("F21-out-l0-sti-bw_ix_d16-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[2:5], [(88, "fetch"), (92, "fetch"), (95, "data_write")])
        m, _ = _events30("F21-out-l0-sti-bw_ix_d16-pE-w0", 6, disp_io="none")
        self.assertEqual(m[2:5], [(87, "fetch"), (91, "fetch"), (94, "data_write")])

    def test_ir_is_no_room_inside_the_ea_clocks(self):
        # PUSH ; MOV AW,[BW+IX+200h], pE, 0 waits: s = 81, EA clocks 82-84, fetch 81 delivers
        # at 84 inside the third: no fetch there, F85 on the take clock, R88 (False: the empty
        # IR counted, F84 R87)
        m, s = _events30("F21-push-l0-ld-bw_ix_d16-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[1:4], [(81, "fetch"), (85, "fetch"), (88, "data_read")])
        m, _ = _events30("F21-push-l0-ld-bw_ix_d16-pE-w0", 6, ea_ir_room=False)
        self.assertEqual(m[2:4], [(84, "fetch"), (87, "data_read")])
        # OUT n1: F88 F92 R95 (False: F91 R94)
        m, s = _events30("F21-out-n1-ld-bw_ix_d16-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[3:5], [(92, "fetch"), (95, "data_read")])
        m, _ = _events30("F21-out-n1-ld-bw_ix_d16-pE-w0", 6, ea_ir_room=False)
        self.assertEqual(m[3:5], [(91, "fetch"), (94, "data_read")])
        # past its EA clocks (the d8 due on the delivery clock 84) the immediate store still
        # fetches through the IR's slot: F84 W88 under both
        for er in (True, False):
            m, s = _events30("F19-i-push-l0-stimmd8-pO-w0", 6, ea_ir_room=er)
            self.assertEqual(m, s, er)
        self.assertEqual(s[2:4], [(84, "fetch"), (88, "data_write")])

    def test_rmw_alu_clocks_count_through_a_fetch(self):
        # OUT ; ADD [BW+200h],AW, pE, 0 waits: R90, fetch 93-95 on the write's first setup
        # clock: W96 (free: W97); the d8 twin, no fetch, W95 under both
        m, s = _events30("F21-out-l0-add-bw_d16-pE-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[3:6], [(90, "data_read"), (93, "fetch"), (96, "data_write")])
        m, _ = _events30("F21-out-l0-add-bw_d16-pE-w0", 7, rmw_alu="free")
        self.assertEqual(m[5], (97, "data_write"))
        for ra in ("through", "free"):
            m, s = _events30("F21-out-l0-add-bw_d8-pE-w0", 6, rmw_alu=ra)
            self.assertEqual(m, s, ra)
        self.assertEqual(s[3:5], [(90, "data_read"), (95, "data_write")])
        # XCH [0C00h],AW: its dest_route clocks after the fetch, W98 under both
        for ra in ("through", "free"):
            m, s = _events30("F14-t-out-xch_dir_aw-pE-w0", 7, rmw_alu=ra)
            self.assertEqual(m, s, ra)
        self.assertEqual(s[4:6], [(93, "fetch"), (98, "data_write")])
        # refresh on: the refresh still taken on the write's first setup clock, 92, W97
        m, s = _events30("F17-s-n0-rmw-pE-w0", 8)
        self.assertEqual(m, s)
        self.assertEqual(s[5:7], [(92, "refresh"), (97, "data_write")])

    def test_immediate_form_waits_out_the_fetch_its_start_raises(self):
        # OUT ; MOV [BW+10h],imm16 x2, pE, 0 waits: the second due at 97 on fetch 94's
        # delivery with 3 stored (one latched): it waits fetch 97 out, W107 (none: W104)
        m, s = _events30("F21-out-l0-sti-bw_d8-k2-pE-w0", 10)
        self.assertEqual(m, s)
        self.assertEqual(s[5:8], [(97, "fetch"), (100, "fetch"), (107, "data_write")])
        m, _ = _events30("F21-out-l0-sti-bw_d8-k2-pE-w0", 10, imm_start="none")
        self.assertEqual(m[7], (104, "data_write"))
        m, s = _events30("F5-out-st_imm_bw-k2-pO-w0", 9)
        self.assertEqual(m, s)
        self.assertEqual(s[6], (108, "data_write"))
        m, _ = _events30("F5-out-st_imm_bw-k2-pO-w0", 9, imm_start="none")
        self.assertEqual(m[6], (105, "data_write"))
        # the direct address (4 operand bytes): W108 under both
        for im in ("wait", "none"):
            m, s = _events30("F21-out-l0-sti-dir-k2-pO-w0", 10, imm_start=im)
            self.assertEqual(m, s, im)
        self.assertEqual(s[8], (108, "data_write"))

    def test_wp30_defaults_are_the_old_model(self):
        for name in ("disp_io", "ea_ir_room", "rmw_alu", "imm_start"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


WP31 = {"slot_room": "word", "slot_idle": "eu", "slot_latch": True, "abort_fixed": True,
        "fixed_floor": True, "lookup_start": True, "dest_route": "slot",
        "rmw_imm.sidle": 2, "rmw.sidle": 2, "load_alu.fdisp": 3}


def _events31(cid, n=4, **kw):
    """_events30 under WP31 (+ kw): the twenty-second fit's rules."""
    return _events30(cid, n, **{**WP31, **kw})


class LeftOutWriteAndTest(unittest.TestCase):
    """WP31 (the left-out-write forms and the TEST/CMP reg forms, no new data), each rule
    against the alternative it replaced; silicon clocks from the fill quoted from the corpus
    (chains-F19, F14, F15)."""

    def test_slot_fetch_needs_room_for_a_word(self):
        # PUSH ; CMP [BW],imm8, pE, 0 waits: R87, the slot at 92 with 5 counted and no cycle
        # since the read: no fetch, the PUSH writes at 100 (any: F92 w101)
        m, s = _events31("F19-i-push-l0-cmpimm8-pE-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[3:6], [(87, "data_read"), (100, "stack_write"), (103, "fetch")])
        m, _ = _events31("F19-i-push-l0-cmpimm8-pE-w0", 6, slot_room="any")
        self.assertEqual(m[4:6], [(92, "fetch"), (101, "stack_write")])
        # CMP [BW],imm16 pO: the slot at 94 on fetch 91's delivery, 5 counted with that word,
        # 3 stored before it: F94 under both
        for sr in ("word", "any"):
            m, s = _events31("F19-i-push-l0-cmpimm-pO-w0", 6, slot_room=sr)
            self.assertEqual(m, s, sr)
        self.assertEqual(s[2:6], [(88, "data_read"), (91, "fetch"), (94, "fetch"),
                                  (103, "stack_write")])

    def test_idle_slot_is_no_bus_cycle(self):
        # the slot without a fetch: the PUSH starts 2 clocks after it at every wait; 1 wait:
        # slot 96, w104 (cycle: w106); 2 waits: slot 100, w108 (cycle: w111)
        for w, sw, cw in ((1, 104, 106), (2, 108, 111)):
            cid = f"F19-i-push-l0-cmpimm8-pE-w{w}"
            m, s = _events31(cid, 5)
            self.assertEqual(m, s, cid)
            self.assertEqual(s[4], (sw, "stack_write"))
            m, _ = _events31(cid, 5, slot_idle="cycle")
            self.assertEqual(m[4], (cw, "stack_write"))

    def test_slot_fills_the_data_latch(self):
        # OUT ; CMP [BW],imm16, pE, 0 waits: slot 97 with its 3-clock fetch, the closing
        # OUT at 101 (the latch to slot + 4): I/O 111 (False: 110); at 1 wait the slot's fetch
        # ends past the latch, I/O 114 under both
        m, s = _events31("F19-i-out-l0-cmpimm-pE-w0", 8)
        self.assertEqual(m, s)
        self.assertEqual(s[5:7], [(97, "fetch"), (111, "io_write")])
        m, _ = _events31("F19-i-out-l0-cmpimm-pE-w0", 8, slot_latch=False)
        self.assertEqual(m[6], (110, "io_write"))
        for sl in (True, False):
            m, s = _events31("F19-i-out-l0-cmpimm-pE-w1", 8, slot_latch=sl)
            self.assertEqual(m, s, sl)
        self.assertEqual(s[6], (114, "io_write"))

    def test_test_on_an_aborted_cycle_counts_a_setup_clock(self):
        # marker-less TEST [BW],AW pO: started at 72 on an aborted cycle, R79 (False: R80)
        m, s = _events31("F14-t-none-test_bw_aw-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s[0], (79, "data_read"))
        m, _ = _events31("F14-t-none-test_bw_aw-pO-w0", 3, abort_fixed=False)
        self.assertEqual(m[0], (80, "data_read"))
        # the k = 2 second TEST under PUSH pE on an aborted cycle at 94: R101 (False: R102)
        m, s = _events31("F14-t-push-test_bw_aw-k2-pE-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[4:7], [(101, "data_read"), (104, "fetch"), (113, "stack_write")])
        m, _ = _events31("F14-t-push-test_bw_aw-k2-pE-w0", 7, abort_fixed=False)
        self.assertEqual(m[4], (102, "data_read"))
        # with a fetch on its start clock: R89 under both
        for af in (True, False):
            m, s = _events31("F14-t-push-test_bw_aw-pE-w0", 5, abort_fixed=af)
            self.assertEqual(m, s, af)
        self.assertEqual(s[3], (89, "data_read"))

    def test_test_imm_floor_carries_the_fixed_lookup(self):
        # marker-less TEST [BW],imm16 pO, no fetch in its head: R81 = s + 9 (False: R80); the
        # pE twin with a fetch at its start reads at s + 10 under both
        m, s = _events31("F15-a-none-test_bw_imm-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s[0], (81, "data_read"))
        m, _ = _events31("F15-a-none-test_bw_imm-pO-w0", 3, fixed_floor=False)
        self.assertEqual(m[0], (80, "data_read"))
        for ff in (True, False):
            m, s = _events31("F15-a-none-test_bw_imm-pE-w0", 3, fixed_floor=ff)
            self.assertEqual(m, s, ff)
        self.assertEqual(s[:2], [(72, "fetch"), (82, "data_read")])

    def test_cmp_r_m_reg_is_the_rmw_with_its_write_left_out(self):
        # marker-less CMP [BW],AW pO: R77, its left-out write posted at the read data holds
        # the fetch (4 counted): F82 (d0ro_latch: F80)
        m, s = _events31("F14-t-none-cmp_bw_aw-pO-w0", 3)
        self.assertEqual(m, s)
        self.assertEqual(s[:2], [(77, "data_read"), (82, "fetch")])
        m, _ = _events31("F14-t-none-cmp_bw_aw-pO-w0", 3, dest_route="d0ro_latch")
        self.assertEqual(m[1], (80, "fetch"))
        # CMP [0C00h],AW under OUT pE: 3 counted, F93 runs; the slot on fetch 93's delivery
        # carries a fetch where AND writes (W96), the OUT at 100: F96 I110 (d0ro_latch: F102
        # I109)
        m, s = _events31("F15-a-out-cmp_dir_aw-pE-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[4:7], [(93, "fetch"), (96, "fetch"), (110, "io_write")])
        m, _ = _events31("F15-a-out-cmp_dir_aw-pE-w0", 7, dest_route="d0ro_latch")
        self.assertEqual(m[5:7], [(102, "fetch"), (109, "io_write")])
        m, s = _events31("F15-a-out-and_dir_aw-pE-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[5], (96, "data_write"))
        # XCH keeps its route clocks before its write: W98 under both
        for dr in ("slot", "d0ro_latch"):
            m, s = _events31("F14-t-out-xch_dir_aw-pE-w0", 7, dest_route=dr)
            self.assertEqual(m, s, dr)
        self.assertEqual(s[5], (98, "data_write"))

    def test_lookup_costs_a_clock_after_a_start_fetch(self):
        # TEST [0C00h],AW x2 under PUSH pE: the second starts at 95 with no fetch, F100 R103
        # (False with fdisp 4: F101 R104); the pO twin starts beside fetch 95: F101 R104, and
        # False with fdisp 3 breaks it (the first instance too)
        m, s = _events31("F14-t-push-test_dir_aw-k2-pE-w0", 8)
        self.assertEqual(m, s)
        self.assertEqual(s[5:7], [(100, "fetch"), (103, "data_read")])
        m, _ = _events31("F14-t-push-test_dir_aw-k2-pE-w0", 8, lookup_start=False,
                         **{"load_alu.fdisp": 4})
        self.assertEqual(m[5:7], [(101, "fetch"), (104, "data_read")])
        m, s = _events31("F14-t-push-test_dir_aw-k2-pO-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[5:7], [(101, "fetch"), (104, "data_read")])
        m, _ = _events31("F14-t-push-test_dir_aw-k2-pO-w0", 7, lookup_start=False)
        self.assertNotEqual(m, s)

    def test_wp31_defaults_are_the_old_model(self):
        for name in ("slot_room", "slot_idle", "slot_latch", "abort_fixed", "fixed_floor",
                     "lookup_start"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


WP32 = {"io_take_nx": True, "reg.nx": 1, "modrm_port": True, "nop_hold": "any",
        "port_issue": True, "latch_start": True, "abort_latched": "any"}


def _events32(cid, n=4, **kw):
    """_events31 under WP32 (+ kw): the twenty-third fit's rules."""
    return _events31(cid, n, **{**WP32, **kw})


class RegisterFormLeadsAndPortTake(unittest.TestCase):
    """WP32 (the leads before a register form, OUT after OUT, MOV CL and SHL AW,CL behind a
    full queue; no new data), each rule against the alternative it replaced; silicon clocks
    from the fill quoted from the corpus (chains-F20, F19, F7, F3, F16, F9)."""

    def test_register_form_take_on_the_io_issue_clock_loads_the_ir_late(self):
        # PUSH ; ES: NOP ; MOV AW,DW ; PUSH, pO, 0 waits: the ModR/M taken at 88 with nothing
        # on the bus, the PUSH starts at 90, w96 (nx 2 without the rule: w97)
        m, s = _events32("F20-r-push-es-none-movr-pO-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:5], [(96, "stack_write"), (99, "fetch")])
        m, _ = _events32("F20-r-push-es-none-movr-pO-w0", 5, io_take_nx=False, **{"reg.nx": 2})
        self.assertEqual(m[3], (97, "stack_write"))
        # OUT ; MOV AW,DW ; OUT DW,AL, pE, 0 waits: the ModR/M on the marker's I/O issue clock
        # 84, OUT DW at 87: F87 F90 I97 (nx 1 without the rule: F90 I93)
        m, s = _events32("F19-d-out-movawdw-outb-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[1:5], [(84, "io_write"), (87, "fetch"), (90, "fetch"),
                                  (97, "io_write")])
        m, _ = _events32("F19-d-out-movawdw-outb-pE-w0", 5, io_take_nx=False)
        self.assertEqual(m[2:4], [(90, "fetch"), (93, "io_write")])

    def test_modrm_commit_frees_the_port_for_an_older_latched_byte(self):
        # PUSH ; ES: NOP ; MOV AW,DW ; MOV AW,[BW], pO, 0 waits: the byte latched at 87 behind
        # a full queue goes in on the ModR/M take at 88; the load at 90 fetches: F90 R95
        # (False: latch_hold holds it, F91 R96)
        m, s = _events32("F20-r-push-es-movawdw-ld-pO-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[3:5], [(90, "fetch"), (95, "data_read")])
        m, _ = _events32("F20-r-push-es-movawdw-ld-pO-w0", 5, modrm_port=False)
        self.assertEqual(m[3:5], [(91, "fetch"), (96, "data_read")])

    def test_nop_start_holds_the_reissued_request_to_the_next_start(self):
        # OUT ; MOV AW,DW ; NOP ; OUT DW,AL, pE, 0 waits: NOP at 87 on fetch 87's issue clock;
        # the fetch waits for the DW form's start at 91: F87 F91 I100 (none: F87 F90 I101)
        m, s = _events32("F19-d-out-movawdw_nop-outb-pE-w0", 5)
        self.assertEqual(m, s)
        self.assertEqual(s[2:5], [(87, "fetch"), (91, "fetch"), (100, "io_write")])
        m, _ = _events32("F19-d-out-movawdw_nop-outb-pE-w0", 5, nop_hold="none")
        self.assertEqual(m[2:5], [(87, "fetch"), (90, "fetch"), (101, "io_write")])
        # 1 wait: the back-to-back clock 92 is the next start: F88 F92 under every option
        for nh in ("none", "io", "any"):
            m, s = _events32("F19-d-out-movawdw_nop-outb-pE-w1", 5, nop_hold=nh)
            self.assertEqual(m, s, nh)
        self.assertEqual(s[2:4], [(88, "fetch"), (92, "fetch")])

    def test_port_take_on_a_fetch_issue_clock_lands_late(self):
        # OUT ; OUT imm8,AL ; OUT imm8,AL, pO, 0 waits: the second OUT's port byte at 94 on
        # fetch 94's issue clock: the first OUT's I/O at 98 (False: 97)
        m, s = _events32("F7-out-out_imm_al-out_imm_al-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[2:4], [(94, "fetch"), (98, "io_write")])
        m, _ = _events32("F7-out-out_imm_al-out_imm_al-pO-w0", 4, port_issue=False)
        self.assertEqual(m[3], (97, "io_write"))
        # 1 wait: the count through fetch 94's wait state ends at 98 under both
        for pi in (True, False):
            m, s = _events32("F7-out-out_imm_al-out_imm_al-pO-w1", 4, port_issue=pi)
            self.assertEqual(m, s, pi)
        self.assertEqual(s[3], (98, "io_write"))

    def test_start_on_the_latched_bytes_entry_clock_runs_a_clock_late(self):
        # PUSH ; MOV CL,4 x4, pO, 0 waits: the fourth MOV CL starts at 97 as the byte latched
        # behind a full queue at 93 goes in: its take and fetch at 101 (False: 100)
        m, s = _events32("F3-push-mov_cl_imm-k4-pO-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[3:6], [(90, "fetch"), (101, "fetch"), (104, "fetch")])
        m, _ = _events32("F3-push-mov_cl_imm-k4-pO-w0", 6, latch_start=False)
        self.assertEqual(m[4], (100, "fetch"))
        # NOP NOP ; MOV CL,4 ; (LS) MOV CL,31, pE, 1 wait: F88 (False: F87)
        m, s = _events32("F16-s-none-n2-movcl-pE-w1", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[2], (88, "fetch"))
        m, _ = _events32("F16-s-none-n2-movcl-pE-w1", 4, latch_start=False)
        self.assertEqual(m[2], (87, "fetch"))
        # NOP NOP ; (LS) MOV CL,31 ; SHL AW,CL: the shift takes its ModR/M on its start
        # clock, the byte stays latched: F85 under both
        for ls in (True, False):
            m, s = _events32("F9-none-nop2-pE-w1", 4, latch_start=ls)
            self.assertEqual(m, s, ls)
        self.assertEqual(s[2], (85, "fetch"))

    def test_abort_test_does_not_count_a_byte_still_latched(self):
        # MOV CL,4 ; NOP ; SHL AW,CL, marker-less, pO, 0 waits: the shift starts at 82 with
        # one word of room but the latched byte: an aborted cycle, the closing MOV CL's fetch
        # at 105 (False: 103); the pE twin, nothing latched, F100 under both
        m, s = _events32("F16-s-none-cl4-n1-shlcl-pO-w0", 4)
        self.assertEqual(m, s)
        self.assertEqual(s[2:4], [(105, "fetch"), (108, "fetch")])
        m, _ = _events32("F16-s-none-cl4-n1-shlcl-pO-w0", 4, abort_latched=False)
        self.assertEqual(m[2], (103, "fetch"))
        for al in ("any", "full", False):
            m, s = _events32("F16-s-none-cl4-n1-shlcl-pE-w0", 4, abort_latched=al)
            self.assertEqual(m, s, al)
        self.assertEqual(s[2], (100, "fetch"))

    def test_wp32_defaults_are_the_old_model(self):
        for name in ("io_take_nx", "modrm_port", "nop_hold", "port_issue", "latch_start",
                     "abort_latched"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


WP33 = {"abort_reg_end": "early", "ea_b2b": True, "free_idle_b2b": True, "grp_io_hold": True}


def _events33(cid, n=4, **kw):
    """_events32 under WP33 (+ kw): the twenty-fourth fit's rules."""
    return _events32(cid, n, **{**WP33, **kw})


class AbortEndEaB2bAndGroupHold(unittest.TestCase):
    """WP33 (NOP NOP ; MULU AW, the second base+index+d16 store, TEST [0C00h],AW under OUT at
    pO; no new data), each rule against the alternative it replaced; silicon clocks from the
    fill quoted from the corpus (chains-F16, F3, F21, F14)."""

    def test_aborted_start_multiply_ends_with_its_early_exec(self):
        # PUSH ; NOP NOP ; MULU AW ; PUSH, pO, 1 wait: the MULU starts at 90 on an aborted
        # cycle, no retry fetch; the PUSH writes at 129 (keep: w130)
        m, s = _events33("F16-l-push-nop2_mulu_aw-pO-w1", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[3], (129, "stack_write"))
        m, _ = _events33("F16-l-push-nop2_mulu_aw-pO-w1", 6, abort_reg_end="keep")
        self.assertEqual(m[3], (130, "stack_write"))
        # under OUT, pO, 0 waits: the retry fetch 124-126 ends on the early end: F136 I139
        # (keep: F137 I140)
        m, s = _events33("F16-l-out-nop2_mulu_aw-pO-w0", 7)
        self.assertEqual(m, s)
        self.assertEqual(s[3:6], [(124, "fetch"), (136, "fetch"), (139, "io_write")])
        m, _ = _events33("F16-l-out-nop2_mulu_aw-pO-w0", 7, abort_reg_end="keep")
        self.assertEqual(m[4:6], [(137, "fetch"), (140, "io_write")])
        # MULU DW x2 under PUSH, pE, 0 waits (abort_reg's own run): the retry fetch 147 is in
        # flight on the early end and holds the PUSH: F147 w156 under both
        for e in ("keep", "early"):
            m, s = _events33("F3-push-mulu_dw-k2-pE-w0", 7, abort_reg_end=e)
            self.assertEqual(m, s, e)
        self.assertEqual(s[3:5], [(147, "fetch"), (156, "stack_write")])

    def test_no_back_to_back_fetch_inside_the_ea_clocks(self):
        # OUT ; MOV [BW+IX+200h],AW x2, pE, 0 waits: the second starts at 94 beside fetch 94
        # with 2 stored; its last clock 96 sees room for a word: silicon F98 (the take clock)
        # F101 W104 (False: F97 F100 W103)
        m, s = _events33("F21-out-l0-st-bw_ix_d16-k2-pE-w0", 9)
        self.assertEqual(m, s)
        self.assertEqual(s[4:8], [(94, "fetch"), (98, "fetch"), (101, "fetch"),
                                  (104, "data_write")])
        m, _ = _events33("F21-out-l0-st-bw_ix_d16-k2-pE-w0", 9, ea_b2b=False)
        self.assertEqual(m[5:8], [(97, "fetch"), (100, "fetch"), (103, "data_write")])
        # 1 wait: the back-to-back clock is the take clock, F97 F101 under both
        for eb in (True, False):
            m, s = _events33("F21-out-l0-st-bw_ix_d16-k2-pE-w1", 9, ea_b2b=eb)
            self.assertEqual(m, s, eb)
        self.assertEqual(s[4:6], [(97, "fetch"), (101, "fetch")])

    def test_back_to_back_fetch_at_the_eve_leaves_an_idle_clock(self):
        # OUT ; MOV [BW+IX+200h],imm16 x2, pE, 0 waits: the second takes its d16 at 102 with
        # fetch 102, fetch 105 back to back on the write's eve: silicon W109 (False: W108)
        m, s = _events33("F21-out-l0-sti-bw_ix_d16-k2-pE-w0", 10)
        self.assertEqual(m, s)
        self.assertEqual(s[6:9], [(102, "fetch"), (105, "fetch"), (109, "data_write")])
        m, _ = _events33("F21-out-l0-sti-bw_ix_d16-k2-pE-w0", 10, free_idle_b2b=False)
        self.assertEqual(m[8], (108, "data_write"))
        # PUSH frame, pO: F99 W103 (False: W102)
        m, s = _events33("F21-push-l0-sti-bw_ix_d16-k2-pO-w0", 9)
        self.assertEqual(m, s)
        self.assertEqual(s[6:8], [(99, "fetch"), (103, "data_write")])
        m, _ = _events33("F21-push-l0-sti-bw_ix_d16-k2-pO-w0", 9, free_idle_b2b=False)
        self.assertEqual(m[7], (102, "data_write"))

    def test_group_clock_in_io_recovery_holds_a_younger_fetch(self):
        # OUT ; TEST [0C00h],AW, pO, 0 waits: the displacement taken at 85 on the marker I/O's
        # issue clock and fetch 82's delivery; the read's group clock waits out the recovery:
        # silicon F91 R94 F97 (False: F89 F92 R95)
        m, s = _events33("F14-t-out-test_dir_aw-pO-w0", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[1:5], [(85, "io_write"), (91, "fetch"), (94, "data_read"),
                                  (97, "fetch")])
        m, _ = _events33("F14-t-out-test_dir_aw-pO-w0", 6, grp_io_hold=False)
        self.assertEqual(m[2:5], [(89, "fetch"), (92, "fetch"), (95, "data_read")])
        # 2 waits: I87, F93 R98
        m, s = _events33("F14-t-out-test_dir_aw-pO-w2", 6)
        self.assertEqual(m, s)
        self.assertEqual(s[1:4], [(87, "io_write"), (93, "fetch"), (98, "data_read")])
        # SHL [BW],CL under OUT, pE: the fetch requested before the I/O runs at 87 under both;
        # the pE TEST twin posts its read after the recovery: F87 F90 R93 under both
        for cid in ("F14-g-out-shl_bw_cl-pE-w0", "F14-t-out-test_dir_aw-pE-w0"):
            for gh in (True, False):
                m, s = _events33(cid, 6, grp_io_hold=gh)
                self.assertEqual(m, s, (cid, gh))
            self.assertEqual(s[2], (87, "fetch"))

    def test_wp33_defaults_are_the_old_model(self):
        for name in ("abort_reg_end", "ea_b2b", "free_idle_b2b", "grp_io_hold"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


_WP33HAND = []


def _events34(cid, **kw):
    """(clock, kind) from the fill of a recorded refresh-on run under the twenty-fourth hand
    fit (fit-wp33-hand.json) with the WP34 rules (+ kw), the fill fetch dropped, and the
    silicon list the same way."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _WP33HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp33-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP33HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    m = simulate_normalized(s.chain, _WP33HAND[0].replace(**{**WP34, **kw}), s.chain_base,
                            refresh=refresh_anchor(s))
    return [(e[0], e[1]) for e in aligned(m)][1:], [(e[0], e[1]) for e in aligned(s)][1:]


WP34 = {"refresh_halt": "status", "refresh_lead": "closed", "refresh_sync": "run",
        "halt_refresh": "run_drop", "refresh_disp": "free"}


class RefreshHaltAndBeatenSync(unittest.TestCase):
    """WP34 (finding 8 c and h, no new data): a refresh request in the END block's HALT, the
    take sync on a fetch a refresh beat, the displacement's address phase under a refresh;
    each rule against the alternative it replaced on a named run, silicon clocks from t_fill
    quoted from chains-F13-w<N> and chains-F17-w<N> (H: the model's HALT start)."""

    def test_halt_status_holds_two_clocks_and_follows_a_refresh(self):
        # refresh_halt=status: F13-s-shlcl2-pO-w0, HALT at 223, the request at 224 (H+1)
        # served at 225, the I/O at 230 (none: R224); F13-s-shlcl9-pO-w0, the request at 240
        # (H) served there, the status after it: I/O at 248 (none: 247)
        m, s = _events34("F13-s-shlcl2-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(s[-2:], [(225, "refresh"), (230, "io_write")])
        m, _ = _events34("F13-s-shlcl2-pO-w0", refresh_halt="none")
        self.assertEqual(m[-2], (224, "refresh"))
        m, s = _events34("F13-s-shlcl9-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(s[-2:], [(240, "refresh"), (248, "io_write")])
        m, _ = _events34("F13-s-shlcl9-pO-w0", refresh_halt="none")
        self.assertEqual(m[-1], (247, "io_write"))

    def test_no_refresh_in_the_ios_lead(self):
        # refresh_lead=closed: F13-s-shlcl7-pO-w0, HALT at 236, the OUT's I/O due at 241 (its
        # lead 239, 240): the request at 240 goes at 241 ahead of the I/O, I/O 246 (open:
        # R240 I245)
        m, s = _events34("F13-s-shlcl7-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(s[-2:], [(241, "refresh"), (246, "io_write")])
        m, _ = _events34("F13-s-shlcl7-pO-w0", refresh_lead="open")
        self.assertEqual(m[-2:], [(240, "refresh"), (245, "io_write")])

    def test_beaten_synced_fetch_runs_two_clocks_early_for_the_eu(self):
        # refresh_sync=run: F17-s-n0-shlcl1-pO-w0, the END's MOV DW takes its latched byte at
        # 207 with the refresh 207-211, its fetch 212 and 215 back to back: OUT at 213, HALT
        # 216, I/O 221 (wait: OUT 215, HALT 218, the refresh at 223 first, I/O 228)
        m, s = _events34("F17-s-n0-shlcl1-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(s[-4:], [(207, "refresh"), (212, "fetch"), (215, "fetch"),
                                  (221, "io_write")])
        m, _ = _events34("F17-s-n0-shlcl1-pO-w0", refresh_sync="wait")
        self.assertEqual(m[-2:], [(223, "refresh"), (228, "io_write")])

    def test_a_fetch_beaten_in_halt_is_dropped(self):
        # halt_refresh=run_drop: F13-s-shlcl7-pE-w2, HALT at 253 while fetch 250-254 runs and
        # commits a fetch back to back, the refresh at 255 beats it: silicon R255 I260 (run:
        # F260 I265)
        m, s = _events34("F13-s-shlcl7-pE-w2")
        self.assertEqual(m, s)
        self.assertEqual(s[-2:], [(255, "refresh"), (260, "io_write")])
        m, _ = _events34("F13-s-shlcl7-pE-w2", halt_refresh="run")
        self.assertEqual(m[-2:], [(260, "fetch"), (265, "io_write")])

    def test_displacement_address_phase_runs_through_a_refresh(self):
        # refresh_disp=free: F17-p-n1-shlcl31-pO-w1, the RFMON store takes its displacement
        # at 96 with the refresh 96-100: the SFR write at 101 (no pins), the next fetch 104
        # (hold: 106)
        m, s = _events34("F17-p-n1-shlcl31-pO-w1")
        self.assertEqual(m, s)
        self.assertIn((104, "fetch"), s)
        m, _ = _events34("F17-p-n1-shlcl31-pO-w1", refresh_disp="hold")
        self.assertIn((106, "fetch"), m)
        self.assertNotIn((104, "fetch"), m)

    def test_wp34_defaults_are_the_old_model(self):
        for name in ("refresh_halt", "refresh_lead", "refresh_sync", "refresh_disp"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        self.assertEqual(OPTIONS["halt_refresh"][:2], ("none", "run"))


_WP34HAND = []


def _events35(cid, **kw):
    """(clock, kind) from the fill of a recorded refresh-on run under the twenty-fifth hand
    fit (fit-wp34-hand.json) with the WP35 rules (+ kw), the fill fetch dropped, and the
    silicon list the same way."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _WP34HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp34-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP34HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    m = simulate_normalized(s.chain, _WP34HAND[0].replace(**{**WP35, **kw}), s.chain_base,
                            refresh=refresh_anchor(s))
    return [(e[0], e[1]) for e in aligned(m)][1:], [(e[0], e[1]) for e in aligned(s)][1:]


WP35 = {"dw_view": "eu", "refresh_lost": "start", "refresh_eve": "hold"}


class RefreshEarlyCountLostRequestAndEve(unittest.TestCase):
    """WP35 (finding 8 b, c, d, g, no new data): the END's I/O count beside the EU's early
    fetch run, the way back of a request lost to a refresh, the shift's loop eve; each rule
    against the alternative it replaced on a named run, silicon clocks from t_fill quoted
    from chains-F13-w<N> and chains-F17-w<N>."""

    def test_the_io_count_sees_the_early_run_as_the_eu_does(self):
        # dw_view=eu: F17-s-n2-out-pE-w0, the END's OUT posted at 212 in the early run
        # 211 214 217 (HALT 215): silicon R220 I225 (bus: R221 I226); w1: R228 I233 (bus:
        # R229 I234)
        for cid, ok, bus in (("F17-s-n2-out-pE-w0", [(220, "refresh"), (225, "io_write")],
                              [(221, "refresh"), (226, "io_write")]),
                             ("F17-s-n2-out-pE-w1", [(228, "refresh"), (233, "io_write")],
                              [(229, "refresh"), (234, "io_write")])):
            m, s = _events35(cid)
            self.assertEqual(m, s, cid)
            self.assertEqual(s[-2:], ok, cid)
            m, _ = _events35(cid, dw_view="bus")
            self.assertEqual(m[-2:], bus, cid)

    def test_a_lost_request_comes_back_on_the_next_start(self):
        # refresh_lost=start: F13-s-shlcl4-pO-w0, the request the END's OUT raised at 226 is
        # lost to the refresh 226-230, HALT 231: silicon F233 I236 (queue: no fetch, I236);
        # F13-s-shlcl1-pO-w1 R225 F232 I236 (queue: I235)
        m, s = _events35("F13-s-shlcl4-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(s[-3:], [(226, "refresh"), (233, "fetch"), (236, "io_write")])
        m, _ = _events35("F13-s-shlcl4-pO-w0", refresh_lost="queue")
        self.assertEqual(m[-2:], [(226, "refresh"), (236, "io_write")])
        m, s = _events35("F13-s-shlcl1-pO-w1")
        self.assertEqual(m, s)
        self.assertEqual(s[-3:], [(225, "refresh"), (232, "fetch"), (236, "io_write")])
        m, _ = _events35("F13-s-shlcl1-pO-w1", refresh_lost="queue")
        self.assertEqual(m[-2:], [(225, "refresh"), (235, "io_write")])

    def test_a_request_pending_at_the_eve_waits_for_the_loop(self):
        # refresh_eve=hold: F17-s-n0-shlcl2-pE-w0, the closing LS's shift (exec 120-125), the
        # request at 124 (the eve): silicon R126, I/O 226 (both: R124, I/O 225)
        m, s = _events35("F17-s-n0-shlcl2-pE-w0")
        self.assertEqual(m, s)
        self.assertIn((126, "refresh"), s)
        self.assertEqual(s[-1], (226, "io_write"))
        m, _ = _events35("F17-s-n0-shlcl2-pE-w0", refresh_eve="both")
        self.assertIn((124, "refresh"), m)
        self.assertEqual(m[-1], (225, "io_write"))

    def test_refresh_off_runs_never_see_the_wp35_rules(self):
        # the three rules act only with refresh on: a refresh-off E twin is identical
        a, s = _events35("F17-e-n0-shlcl1-pO-w0")
        b, _ = _events35("F17-e-n0-shlcl1-pO-w0", dw_view="bus", refresh_lost="queue",
                         refresh_eve="both")
        self.assertEqual(a, s)
        self.assertEqual(a, b)

    def test_wp35_defaults_are_the_old_model(self):
        for name in ("dw_view", "refresh_lost", "refresh_eve"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


_WP35HAND = []


def _events36(cid, **kw):
    """(clock, kind) from the fill of a recorded refresh-on run under the twenty-sixth hand
    fit (fit-wp35-hand.json) with the WP36 rules (+ kw), the fill fetch dropped, and the
    silicon list the same way."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _WP35HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp35-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP35HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    m = simulate_normalized(s.chain, _WP35HAND[0].replace(**{**WP36, **kw}), s.chain_base,
                            refresh=refresh_anchor(s))
    return [(e[0], e[1]) for e in aligned(m)][1:], [(e[0], e[1]) for e in aligned(s)][1:]


WP36 = {"refresh_take0": "none", "refresh_mul_exit": "exit", "mul.rexit": 8, "div.rexit": 6,
        "refresh_retry": "end", "shift_exit0": "exit", "refresh_abort": "abort",
        "refresh_lift": "free"}


def _span(ev, lo, hi):
    return [e for e in ev if lo <= e[0] <= hi]


class RefreshNopEndUnitExitsAndAbort(unittest.TestCase):
    """WP36 (finding 8 b, f, no new data): the NOP's end inside a refresh's window, the
    register multiply's and divide's loop exit, the retry moved with the exec's end, the
    count-less shift's 2-clock exit, the aborted request under a refresh, the I/O lead's first
    free clock; each rule against the alternative it replaced on a named run, silicon clocks
    from t_fill quoted from chains-F8-w<N>, chains-F13-w<N>, chains-F17-w<N>, chains-F18-w<N>."""

    def test_a_start_after_a_nop_inside_a_refresh_waits_for_its_end(self):
        # refresh_take0=none: F17-s-n0-nop8-pE-w0, the refresh 92-96 taken on a NOP's start,
        # the next NOP's start on 96 held to 97: silicon F97 F101 R109 F114 F121 (take: F100
        # R108 F113 F116 F119)
        m, s = _events36("F17-s-n0-nop8-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 92, 124), [(92, "refresh"), (97, "fetch"), (101, "fetch"),
                                             (109, "refresh"), (114, "fetch"), (121, "fetch"),
                                             (124, "refresh")])
        m, _ = _events36("F17-s-n0-nop8-pE-w0", refresh_take0="take")
        self.assertEqual(_span(m, 92, 124), [(92, "refresh"), (97, "fetch"), (100, "fetch"),
                                             (108, "refresh"), (113, "fetch"), (116, "fetch"),
                                             (119, "fetch"), (124, "refresh")])
        # the ES: NOP series: F18-b-p-n4-shlcl4-pE-w0 R95 F100 R108 F113 (take: F103 R110)
        m, s = _events36("F18-b-p-n4-shlcl4-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 95, 113), [(95, "refresh"), (100, "fetch"), (108, "refresh"),
                                             (113, "fetch")])
        m, _ = _events36("F18-b-p-n4-shlcl4-pE-w0", refresh_take0="take")
        self.assertEqual(_span(m, 95, 110), [(95, "refresh"), (100, "fetch"), (103, "fetch"),
                                             (110, "refresh")])

    def test_the_multiply_runs_its_last_eight_clocks_as_an_exit(self):
        # refresh_mul_exit=exit: F17-s-n2-mulu-pE-w0, MULU AW's exec from 98, the refresh at
        # 108 held, the request at 124: silicon R126 (none: R125)
        m, s = _events36("F17-s-n2-mulu-pE-w0")
        self.assertEqual(m, s)
        self.assertIn((126, "refresh"), s)
        m, _ = _events36("F17-s-n2-mulu-pE-w0", refresh_mul_exit="none")
        self.assertIn((125, "refresh"), m)
        self.assertNotIn((126, "refresh"), m)
        # the integer is the class's: no exit without it
        m, _ = _events36("F17-s-n2-mulu-pE-w0", **{"mul.rexit": 0})
        self.assertIn((125, "refresh"), m)

    def test_the_retry_moves_with_the_exec_end(self):
        # refresh_retry=end: F18-b-p-n1-mulu-pE-w0, the retry of the request aborted at MULU's
        # start rises mtail before the end the refreshes held in the exec give it: silicon F134
        # (fixed: F132)
        m, s = _events36("F18-b-p-n1-mulu-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 95, 140), [(95, "refresh"), (108, "refresh"),
                                             (125, "refresh"), (134, "fetch"),
                                             (140, "refresh")])
        m, _ = _events36("F18-b-p-n1-mulu-pE-w0", refresh_retry="fixed")
        self.assertIn((132, "fetch"), m)

    def test_the_count_less_shift_lacks_a_clock_of_its_exit(self):
        # shift_exit0=exit: SHL AW,1 (exec0) runs exec 3, loop 2, exit 2; F18-b-n2-shl1-pE-w1
        # R100 F110 R114 (tail: R99 F109 F113); F18-b-n1-shl1-pE-w1 R98 (tail: R100)
        m, s = _events36("F18-b-n2-shl1-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 91, 119), [(91, "fetch"), (100, "refresh"), (110, "fetch"),
                                             (114, "refresh"), (119, "fetch")])
        m, _ = _events36("F18-b-n2-shl1-pE-w1", shift_exit0="tail")
        self.assertEqual(_span(m, 91, 117), [(91, "fetch"), (99, "refresh"), (109, "fetch"),
                                             (113, "fetch"), (117, "refresh")])
        m, s = _events36("F18-b-n1-shl1-pE-w1")
        self.assertEqual(m, s)
        self.assertIn((98, "refresh"), s)
        m, _ = _events36("F18-b-n1-shl1-pE-w1", shift_exit0="tail")
        self.assertIn((100, "refresh"), m)

    def test_a_request_aborted_at_a_unit_start_stays_aborted_under_a_refresh(self):
        # refresh_abort=abort: F18-b-p-n1-mulu-pE-w0, MULU AW starts at 95 with the refresh
        # 95-99 and room for one word: no fetch at 100 (beat: F100 R109 R124);
        # F18-b-n3-shl1-pE-w1 SHL AW,1 the same: silicon R99 F109 (beat: F104)
        m, s = _events36("F18-b-p-n1-mulu-pE-w0", refresh_abort="beat")
        self.assertEqual(_span(m, 95, 125), [(95, "refresh"), (100, "fetch"), (109, "refresh"),
                                             (124, "refresh")])
        self.assertNotIn((100, "fetch"), s)
        m, s = _events36("F18-b-n3-shl1-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 99, 109), [(99, "refresh"), (109, "fetch")])
        m, _ = _events36("F18-b-n3-shl1-pE-w1", refresh_abort="beat")
        self.assertIn((104, "fetch"), m)

    def test_the_io_lead_lets_the_older_fetch_run_on_its_first_free_clock(self):
        # refresh_lift=free: F8-out-nop-k4-pO-w0, the marker's OUT 20h,AL posts its I/O at 95
        # with the fetch raised there, the refresh 98-102 runs into the I/O's lead: silicon
        # F103 I106 (clock: I104 F107)
        m, s = _events36("F8-out-nop-k4-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 98, 106), [(98, "refresh"), (103, "fetch"),
                                             (106, "io_write")])
        m, _ = _events36("F8-out-nop-k4-pO-w0", refresh_lift="clock")
        self.assertEqual(_span(m, 98, 107), [(98, "refresh"), (104, "io_write"),
                                             (107, "fetch")])

    def test_refresh_off_runs_never_see_the_wp36_rules(self):
        # the rules act only with refresh on: a refresh-off E twin is identical
        a, s = _events36("F17-e-n0-shlcl1-pO-w0")
        b, _ = _events36("F17-e-n0-shlcl1-pO-w0", refresh_take0="take",
                         refresh_mul_exit="none", refresh_retry="fixed", shift_exit0="tail",
                         refresh_abort="beat", refresh_lift="clock")
        self.assertEqual(a, s)
        self.assertEqual(a, b)

    def test_wp36_defaults_are_the_old_model(self):
        for name in ("refresh_take0", "refresh_mul_exit", "refresh_retry", "shift_exit0",
                     "refresh_abort", "refresh_lift"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        self.assertEqual(DEFAULT.c("mul", "rexit"), 0)


_WP36HAND = []


def _events37(cid, **kw):
    """(clock, kind) from the fill of a recorded refresh-on run under the twenty-seventh hand
    fit (fit-wp36-hand.json) with the WP37 rules (+ kw), the fill fetch dropped, and the
    silicon list the same way."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _WP36HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp36-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP36HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    m = simulate_normalized(s.chain, _WP36HAND[0].replace(**{**WP37, **kw}), s.chain_base,
                            refresh=refresh_anchor(s))
    return [(e[0], e[1]) for e in aligned(m)][1:], [(e[0], e[1]) for e in aligned(s)][1:]


WP37 = {"refresh_rmw_shape": "shift", "refresh_grpcl": "step", "refresh_abort_retry": "next",
        "refresh_abort_wait": "run", "refresh_wbsync": "seam", "refresh_post": "post",
        "refresh_take_seam": "seam"}


class RefreshMemoryShiftPostAndTakes(unittest.TestCase):
    """WP37 (finding 8, the refresh side's middle, no new data): the memory shift's write
    setup in the register shift's shape, its read setup's CL clocks, the request aborted under
    a refresh, the take sync on an aborted cycle, the write-back sync, a posted request's
    first clock, the clocks between two operand takes; each rule against the alternative it
    replaced on a named run, silicon clocks from t_fill quoted from chains-F8-w<N>,
    chains-F13-w<N>, chains-F18-w<N>."""

    def test_the_memory_shift_write_setup_has_the_register_shift_shape(self):
        # refresh_rmw_shape=shift: F18-b-n2-shlmcl-pE-w0 (SHL [BW],CL, CL = 31, read 106-108):
        # the refresh on the post costs 2, the last one 2 before the issue: silicon R189 W194
        # (even: R188 W195)
        m, s = _events37("F18-b-n2-shlmcl-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 106, 194), [(106, "data_read"), (109, "refresh"),
                                              (124, "refresh"), (141, "refresh"),
                                              (156, "refresh"), (173, "refresh"),
                                              (189, "refresh"), (194, "data_write")])
        m, _ = _events37("F18-b-n2-shlmcl-pE-w0", refresh_rmw_shape="even")
        self.assertEqual(_span(m, 173, 195), [(173, "refresh"), (188, "refresh"),
                                              (195, "data_write")])

    def test_the_memory_shift_read_takes_a_refresh_on_its_cl_clocks(self):
        # refresh_grpcl=step: F18-b-n4-shlmcl-pE-w0, the read posted at 106 (setup 7), the
        # request of 108 taken on the CL clocks' first, 110, the read on the refresh's end + 1
        # (hold: R112 D117)
        m, s = _events37("F18-b-n4-shlmcl-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 101, 115), [(101, "fetch"), (110, "refresh"),
                                              (115, "data_read")])
        m, _ = _events37("F18-b-n4-shlmcl-pE-w0", refresh_grpcl="hold")
        self.assertEqual(_span(m, 101, 117), [(101, "fetch"), (112, "refresh"),
                                              (117, "data_read")])
        # a refresh on the post's own clock costs the read one clock: F18-b-n1-shlmcl-pE-w0
        # R93 D100 (hold: D103)
        m, s = _events37("F18-b-n1-shlmcl-pE-w0")
        self.assertEqual(_span(m, 93, 100), [(93, "refresh"), (100, "data_read")])
        self.assertEqual(_span(s, 93, 100), [(93, "refresh"), (100, "data_read")])
        m, _ = _events37("F18-b-n1-shlmcl-pE-w0", refresh_grpcl="hold")
        self.assertIn((103, "data_read"), m)

    def test_a_request_aborted_under_a_refresh_waits_for_the_next_cycle(self):
        # refresh_abort_retry=next: F18-b-n3-shlmcl-pE-w1, SHL [BW],CL starts at 99 on the
        # refresh 99-103 with room for a word: no fetch before the write (refresh: F104)
        m, s = _events37("F18-b-n3-shlmcl-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 99, 112), [(99, "refresh"), (112, "data_read")])
        self.assertEqual(_span(s, 196, 205), [(196, "refresh"), (201, "data_write"),
                                              (205, "fetch")])
        m, _ = _events37("F18-b-n3-shlmcl-pE-w1", refresh_abort_retry="refresh")
        self.assertEqual(_span(m, 99, 119), [(99, "refresh"), (104, "fetch"),
                                             (114, "refresh"), (119, "data_read")])

    def test_the_sync_on_an_aborted_cycle_is_no_wait(self):
        # refresh_abort_wait=run: F18-b-n4-shlmcl-pE-w2, SHL [BW],CL starts at 110 on an
        # aborted cycle, the request of 111: silicon R113 (wait: R111)
        m, s = _events37("F18-b-n4-shlmcl-pE-w2")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 105, 124), [(105, "fetch"), (113, "refresh"),
                                              (124, "data_read")])
        m, _ = _events37("F18-b-n4-shlmcl-pE-w2", refresh_abort_wait="wait")
        self.assertEqual(_span(m, 105, 124), [(105, "fetch"), (111, "refresh"),
                                              (124, "data_read")])

    def test_the_write_back_sync_is_no_hold_point(self):
        # refresh_wbsync=seam: F8-out-empty-pE-w0, the marker OUT 20h,AL after the first LS
        # starts at 87 with the refresh 87-91: silicon F92 I101 (wait: F95 R103 I108)
        m, s = _events37("F8-out-empty-pE-w0")
        self.assertEqual(_span(m, 87, 109), _span(s, 87, 109))
        self.assertEqual(_span(s, 87, 101), [(87, "refresh"), (92, "fetch"), (101, "io_write")])
        m, _ = _events37("F8-out-empty-pE-w0", refresh_wbsync="wait")
        self.assertEqual(_span(m, 87, 108), [(87, "refresh"), (95, "fetch"), (103, "refresh"),
                                             (108, "io_write")])

    def test_a_posted_request_takes_a_refresh_on_its_first_clock(self):
        # refresh_post=post: F13-c-push-shlcl2-pO-w0, the marker PUSH AW posts its write at 129
        # (setup 7), the request of 128 pending: silicon R129 W136 (free: R133 W138)
        m, s = _events37("F13-c-push-shlcl2-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 125, 136), [(129, "refresh"), (136, "stack_write")])
        m, _ = _events37("F13-c-push-shlcl2-pO-w0", refresh_post="free")
        self.assertEqual(_span(m, 125, 138), [(133, "refresh"), (138, "stack_write")])

    def test_the_clocks_between_two_takes_are_no_hold_point(self):
        # refresh_take_seam=seam: F18-b-n3-shli4-pE-w1, SHL AW,4 starts at 99 on the refresh
        # 99-103: the count byte taken under it, silicon F104 (hold: F106)
        m, s = _events37("F18-b-n3-shli4-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 99, 115), [(99, "refresh"), (104, "fetch"), (115, "refresh")])
        m, _ = _events37("F18-b-n3-shli4-pE-w1", refresh_take_seam="hold")
        self.assertEqual(_span(m, 99, 115), [(99, "refresh"), (106, "fetch"), (115, "refresh")])

    def test_refresh_off_runs_never_see_the_wp37_rules(self):
        # the rules act only with refresh on: a refresh-off E twin is identical
        a, s = _events37("F17-e-n0-shlcl1-pO-w0")
        b, _ = _events37("F17-e-n0-shlcl1-pO-w0", **{k: OPTIONS[k][0] for k in WP37})
        self.assertEqual(a, s)
        self.assertEqual(a, b)

    def test_wp37_defaults_are_the_old_model(self):
        for name in WP37:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


_WP37HAND = []


def _events38(cid, **kw):
    """(clock, kind) from the fill of a recorded run under the twenty-eighth hand fit
    (fit-wp37-hand.json) with the WP38 rules (+ kw), the fill fetch dropped, and the silicon
    list the same way."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _WP37HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp37-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP37HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    m = simulate_normalized(s.chain, _WP37HAND[0].replace(**{**WP38, **kw}), s.chain_base,
                            refresh=refresh_anchor(s))
    return [(e[0], e[1]) for e in aligned(m)][1:], [(e[0], e[1]) for e in aligned(s)][1:]


WP38 = {"refresh_loop_hold": "entry", "sfr_setup": "count", "refresh_io_pre": "count",
        "refresh_drop_unit": "unit"}


class RefreshLoopEntrySfrSetupIoPreAndUnitDrop(unittest.TestCase):
    """WP38 (finding 8 b, e, g, the refresh side's middle, no new data): the shift's loop
    entry as the exec's hold point, the SFR store's setup through a fetch, a refresh's wait
    states before an I/O form's count began, the request lost inside a register unit's clocks
    at even room; each rule against the alternative it replaced on a named run, silicon clocks
    from t_fill quoted from chains-F13-w<N>, chains-F17-w<N>."""

    def test_a_refresh_at_the_exec_end_holds_the_loop_entry(self):
        # refresh_loop_hold=entry: F13-s-shlcl4-pE-w2, the closing LS's exec 142-147, the
        # refresh 144-148 (L-4): the loop starts a clock late, silicon R159 R176 R191 R208 R224
        # F233 (eve: no hold, R160 R175 R192 R207 R223 F232)
        m, s = _events38("F13-s-shlcl4-pE-w2")
        self.assertEqual(_span(m, 140, 235), _span(s, 140, 235))
        self.assertEqual([e for e in _span(s, 150, 235) if e[1] != "fetch"],
                         [(159, "refresh"), (176, "refresh"), (191, "refresh"),
                          (208, "refresh"), (224, "refresh")])
        self.assertIn((233, "fetch"), s)
        m, _ = _events38("F13-s-shlcl4-pE-w2", refresh_loop_hold="eve")
        self.assertEqual([e for e in _span(m, 150, 235) if e[1] != "fetch"],
                         [(160, "refresh"), (175, "refresh"), (192, "refresh"),
                          (207, "refresh"), (223, "refresh")])
        self.assertIn((232, "fetch"), m)

    def test_the_sfr_store_setup_counts_through_a_fetch(self):
        # sfr_setup=count: F17-w-ec-n2-pE-w1 (refresh off), the RFMON store posted at 86 inside
        # fetch 85-88: the on-chip write on 89, silicon F92 F96 F100 (fetch_free: the
        # back-to-back fetch first, F89 F99 F103)
        m, s = _events38("F17-w-ec-n2-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 85, 100), [(85, "fetch"), (92, "fetch"), (96, "fetch"),
                                             (100, "fetch")])
        m, _ = _events38("F17-w-ec-n2-pE-w1", sfr_setup="fetch_free")
        self.assertEqual(_span(m, 85, 103), [(85, "fetch"), (89, "fetch"), (99, "fetch"),
                                             (103, "fetch")])

    def test_a_refresh_before_the_io_count_keeps_its_waits_counting(self):
        # refresh_io_pre=count: F13-c-out-shlcl2-pE-w0, the marker OUT after the first LS
        # starts at 87 with the refresh 87-91 under its write-back sync: silicon I99 F102 R105
        # (waits: I101 R104)
        m, s = _events38("F13-c-out-shlcl2-pE-w0")
        self.assertEqual(_span(m, 87, 110), _span(s, 87, 110))
        self.assertEqual(_span(s, 87, 105), [(87, "refresh"), (92, "fetch"), (99, "io_write"),
                                             (102, "fetch"), (105, "refresh")])
        m, _ = _events38("F13-c-out-shlcl2-pE-w0", refresh_io_pre="waits")
        self.assertEqual(_span(m, 87, 104), [(87, "refresh"), (92, "fetch"), (101, "io_write"),
                                             (104, "refresh")])

    def test_a_request_at_even_room_inside_a_unit_is_lost(self):
        # refresh_drop_unit=unit: F17-s-n1-rmw-pE-w2, the closing LS's exec from 124, the word
        # delivered on 129 with room 2, the refresh 129-133: no fetch until the shift's end,
        # silicon R129 R144 ... F218 (odd: F134)
        m, s = _events38("F17-s-n1-rmw-pE-w2")
        self.assertEqual(m, s)
        self.assertEqual([e for e in _span(s, 124, 218) if e[1] == "fetch"],
                         [(124, "fetch"), (218, "fetch")])
        m, _ = _events38("F17-s-n1-rmw-pE-w2", refresh_drop_unit="odd")
        self.assertEqual(_span(m, 124, 134), [(124, "fetch"), (129, "refresh"), (134, "fetch")])

    def test_refresh_off_runs_never_see_the_refresh_rules(self):
        # refresh_loop_hold, refresh_io_pre and refresh_drop_unit act only with refresh on
        a, s = _events38("F17-e-n0-shlcl1-pO-w0")
        b, _ = _events38("F17-e-n0-shlcl1-pO-w0", refresh_loop_hold="eve",
                         refresh_io_pre="waits", refresh_drop_unit="odd")
        self.assertEqual(a, s)
        self.assertEqual(a, b)

    def test_wp38_defaults_are_the_old_model(self):
        for name in WP38:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


_WP38HAND = []


def _events39(cid, **kw):
    """(clock, kind) from the fill of a recorded run under the twenty-ninth hand fit
    (fit-wp38-hand.json) with the WP39 rules (+ kw), the fill fetch dropped, and the silicon
    list the same way."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _WP38HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp38-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP38HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    m = simulate_normalized(s.chain, _WP38HAND[0].replace(**{**WP39, **kw}), s.chain_base,
                            refresh=refresh_anchor(s))
    return [(e[0], e[1]) for e in aligned(m)][1:], [(e[0], e[1]) for e in aligned(s)][1:]


WP39 = {"refresh_io_run": "pair", "refresh_take_latch": "hold"}


class RefreshIoRunAndTakeLatch(unittest.TestCase):
    """WP39 (finding 8 b, f, the refresh side's middle, no new data): the fetch a refresh beat
    while an IN or OUT waits for its I/O runs with a second fetch back to back; an operand take
    behind a byte latched at a full queue is a hold point; each rule against the alternative it
    replaced on a named run, silicon clocks from t_fill quoted from chains-F13-w<N>."""

    def test_a_beaten_fetch_beside_a_waiting_out_runs_two_words(self):
        # refresh_io_run=pair: F13-c-out-shlcl2-pE-w2, the marker OUT after the first LS takes
        # its port byte and posts its I/O at 95 with 3 bytes stored, the refresh 95-99 beats the
        # fetch: silicon R95 F100 F105 I110 R113 (none: F100 I106 F109 R114)
        m, s = _events39("F13-c-out-shlcl2-pE-w2")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 95, 113), [(95, "refresh"), (100, "fetch"), (105, "fetch"),
                                             (110, "io_write"), (113, "refresh")])
        m, _ = _events39("F13-c-out-shlcl2-pE-w2", refresh_io_run="none")
        self.assertEqual(_span(m, 95, 114), [(95, "refresh"), (100, "fetch"), (106, "io_write"),
                                             (109, "fetch"), (114, "refresh")])
        # the second OUT, started on the issue of a fetch the refresh 128-132 beat at the end of
        # X's shift (room 2): F13-c-out-shlcl2-pO-w0, silicon F133 F136 (none: F133 F143)
        m, s = _events39("F13-c-out-shlcl2-pO-w0")
        self.assertEqual(_span(m, 120, 140), _span(s, 120, 140))
        self.assertEqual(_span(s, 128, 140), [(128, "refresh"), (133, "fetch"), (136, "fetch")])
        m, _ = _events39("F13-c-out-shlcl2-pO-w0", refresh_io_run="none")
        self.assertEqual(_span(m, 128, 143), [(128, "refresh"), (133, "fetch"), (143, "fetch")])

    def test_a_take_behind_a_full_queue_waits_out_the_refresh(self):
        # refresh_take_latch=hold: F13-n-none-nop8-pE-w2, MOV CL,31 starts after the NOP train
        # at 129 with the refresh 129-133 and a word delivered into 6 stored bytes: silicon
        # R129 F136 R143 (free: the take at 132 under the refresh, SHL AW,CL at 134, F134 R145)
        m, s = _events39("F13-n-none-nop8-pE-w2")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 129, 143), [(129, "refresh"), (136, "fetch"), (143, "refresh")])
        m, _ = _events39("F13-n-none-nop8-pE-w2", refresh_take_latch="free")
        self.assertEqual(_span(m, 129, 145), [(129, "refresh"), (134, "fetch"), (145, "refresh")])

    def test_refresh_off_runs_never_see_the_refresh_rules(self):
        # the refresh-off twin of the marker OUT cell: the same queue at the port take, the
        # fetch issued there, no second fetch (F77 I86 F89)
        a, s = _events39("F3-out-shl_cl2-k1-pE-w2")
        b, _ = _events39("F3-out-shl_cl2-k1-pE-w2", refresh_io_run="none",
                         refresh_take_latch="free")
        self.assertEqual(a, s)
        self.assertEqual(a, b)
        self.assertEqual(_span(s, 77, 89), [(77, "fetch"), (86, "io_write"), (89, "fetch")])

    def test_wp39_defaults_are_the_old_model(self):
        for name in WP39:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


_WP39HAND = []
WP40 = {"prelude_tail": "segs", "prelude_anchor": "pop", "wlatch_ir_at": "start",
        "pop_refresh": "stall", "refresh_reissue": "keep", "refresh_run_modrm": "wait",
        "refresh_sync_run": "two", "refresh_sync_reg": "delivery", "room_ir_imm": "none"}


def _pre40(cid, **kw):
    """The pre window (normalize.Normalized.pre: the prelude's POP PSW read to clock 0) of a
    recorded run, (clock rel the POP read, kind char), silicon and the model under the thirtieth
    hand fit (fit-wp39-hand.json) with the WP40 prelude rules (+ kw)."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _WP39HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp39-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP39HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    m = simulate_normalized(s.chain, _WP39HAND[0].replace(**{**WP40, **kw}), s.chain_base,
                            refresh=refresh_anchor(s))
    pre = lambda n: [(e.clock - n.pre[0].clock, e.char) for e in n.pre] if n.pre else []
    return pre(m), pre(s), m, s


def _chars(pre):
    return " ".join(f"{c}{t}" for t, c in pre)


class PreludePopAnchor(unittest.TestCase):
    """WP40 (finding 8 a): the model runs the prelude's tail from its POP PSW stack read
    (prelude_anchor=pop, the counter there refresh.POP_COUNTER) and its events before clock 0
    are compared with silicon's (Normalized.pre); each rule the refresh-on pre window needs,
    against the alternative it replaces on a named run, clocks rel the POP read quoted from
    chains-F13-w<N> / chains-F17-w0. Not in fit.json (the OUT-marked cells and two 0-wait R
    cells still lose, scratchpad wp40-facts.md)."""

    def test_the_refresh_off_pre_window_is_the_models(self):
        # every ECh cell: r0 F11 F14 F17 F24 ... at 0 waits, the first fetch at read + 11 + w
        for cid in ("F17-s-n0-empty-pE-w0", "F17-s-n0-empty-pO-w1", "F17-s-n0-empty-pE-w2"):
            m, s, mn, sn = _pre40(cid)
            self.assertEqual(m, s, cid)
            self.assertEqual(mn.t_fill, sn.t_fill, cid)
        m, s, _, _ = _pre40("F17-s-n0-empty-pE-w0")
        self.assertEqual(_chars(s), "r0 F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 "
                                    "F65 F72 F75")
        m, _, _, _ = _pre40("F17-s-n0-empty-pE-w0", pop_exit=3)
        self.assertEqual(m[1], (10, "F"))          # the read a clock late against the train

    def test_the_counter_at_the_pop_read(self):
        # the FCh prelude at 0 waits: requests at read + 10 + 16k, served 11 29 44 59 74 93
        from validation.v35s.chains.sim.refresh import POP_COUNTER, PRELUDE_COUNTER
        self.assertEqual(POP_COUNTER[(0xFC, 0)], (PRELUDE_COUNTER[(0xFC, 0)] - 98) % 128)
        for key, read in (((0xFC, 0, "push"), -102), ((0xFC, 1, "out"), -115),
                          ((0xFD, 2, "push"), -134), ((0xEC, 1, "out"), -100)):
            iv = 16 << (key[0] & 3)
            self.assertEqual((PRELUDE_COUNTER[key] + read) % iv, POP_COUNTER[key[:2]] % iv, key)
        m, s, _, _ = _pre40("F17-p-n0-empty-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual([t for t, c in s if c == "X"], [12, 29, 42, 59, 76, 93, 106])

    def test_a_refresh_in_pop_psws_clocks_costs_its_length_less_2(self):
        # pop_refresh=stall: F13-r-rfw-1-pE-w1 (F4h, 4-clock refresh): X4 F14 (none: F12)
        m, s, _, _ = _pre40("F13-r-rfw-1-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_chars(s[:6]), "r0 X4 F14 X18 F22 F26")
        m, _, _, _ = _pre40("F13-r-rfw-1-pE-w1", pop_refresh="none")
        self.assertEqual(_chars(m[:5]), "r0 X4 F12 F16 X20")

    def test_the_beaten_fetch_keeps_its_reissue_and_a_modrm_form_waits(self):
        # refresh_reissue=keep, refresh_run_modrm=wait: F13-c-out-shlcl0-pE-w1, the refresh at
        # 12 beats MOV AW,imm16's fetch: silicon X12 F17 F21 F25 X29 F34 (either flipped back:
        # X31 F36)
        m, s, _, _ = _pre40("F13-c-out-shlcl0-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_chars(s[1:7]), "X12 F17 F21 F25 X29 F34")
        for kw in ({"refresh_reissue": "clear"}, {"refresh_run_modrm": "early"}):
            m, _, _, _ = _pre40("F13-c-out-shlcl0-pE-w1", **kw)
            self.assertEqual(_chars(m[1:7]), "X12 F17 F21 F25 X31 F36", kw)

    def test_the_early_sync_on_the_runs_first_two_fetches_only(self):
        # refresh_sync_run=two: F13-r-rfm-f1-pE-w1 (FDh): F70 F78 F82 (all: F70 F76 F80)
        m, s, _, _ = _pre40("F13-r-rfm-f1-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_chars(s[12:16]), "F66 F70 F78 F82")
        m, _, _, _ = _pre40("F13-r-rfm-f1-pE-w1", refresh_sync_run="all")
        self.assertEqual(_chars(m[12:16]), "F66 F70 F76 F80")

    def test_a_register_forms_sync_on_the_delivery(self):
        # refresh_sync_reg=delivery: F13-c-out-shlcl0-pE-w0: F40 X44 F49 (early: F40 X43 F48)
        m, s, _, _ = _pre40("F13-c-out-shlcl0-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_chars(s[8:11]), "F40 X44 F49")
        m, _, _, _ = _pre40("F13-c-out-shlcl0-pE-w0", refresh_sync_reg="early")
        self.assertEqual(_chars(m[8:11]), "F40 X43 F48")

    def test_no_idle_ir_slot_under_a_16_bit_immediate(self):
        # room_ir_imm=none: F13-r-rfm-f1-pE-w0 (FDh): X72 F77 F81 (idle: X72 F77 F82)
        m, s, _, _ = _pre40("F13-r-rfm-f1-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_chars(s[-4:-1]), "X72 F77 F81")
        m, _, _, _ = _pre40("F13-r-rfm-f1-pE-w0", room_ir_imm="idle")
        self.assertEqual(_chars(m[-4:-1]), "X72 F77 F82")

    def test_the_stand_in_has_no_pre_window(self):
        # prelude_anchor=clock0 (the stand-in or the old tail anchor): no POP read in the model
        m, s, _, _ = _pre40("F17-s-n0-empty-pE-w0", prelude_tail="standin",
                            prelude_anchor="clock0")
        self.assertEqual(m, [])
        self.assertTrue(s)

    def test_wp40_defaults_are_the_old_model(self):
        for name in ("prelude_anchor", "pop_refresh", "refresh_reissue", "refresh_run_modrm",
                     "refresh_sync_run", "refresh_sync_reg", "room_ir_imm"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


WP41 = {"refresh_lead_port": "last", "refresh_drop_post": "hold", "refresh_wlatch": "hold",
        "refresh_beat_t4": "t4"}


def _ev41(cid, lo, hi, **kw):
    """Silicon's and the model's events (pre window included) from clock lo to hi rel clock 0,
    as "X20 I25" strings, under the thirtieth hand fit with the WP40 and WP41 rules (+ kw)."""
    _, _, m, s = _pre40(cid, **{**WP41, **kw})
    f = lambda n: " ".join(f"{e.char}{e.clock}" for e in n.pre + n.events if lo <= e.clock <= hi)
    return f(m), f(s)


class RefreshPreludeTailLosses(unittest.TestCase):
    """WP41: the rules that close the prelude tail's last 51 losses (scratchpad wp41-facts.md),
    each against the alternative it replaces on a named run (rel clock 0 unless stated, quoted
    from chains-F18-w<N> / chains-F13-w<N> / chains-F17-w1)."""

    def test_a_port_forms_lead_holds_a_refresh_on_its_last_clock_only(self):
        # refresh_lead_port=last: the FCh marker OUT, the request at 20 on the lead's first clock
        m, s = _ev41("F18-a-out-fc-empty-pE-w0", 12, 27)
        self.assertEqual(m, s)
        self.assertEqual(s, "F12 F15 X20 I25")
        m, _ = _ev41("F18-a-out-fc-empty-pE-w0", 12, 27, refresh_lead_port="lead")
        self.assertEqual(m, "F12 F15 X22 I27")
        # the request on the lead's last clock still waits for the issue clock
        m, s = _ev41("F17-s-n0-out-pE-w1", 123, 136)
        self.assertEqual(m, s)
        self.assertEqual(s, "F123 X131 I136")

    def test_a_request_lost_on_a_port_forms_post_is_held_by_the_io(self):
        # refresh_drop_post=hold: the FCh 2-wait marker OUT posts on 20 with a byte latched
        m, s = _ev41("F18-a-out-fc-empty-pE-w2", 15, 32)
        self.assertEqual(m, s)
        self.assertEqual(s, "F15 X20 F27 I32")
        m, _ = _ev41("F18-a-out-fc-empty-pE-w2", 15, 32, refresh_drop_post="drop")
        self.assertEqual(m, "F15 X20 I29")

    def test_no_refresh_while_an_io_form_waits_for_the_data_latch(self):
        # refresh_wlatch=hold: the FDh 0-wait marker OUT, the request at 9
        m, s = _ev41("F18-a-out-fd-empty-pE-w0", 7, 26)
        self.assertEqual(m, s)
        self.assertEqual(s, "F7 X11 F21 I24")
        m, _ = _ev41("F18-a-out-fd-empty-pE-w0", 7, 26, refresh_wlatch="free")
        self.assertEqual(m, "F7 X10 F23 I26")

    def test_a_3_clock_beaten_fetch_holds_its_delivery_clock(self):
        # refresh_beat_t4=t4: FEh at 0 waits, rel the POP read: X27 F32 F36 (none: F35)
        m, s, _, _ = _pre40("F13-r-rfm-f2-pE-w0", **WP41)
        self.assertEqual(m, s)
        self.assertEqual(_chars(s[5:9]), "X27 F32 F36 F39")
        m, _, _, _ = _pre40("F13-r-rfm-f2-pE-w0", **{**WP41, "refresh_beat_t4": "none"})
        self.assertEqual(_chars(m[5:9]), "X27 F32 F35 F39")
        # a 4-clock beaten fetch (F4h at 1 wait) frees the bus on its delivery
        m, s, _, _ = _pre40("F13-r-rfw-1-pE-w1", **WP41)
        self.assertEqual(m, s)

    def test_the_ffh_1_wait_counter_from_the_first_refreshes(self):
        # POP_COUNTER (FFh, 1) = 79: requests on 21 and 149, silicon F20 X24 ... X149
        from validation.v35s.chains.sim.refresh import POP_COUNTER
        self.assertEqual(POP_COUNTER[(0xFF, 1)], 79)
        m, s = _ev41("F13-r-rfm-f3-pE-w1", 16, 160)
        self.assertEqual(m, s)
        self.assertEqual(s.split()[:3], ["F16", "F20", "X24"])
        self.assertIn("X149", s.split())

    def test_an_older_fetch_still_runs_on_the_port_forms_lead_first_clock(self):
        # refresh_lead_port=last with a fetch the lift lets run: the fetch first, no overfill
        from validation.v35s.chains.families import generate
        from validation.v35s.chains.sim.machine import Machine
        _pre40("F17-s-n0-empty-pE-w0")             # loads the hand fit
        cfg = _WP39HAND[0].replace(**{**WP40, **WP41})
        chain = next(c for c in generate(families=["F13"], waits=(2,))
                     if c.id == "F13-c-out-shlcl12-pO-w2")
        m = Machine(chain, cfg)
        m.run()                                     # QueueOverflow if the refresh beat it
        self.assertLessEqual(m.queue.peak, 6)

    def test_wp41_defaults_are_the_old_model(self):
        for name in WP41:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


# (WP43, F22) the immediate forms' post against the fetch run: the immediate RMW's displaced
# read posted where the store's write is (rmw_imm.dadd 1), TEST r/m,imm16's lookup between its
# ModR/M and displacement bytes, the one-byte immediate's request on a non-run delivery clock
WP43 = {"rmw_imm.dadd": 1, "fixed_lookup_grp": "group", "imm1_first": "hold"}
_WP41HAND = []
_RUNS43 = {}


def _ev43(cid, lo, hi, **kw):
    """Silicon's and the model's events from clock lo to hi rel t_fill, as "F75 R79" strings,
    under the thirty-first hand fit (fit-wp41-hand.json) with the WP43 rules (+ kw)."""
    import json
    from pathlib import Path

    if not _WP41HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp41-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP41HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS43:
        _RUNS43[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS43[family][cid])
    m = simulate_normalized(s.chain, _WP41HAND[0].replace(**{**WP43, **kw}), s.chain_base)
    k = {"fetch": "F", "data_read": "R", "data_write": "W", "io_write": "I", "io_read": "i",
         "stack_write": "S", "stack_read": "P"}
    f = lambda n: " ".join(f"{k.get(e[1], '?')}{e[0]}" for e in aligned(n) if lo <= e[0] <= hi)
    return f(m), f(s)


class ImmediateFormsPostAgainstTheRun(unittest.TestCase):
    """WP43 (F22, chains-F22-w0/w1): each rule against the alternative it replaces on a named
    run; clocks rel t_fill quoted from the corpus."""

    def test_the_rmws_displaced_read_is_posted_where_the_stores_write_is(self):
        # ADD [BW+200h],imm16, marker-less, pO, 0 waits (s 72): silicon F75 R79 F82 W85, as
        # MOV [BW+200h],imm16's F75 W79 F82 (rmw_imm.dadd 0: F75 F78 R81 W86)
        m, s = _ev43("F22-none-l0-add_d16-pO-w0", 70, 86)
        self.assertEqual(s, "F75 R79 F82 W85")
        self.assertEqual(m, s)
        m, _ = _ev43("F22-none-l0-add_d16-pO-w0", 70, 86, **{"rmw_imm.dadd": 0})
        self.assertEqual(m, "F75 F78 R81 W86")
        # item 1's three F5 runs: the run's fetch at the read's eve and the idle clock after it
        m, s = _ev43("F5-push-add_m_imm_d16-k1-pE-w0", 86, 92)
        self.assertEqual(s, "F87 R91")
        self.assertEqual(m, s)
        m, _ = _ev43("F5-push-add_m_imm_d16-k1-pE-w0", 86, 92, **{"rmw_imm.dadd": 0})
        self.assertEqual(m, "F87 R90")
        # ADD [BW+10h],imm16 at 1 wait after a start-clock fetch: R84 = s + 8 (0: R83)
        m, s = _ev43("F22-none-n1-add_d8-pE-w1", 76, 84)
        self.assertEqual(m, s)
        self.assertEqual(s, "F76 R84")
        m, _ = _ev43("F22-none-n1-add_d8-pE-w1", 76, 84, **{"rmw_imm.dadd": 0})
        self.assertEqual(m, "F76 R83")

    def test_test_imm_with_a_displacement_runs_the_fixed_lookup_in_the_decoder(self):
        # TEST [BW+200h],imm16 at an odd address, no fetch on the start clock (s 72): the
        # displacement's fetch at s+5, the read at s+9 (none: F75 F78 R82)
        m, s = _ev43("F22-none-l0-test_d16-pO-w0", 70, 82)
        self.assertEqual(s, "F77 R81")
        self.assertEqual(m, s)
        m, _ = _ev43("F22-none-l0-test_d16-pO-w0", 70, 82, fixed_lookup_grp="none")
        self.assertEqual(m, "F75 F78 R82")
        # even address with a start-clock fetch: s+6 (lookup_start) and R s+10 (none: F75)
        m, s = _ev43("F22-none-l0-test_d16-pE-w0", 70, 82)
        self.assertEqual(s, "F72 F78 R82")
        self.assertEqual(m, s)
        m, _ = _ev43("F22-none-l0-test_d16-pE-w0", 70, 82, fixed_lookup_grp="none")
        self.assertEqual(m, "F72 F75 R82")
        # TEST [BW],imm16 (no displacement) is untouched: R s+9
        for g in ("none", "group"):
            m, s = _ev43("F15-a-none-test_bw_imm-pO-w0", 70, 82, fixed_lookup_grp=g)
            self.assertEqual(m, s, g)

    def test_one_byte_immediate_request_goes_first_on_a_non_run_delivery_clock(self):
        # ADD [BW+200h],imm8, marker-less, pO, 0 waits: its read issuable on fetch 75's
        # delivery 78 with 4 bytes counted: silicon F75 R78 F81 (none: F75 F78 R81)
        m, s = _ev43("F22-none-l0-add8_d16-pO-w0", 70, 82)
        self.assertEqual(s, "F75 R78 F81")
        self.assertEqual(m, s)
        m, _ = _ev43("F22-none-l0-add8_d16-pO-w0", 70, 82, imm1_first="none")
        self.assertEqual(m, "F75 F78 R81")
        # 1 wait, against ADD [BW+200h],imm16 in the same cell, which fetches first
        m, s = _ev43("F22-push-n3-add8_d16-pO-w1", 96, 102)
        self.assertEqual(s, "F97 R101")
        self.assertEqual(m, s)
        m, s = _ev43("F22-push-n3-add_d16-pO-w1", 96, 102)
        self.assertEqual(s, "F97 F101")
        self.assertEqual(m, s)
        # after a fetch run (a fetch on the start clock) the fetch goes first: F84 F87 R90
        for v in ("none", "hold"):
            m, s = _ev43("F22-push-l0-add8_d16-pE-w0", 80, 90, imm1_first=v)
            self.assertEqual(m, s, v)
        self.assertEqual(s, "F81 F84 F87 R90")
        # behind the OUT marker's I/O at pE with 3 counted the fetch goes first under both
        for v in ("none", "hold"):
            m, s = _ev43("F22-out-l0-add8_d16-pE-w0", 84, 93, imm1_first=v)
            self.assertEqual(m, s, v)

    def test_wp43_defaults_are_the_old_model(self):
        self.assertEqual(DEFAULT.c("rmw_imm", "dadd"), 0)
        for name in ("fixed_lookup_grp", "imm1_first"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


# (WP45, F13) an I/O request's setup counts from its post (io_post=take, the thirty-third
# fit), not from the instruction's start (start, the sixth to the thirty-second fit)
_WP43HAND = []
_RUNS45 = {}


def _ev45(cid, **kw):
    """(model, silicon) aligned events (clock rel t_fill, kind, addr, width, length) of a
    recorded run under the thirty-second hand fit (fit-wp43-hand.json, io_post=start) + kw,
    the refresh timer placed by the run's anchor."""
    import json
    from pathlib import Path
    from validation.v35s.chains.sim.machine import refresh_anchor

    if not _WP43HAND:
        path = (Path(__file__).resolve().parents[3]
                / "build/validation/v35s/chains/fit/fit-wp43-hand.json")
        if not path.exists():
            raise unittest.SkipTest(f"no {path}")
        _WP43HAND.append(Config.from_json(json.loads(path.read_text())))
    family = cid.split("-")[0]
    if family not in _RUNS45:
        _RUNS45[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS45[family][cid])
    m = simulate_normalized(s.chain, _WP43HAND[0].replace(**kw), s.chain_base,
                            refresh=refresh_anchor(s))
    return aligned(m), aligned(s)


class IoPostFromTake(unittest.TestCase):
    """WP45 (F13 C and U OUT cells, RFM FCh, odd parity, 1 wait): the marker OUT 21h,AL
    after a long register instruction (SHL AW,CL with CL=8; MULU) starts at 149 on the fetch
    the refresh 144-148 held to then, so that fetch's wait state (151) falls in the OUT's pre
    (151-153 after its write-back sync); it posts at 154 and the refresh 159-163 runs in its
    setup (its 2 wait states uncounted under io_count=nowait either way). Silicon issues the
    io_write at 164, at the refresh's end: 8 countable clocks from the post (take); counted
    from the start the pre gives 2 of its 3 clocks and the issue is 165."""

    RUNS = ("F13-c-out-shlcl8-pO-w1", "F13-u-out-mulu-k1-pO-w1")

    def _io21(self, ev):
        return [e[0] for e in ev if e[1] == "io_write" and e[2] == 0x21]

    def test_take_is_exact_and_start_a_clock_late_at_the_marker(self):
        for cid in self.RUNS:
            m, s = _ev45(cid, io_post="take")
            self.assertEqual(self._io21(s), [164], cid)
            self.assertEqual(m, s, cid)
            m, _ = _ev45(cid, io_post="start")
            self.assertEqual(self._io21(m), [165], cid)
            k = next(i for i, (x, y) in enumerate(zip(m, s)) if x != y)
            self.assertEqual((s[k][:2], m[k][:2]), ((164, "io_write"), (165, "io_write")), cid)

    def test_the_refresh_in_the_setup_is_the_same_under_both(self):
        for cid in self.RUNS:
            for v in ("take", "start"):
                m, _ = _ev45(cid, io_post=v)
                self.assertIn((144, "refresh"), [e[:2] for e in m], (cid, v))
                self.assertIn((159, "refresh"), [e[:2] for e in m], (cid, v))
                self.assertIn((149, "fetch"), [e[:2] for e in m], (cid, v))

    def test_default_is_take(self):
        self.assertEqual(DEFAULT.io_post, "take")
        self.assertEqual(OPTIONS["io_post"][0], "take")


class TrackedFit(unittest.TestCase):
    """The adopted fit is tracked (sim.config.FIT_PATH) so a fresh checkout scores the
    model; it must be canonical and name every Config field, so no field silently takes
    DEFAULT's value, and `adopt` is the only way to change it."""

    def setUp(self):
        import json
        from dataclasses import fields

        from validation.v35s.chains.sim import config
        self.json, self.config = json, config
        self.names = {f.name for f in fields(Config)}

    def test_loads(self):
        self.assertTrue(self.config.FIT_PATH.is_file())
        self.assertIsInstance(Config.fitted(), Config)

    def test_canonical(self):
        text = self.config.FIT_PATH.read_text()
        dumped = self.json.dumps(Config.fitted().to_json(), indent=1, sort_keys=True)
        self.assertIn(text, (dumped, dumped + "\n"))

    def test_every_field(self):
        self.assertEqual(set(self.json.loads(self.config.FIT_PATH.read_text())), self.names)

    def test_adopt(self):
        import argparse
        import contextlib
        import io
        import tempfile
        from pathlib import Path
        from unittest import mock

        from validation.v35s.chains.score import adopt_main
        text = self.config.FIT_PATH.read_text()
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src.json", Path(tmp) / "fit.json"
            src.write_text(text)
            with mock.patch.object(self.config, "FIT_PATH", dst), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(adopt_main(argparse.Namespace(path=str(src))), 0)
                self.assertEqual(dst.read_text(), text)
                bad = {**self.json.loads(text), "no_such_field": 1}
                src.write_text(self.json.dumps(bad))
                dst.write_text("untouched")
                self.assertEqual(adopt_main(argparse.Namespace(path=str(src))), 2)
                self.assertEqual(dst.read_text(), "untouched")


class EaAloneAndStackFrame(unittest.TestCase):
    """(WP52, F25) decode / execute / templates of LDEA, XLAT, the immediate, segment and
    burst pushes and pops, PREPARE and DISPOSE, and the F25 chains simulate."""

    REGS = {"AW": 0x0034, "BW": 0x0800, "CW": 0, "DW": 0x40, "SP": 0x0F00, "BP": 0x0A00,
            "IX": 0x0100, "IY": 0x0180, "Z": 1, "ret0F00": 0,   # (WP55) the F23 forms' context
            "CY": 0, "S": 0, "V": 0, "P": 1,                     # (WP88) F35's conditions
            **F37_WORDS}                                         # (WP91) F37's stored words

    def _op(self, form):
        from validation.v35s.chains.sim.templates import execute
        regs = dict(self.REGS)
        code = FORMS[form].code
        op = decode(code, 0, regs)
        self.assertEqual(op.length, len(code), form)
        self.assertEqual(op.cls, FORMS[form].cls, form)
        execute(op, code, regs)
        return op, regs

    def test_classes_have_templates(self):
        from validation.v35s.chains.forms import CLASSES, F25_LDEA_FORMS, F25_STACK_FORMS
        from validation.v35s.chains.sim.config import DEFAULT_COST
        from validation.v35s.chains.sim.templates import steps
        for form in FORMS.values():
            if form.name in UNMODELLED_FORMS:
                continue
            self.assertIn(form.cls, CLASSES, form.name)
            if form.name in F25_LDEA_FORMS + F25_STACK_FORMS:
                self.assertIn(form.cls, DEFAULT_COST, form.name)   # the new classes' own dicts
            op = decode(form.code, 0, dict(self.REGS))
            self.assertTrue(steps(op, DEFAULT), form.name)

    def test_push_r_eight_addresses(self):
        from validation.v35s.chains.sim.templates import steps
        op, regs = self._op("push_r")
        self.assertEqual(regs["SP"], 0x0EF0)
        for burst in OPTIONS["burst_wait"]:
            seq = steps(op, DEFAULT.replace(burst_wait=burst))
            writes = [s[2] for s in seq if s[0] in ("data", "post") and s[1] == "write"]
            self.assertEqual(writes, [0x0F00 - 2 * (i + 1) for i in range(8)], burst)
        op, regs = self._op("pop_r")
        self.assertEqual(regs["SP"], 0x0F10)
        reads = [s[2] for s in steps(op, DEFAULT) if s[0] in ("data", "post")]
        self.assertEqual(reads, [0x0F00 + 2 * i for i in range(8)])

    def test_push_r_matches_the_normaliser(self):
        from validation.v35s.chains.normalize import expected_accesses
        from validation.v35s.chains.sim.templates import steps
        chain = next(c for c in generate(["F25"], waits=(0,), parities=("even",))
                     if c.id == "F25-out-pushr_popr-pE-w0")
        x = [k for k, i in enumerate(chain.instrs) if i.role == "x"]
        exp = expected_accesses(chain)
        regs = dict(self.REGS)
        for k, name in zip(x, ("push_r", "pop_r")):
            op = decode(FORMS[name].code, 0, regs)
            got = [s[2] for s in steps(op, DEFAULT) if s[0] in ("data", "post")]
            self.assertEqual(got, [a.addr for a in exp[k]], name)
            from validation.v35s.chains.sim.templates import execute
            execute(op, FORMS[name].code, regs)

    def test_prepare_dispose_sp_bp(self):
        from validation.v35s.chains.sim.templates import execute
        regs = dict(self.REGS)
        code = FORMS["prepare_00"].code + FORMS["dispose"].code
        op = decode(code, 0, regs)
        self.assertEqual((op.cls, op.length, op.stack), ("prepare", 4, (None, 0x0EFE)))
        execute(op, code, regs)
        self.assertEqual((regs["SP"], regs["BP"]), (0x0EFE, 0x0EFE))
        op = decode(code, 4, regs)
        self.assertEqual((op.cls, op.stack), ("dispose", (0x0EFE, None)))
        execute(op, code, regs)
        self.assertEqual(regs["SP"], 0x0F00)
        self.assertRaises(ValueError, decode, bytes([0xC8, 0, 0, 1]), 0, dict(self.REGS))

    def test_xlat_address(self):
        op, regs = self._op("xlat")
        self.assertEqual((op.ea, op.width), (0x0834, 1))
        self.assertEqual(regs["AW"] & 0xFF, 0x90)

    def test_ldea_writes_the_offset(self):
        for name, ea in (("ldea_bw", 0x0800), ("ldea_bw_ix_d8", 0x0910),
                         ("ldea_bp_iy_d16", 0x0D80), ("ldea_dir", 0x0C00)):
            op, regs = self._op(name)
            self.assertEqual((op.cls, op.ea, op.bus), ("lea", ea, False), name)
            self.assertEqual(regs["AW"], ea, name)
            self.assertEqual(regs["SP"], 0x0F00, name)

    def test_segment_forms(self):
        for name, cls, sp in (("push_ds1", "push_seg", 0x0EFE), ("pop_ds0", "pop_seg", 0x0F02),
                              ("push_imm16", "push_imm", 0x0EFE),
                              ("push_imm8", "push_imm", 0x0EFE),
                              ("mov_ds1_aw", "reg", 0x0F00), ("mov_aw_ds1", "reg", 0x0F00),
                              ("mov_ds1_m", "load_seg", 0x0F00), ("mov_m_ds0", "store", 0x0F00)):
            op, regs = self._op(name)
            self.assertEqual((op.cls, regs["SP"]), (cls, sp), name)

    def test_f25_simulates(self):
        for chain in generate(["F25"], waits=(0, 1, 2)):
            with self.subTest(chain=chain.id):
                for cfg in (DEFAULT, Config.fitted()):
                    events = simulate(chain, cfg)
                    self.assertEqual(events[-1].kind, "io_write")
                    self.assertEqual(events[-1].addr, 0xFF00)


class ControlFlow(unittest.TestCase):
    """(WP55, F23) decode / execute / templates of the control transfers (BE, BNE, BR short
    and near, DBNZ, CALL, RET): the target, the flush and the refill from it, CALL's and RET's
    stack word and SP, DBNZ's count, and the F23 chains simulate."""

    REGS = {"AW": 0, "BW": 0x0800, "CW": 0, "DW": 0x40, "SP": 0x0F00, "BP": 0x0A00,
            "IX": 0x0100, "IY": 0x0180, "Z": 1}
    CLASSES = ("branch_short", "branch_near", "dbnz", "call", "ret")

    def _chain(self, cid):
        return next(c for c in generate(["F23"], waits=(int(cid[-1]),),
                                        parities=("even" if "-pE-" in cid else "odd",))
                    if c.id == cid)

    def test_classes_have_templates_and_costs(self):
        from validation.v35s.chains.forms import F23_FORMS
        from validation.v35s.chains.sim.config import DEFAULT_COST
        from validation.v35s.chains.sim.templates import steps
        for name in F23_FORMS:
            form = FORMS[name]
            regs = {**self.REGS, "CW": 2, "ret0F00": 0}
            op = decode(form.code, 0, regs)
            self.assertEqual((op.cls, op.length), (form.cls, len(form.code)), name)
            self.assertTrue(steps(op, DEFAULT), name)
            if op.cls in self.CLASSES:
                self.assertIn(op.cls, DEFAULT_COST, name)

    def test_targets(self):
        from validation.v35s.chains.sim.templates import execute
        for name, target in (("be_n3", 5), ("br_n7", 9), ("br_near_n2", 5), ("bne_n2", None),
                             ("call_n2", 5), ("dbnz_n2", 4)):
            regs = {**self.REGS, "CW": 2}
            op = decode(FORMS[name].code, 0, regs)
            self.assertEqual(op.target, target, name)
            self.assertEqual(op.cond, name.startswith(("be_", "bne_")), name)
        regs = {**self.REGS, "Z": 0}
        self.assertEqual(decode(FORMS["bne_n0"].code, 0, regs).target, 2)
        self.assertIsNone(decode(FORMS["be_n0"].code, 0, regs).target)
        self.assertRaises(ValueError, decode, FORMS["be_n0"].code, 0, {**self.REGS, "Z": None})
        # DBNZ: CW counted down, taken while it is not 0
        regs = {**self.REGS, "CW": 1}
        op = decode(FORMS["dbnz_n0"].code, 0, regs)
        self.assertIsNone(op.target)
        execute(op, FORMS["dbnz_n0"].code, regs)
        self.assertEqual(regs["CW"], 0)
        # CMP AW,AW sets Z
        regs = {**self.REGS, "Z": None}
        execute(decode(FORMS["cmp_aw_aw"].code, 0, regs), FORMS["cmp_aw_aw"].code, regs)
        self.assertEqual(regs["Z"], 1)

    def test_call_ret_stack(self):
        from validation.v35s.chains.sim.templates import execute, steps
        code = FORMS["call_n2"].code + FORMS["br_n1"].code + FORMS["ret"].code
        regs = dict(self.REGS)
        call = decode(code, 0, regs)
        self.assertEqual((call.cls, call.target, call.stack), ("call", 5, (None, 0x0EFE)))
        writes = [s for s in steps(call, DEFAULT) if s[0] == "data"]
        self.assertEqual([(s[1], s[2]) for s in writes], [("write", 0x0EFE)])
        execute(call, code, regs)
        self.assertEqual((regs["SP"], regs["ret0EFE"]), (0x0EFE, 3))
        ret = decode(code, 5, regs)
        self.assertEqual((ret.cls, ret.target, ret.stack), ("ret", 3, (0x0EFE, None)))
        execute(ret, code, regs)
        self.assertEqual(regs["SP"], 0x0F00)
        self.assertRaises(ValueError, decode, code, 5, dict(self.REGS))   # no CALL before

    def test_run_order_and_refill(self):
        for cfg in (DEFAULT, Config.fitted()):
            # callret runs CALL, RET, BR (X indices 0, 2, 1)
            chain = self._chain("F23-out-callret-pE-w0")
            m = Machine(chain, cfg)
            m.run()
            x = {i.offset: i.index for i in chain.instrs if i.role == "x"}
            self.assertEqual([x[o] for _, o, _ in m.eu.trace if o in x], [0, 2, 1])
            # after a taken branch the fetches restart at the target: an odd target's first
            # fetch at the odd address itself (its one byte), then the next words
            for cid, odd in (("F23-out-be-n0-pE-w0", False), ("F23-out-be-n1-pE-w0", True)):
                chain = self._chain(cid)
                be = next(i for i in chain.instrs if i.form.startswith("be_"))
                target = 0x10047 + be.offset + 2 + be.code[1]
                self.assertEqual(target & 1, int(odd))
                m = Machine(chain, cfg)
                cycles = m.run()
                fetches = [c.addr for c in cycles if c.kind == "fetch"]
                k = fetches.index(target)
                self.assertEqual(fetches[k + 1:k + 3], [(target | 1) + 1, (target | 1) + 3])
                self.assertNotIn(target - 1 if odd else target + 1, fetches[k:k + 4])

    def test_not_taken_is_fetch_only(self):
        for cid in ("F23-out-bne-n0-k1-pE-w0", "F23-out-bne-n0-k2-pO-w1",
                    "F23-push-dbnz-c1-n0-pE-w2"):
            chain = self._chain(cid)
            n = simulate_normalized(chain, Config.fitted())
            m0, m1 = sorted(n.t_markers.values())
            mid = [e.kind for e in n.events if m0 < e.clock < m1]
            self.assertEqual(set(mid), {"fetch"}, cid)

    def test_f23_simulates(self):
        for chain in generate(["F23"], waits=(0, 1, 2)):
            with self.subTest(chain=chain.id):
                for cfg in (DEFAULT, Config.fitted()):
                    events = simulate(chain, cfg)
                    self.assertEqual(events[-1].kind, "io_write")
                    self.assertEqual(events[-1].addr, 0xFF00)

    def test_every_option_runs(self):
        from validation.v35s.chains.fit import F23_ENUMS
        chains = [self._chain(c) for c in ("F23-out-callret-pO-w2", "F23-push-be-n3-pE-w1",
                                           "F23-out-dbnz-c2-n2-pE-w0")]
        for name, values in F23_ENUMS.items():
            for v in values:
                for chain in chains:
                    with self.subTest(option=name, value=v, chain=chain.id):
                        events = simulate(chain, Config.fitted().replace(**{name: v}))
                        self.assertEqual(events[-1].addr, 0xFF00)


_TRACKED = []
WP58 = {"refresh_io_step": "own", "refresh_io_stall": "step", "io_step_issue": "step",
        "refresh_io_run": "pair_out", "port_ready": "issue", "refresh_post": "post_beat"}


# the thirty-fourth fit's values of the WP58 fields (refresh_io_run=pair from WP39)
FIT34 = {"refresh_io_step": "any", "refresh_io_stall": "waits", "io_step_issue": "count",
         "refresh_io_run": "pair", "port_ready": "relatch", "refresh_post": "post"}


def _fit58(**kw):
    """The tracked fit with the WP58 values (+ kw): the stage-11 fit's enums, whichever fit is
    adopted."""
    if not _TRACKED:
        _TRACKED.append(Config.fitted())
    return _TRACKED[0].replace(**{**WP58, **kw})


def _events58(cid, **kw):
    """(clock, kind) from the fill of a recorded run under the tracked fit with the WP58 values
    (+ kw), the fill fetch dropped, and the silicon list the same way; the model's list is None
    when it raises (sim.queue.QueueOverflow)."""
    from validation.v35s.chains.sim.machine import refresh_anchor

    family = cid.split("-")[0]
    if family not in _RUNS23:
        _RUNS23[family] = {r["chain"]["id"]: r for r in _runs(family)}
    s = normalize(_RUNS23[family][cid])
    sil = [(e[0], e[1]) for e in aligned(s)][1:]
    try:
        m = simulate_normalized(s.chain, _fit58(**kw), s.chain_base, refresh=refresh_anchor(s))
    except QueueOverflow:
        return None, sil
    return [(e[0], e[1]) for e in aligned(m)][1:], sil


class RefreshOnProbesF27(unittest.TestCase):
    """(WP58, F27) the refresh-on probe family: every F27 chain runs within the queue's six
    bytes, the IN under a refresh, and the I/O steps' enums each against the alternative it
    replaced on a named run, silicon clocks from t_fill quoted from chains-F27-w<N>."""

    def test_every_f27_chain_runs_within_the_queue(self):
        # under DEFAULT and under the fit, at the timer phase the generated chains run with
        # (machine.Machine without an anchor), every wait and parity
        chains = generate(["F27"])
        self.assertEqual(len(chains), 1072)
        for cfg in (DEFAULT, _fit58()):
            peak = 0
            for chain in chains:
                m = Machine(chain, cfg)
                m.run()                  # raises QueueOverflow on an over-fill
                peak = max(peak, m.queue.peak)
            self.assertLessEqual(peak, QUEUE_BYTES)

    def test_in_under_a_refresh(self):
        # F27-push-fc-port-inb-n1-pO-w0: IN AL,40h after a NOP under PUSH; its I/O posted on the
        # port byte's take at 111, the refresh request at 112. Silicon R114 (the I/O's step, its
        # count 4) I121 F124 R131 W136. The old model held the refresh to the I/O's last clock
        # (R118), let the fetch the refresh beat run ahead of the IN with a second one back to
        # back (F123 F126) and over-filled the queue at clock 251 in the END block
        m, s = _events58("F27-push-fc-port-inb-n1-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 110, 136), [(114, "refresh"), (121, "io_read"),
                                              (124, "fetch"), (131, "refresh"),
                                              (136, "stack_write")])
        m, _ = _events58("F27-push-fc-port-inb-n1-pO-w0", **FIT34)
        self.assertIsNone(m)

    def test_refresh_on_the_io_steps(self):
        # refresh_io_step: F27-push-fc-port-inb-n0-pO-w0, the IN's I/O posted at 108, the
        # request at 112 (count 5): silicon R113 (count 6) I118 (any: R115 at the count's end,
        # I120); F27-push-fc-port-indw-n4-pE-w2, IN AL,DW (setup 7, its steps a clock earlier
        # against the post): R128 I135 (any: R132 I137)
        m, s = _events58("F27-push-fc-port-inb-n0-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 109, 125), [(113, "refresh"), (118, "io_read")])
        m, _ = _events58("F27-push-fc-port-inb-n0-pO-w0", refresh_io_step="any")
        self.assertEqual(_span(m, 109, 125), [(115, "refresh"), (120, "io_read")])
        m, s = _events58("F27-push-fc-port-indw-n4-pE-w2")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 122, 140), [(128, "refresh"), (135, "io_read")])
        m, _ = _events58("F27-push-fc-port-indw-n4-pE-w2", refresh_io_step="any")
        self.assertEqual(_span(m, 122, 140), [(132, "refresh"), (137, "io_read")])

    def test_the_steps_own_the_refresh_beside_an_out(self):
        # refresh_io_step=own: F27-out-fc-port-outb-n0-pO-w0, X = OUT 40h,AL posts at 110, the
        # closing OUT starts at 112 and takes its port byte on 115; the request at 112:
        # silicon R113 on X's step, the closing OUT mid-take (step: the EU holds it to the
        # take, F115 R118 I123)
        m, s = _events58("F27-out-fc-port-outb-n0-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 108, 123), [(113, "refresh"), (118, "fetch"),
                                              (122, "io_write")])
        # (WP61) the stage-12 fields at their old values: the alternative as WP58 measured it
        m, _ = _events58("F27-out-fc-port-outb-n0-pO-w0", refresh_io_step="step", **_OLD61,
                         **_OLD85)
        self.assertEqual(_span(m, 108, 123), [(115, "fetch"), (118, "refresh"),
                                              (123, "io_write")])

    def test_the_refresh_last_clock_under_a_step(self):
        # refresh_io_stall=step: F27-push-fc-port-inb-n1-pO-w0, the refresh 114-118 taken at
        # the I/O's count 4: its last clock would complete count 6, a step, and does not count;
        # silicon I121 (waits: I123 behind a fetch at 120)
        m, _ = _events58("F27-push-fc-port-inb-n1-pO-w0", refresh_io_stall="waits")
        self.assertEqual(_span(m, 110, 136), [(114, "refresh"), (120, "fetch"),
                                              (123, "io_read"), (128, "refresh"),
                                              (135, "stack_write")])

    def test_an_in_issues_on_a_step_after_a_refresh(self):
        # io_step_issue: F27-push-fc-port-inb-n1-pE-w0, the refresh on the IN's post clock 104
        # beats a fetch, which runs 109-111; the I/O's count is done at 113, its step after
        # the fetch at 114: silicon I114 (count: I113)
        m, s = _events58("F27-push-fc-port-inb-n1-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 100, 116), [(104, "refresh"), (109, "fetch"),
                                              (114, "io_read")])
        m, _ = _events58("F27-push-fc-port-inb-n1-pE-w0", io_step_issue="count")
        self.assertEqual(_span(m, 100, 116), [(104, "refresh"), (109, "fetch"),
                                              (113, "io_read")])

    def test_no_pair_beside_an_in(self):
        # refresh_io_run=pair_out: the same run, the fetch the refresh beat beside the IN is
        # one word (pair: F109 F112 I115); beside an OUT the pair stays (RefreshIoRunAndTakeLatch)
        m, _ = _events58("F27-push-fc-port-inb-n1-pE-w0", refresh_io_run="pair")
        self.assertEqual(_span(m, 100, 116), [(104, "refresh"), (109, "fetch"),
                                              (112, "fetch"), (115, "io_read")])
        m, s = _events58("F13-c-out-shlcl2-pE-w2")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 95, 113), [(95, "refresh"), (100, "fetch"), (105, "fetch"),
                                             (110, "io_write"), (113, "refresh")])

    def test_a_ready_io_issues_on_the_take_clock(self):
        # port_ready=issue: F27-out-fc-empty-pE-w1, the marker OUT's I/O counted out at 105
        # behind the fetches 102 and 106; the closing OUT takes its port byte on 110, the clock
        # the bus frees: silicon I110 R113 I122 (relatch: held to 113, R111 I116 I126)
        m, s = _events58("F27-out-fc-empty-pE-w1")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 100, 126), [(102, "fetch"), (106, "fetch"), (110, "io_write"),
                                              (113, "refresh"), (122, "io_write"),
                                              (125, "fetch")])
        m, _ = _events58("F27-out-fc-empty-pE-w1", port_ready="relatch", **_OLD61)
        self.assertEqual(_span(m, 100, 126), [(102, "fetch"), (106, "fetch"), (111, "refresh"),
                                              (116, "io_write"), (126, "io_write")])

    def test_the_post_clock_hold_beside_a_beaten_fetch(self):
        # refresh_post=post_beat: F27-push-fc-room-movawi-n0-k1-pE-w0, PUSH AW starts and posts
        # its write at 104 with the refresh 104-108 beating a fetch the write's setup then holds:
        # silicon W111 F114 (post: no hold beside a beaten fetch, W110 F113); F17-c-push-empty-
        # pE-w0, the beaten fetch run ahead of the write (98-100): W101 either way
        m, s = _events58("F27-push-fc-room-movawi-n0-k1-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 102, 117), [(104, "refresh"), (111, "stack_write"),
                                              (114, "fetch"), (117, "fetch")])
        m, _ = _events58("F27-push-fc-room-movawi-n0-k1-pE-w0", refresh_post="post")
        self.assertEqual(_span(m, 102, 117), [(104, "refresh"), (110, "stack_write"),
                                              (113, "fetch"), (116, "fetch")])
        for kw in ({}, {"refresh_post": "post"}):
            m, s = _events58("F17-c-push-empty-pE-w0", **kw)
            self.assertEqual(m, s)
            self.assertEqual(_span(s, 90, 101), [(90, "stack_write"), (93, "refresh"),
                                                 (98, "fetch"), (101, "stack_write")])

    def test_the_end_dw_out_in_halt_is_not_stepped(self):
        # the steps apply while the EU runs: the END's OUT DW,AL, posted with the EU going into
        # HALT, keeps the old rules (F13-s-shlcl1-pE-w0 exact; stepping it loses 103 refresh-on
        # corpus runs)
        from validation.v35s.chains.sim.arbiter import Request, io_stepped

        class _Eu:
            halted = True
        r = Request([("io_write", 0xFF00, "lo")], 7, 0)
        self.assertFalse(io_stepped(r, _Eu()))
        _Eu.halted = False
        self.assertTrue(io_stepped(r, _Eu()))
        m, s = _events58("F13-s-shlcl1-pE-w0")
        self.assertEqual(m, s)

    def test_refresh_off_runs_never_see_the_steps(self):
        for cid in ("F3-out-shl_cl2-k1-pE-w2", "F27-out-ec-port-inb-n1-pO-w0",
                    "F19-d-out-pair-outb-pE-w0"):
            a, s = _events58(cid)
            b, _ = _events58(cid, **FIT34)
            self.assertEqual(a, b, cid)
            self.assertEqual(a, s, cid)

    def test_wp58_defaults_are_the_old_model(self):
        for name in WP58:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)


# (WP61) the stage-12 fields and the values the read found (F28, F29)
WP61 = {"refresh_wb": "free_wait", "refresh_relatch": "issue", "refresh_window": "posted",
        "refresh_start_seam": "start", "refresh_step_lead": "step", "refresh_beat_b2b": "imm",
        "grp_disp": "hold", "dw_lift": "moved"}
_OLD61 = {n: OPTIONS[n][0] for n in WP61}
# (forty-fourth fit) WP85's I/O-sequencer enums at their old values: the WP58/WP61 alternative
# checks below were measured before them
_OLD85 = {n: OPTIONS[n][0] for n in ("port_ready_count", "port_refresh", "refresh_pair_post",
                                      "io_step_restart", "refresh_lead_step")}
WP61_REFRESH = ("refresh_wb", "refresh_relatch", "refresh_window", "refresh_start_seam",
                "refresh_step_lead", "refresh_beat_b2b")


def _events61(cid, **kw):
    """_events58 under the tracked fit with the WP58 and WP61 values (+ kw)."""
    return _events58(cid, **{**WP61, **kw})


class RefreshExitBeatGroupF28F29(unittest.TestCase):
    """(WP61, F28, F29) a unit's exit before an OUT under a refresh, the beaten fetch's committed
    successor, the group forms' displacement hold and the moved DW request's lift: each value
    against the one it replaced on a named run, silicon clocks from t_fill quoted from
    chains-F27/F28/F29-w<N>."""

    def test_every_f28_f29_chain_runs_within_the_queue(self):
        chains = generate(["F28", "F29"])
        self.assertEqual(len(chains), 1088 + 456)
        for cfg in (DEFAULT, _fit58(**WP61)):
            peak = 0
            for chain in chains:
                m = Machine(chain, cfg)
                m.run()                  # raises QueueOverflow on an over-fill
                peak = max(peak, m.queue.peak)
            self.assertLessEqual(peak, QUEUE_BYTES)

    def test_the_write_back_runs_under_the_refresh_hold(self):
        # refresh_wb (state A): F28-out-fc-fence-cl27-n0-pE-w0, the refresh 72-76 over SHL
        # AW,CL's exit and M0's start: silicon F80 R89 I94 (hold: the OUT starts at 77 and
        # waits out the write-back to 79, F82 R87 I95)
        m, s = _events61("F28-out-fc-fence-cl27-n0-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 76, 98), [(80, "fetch"), (89, "refresh"), (94, "io_write"),
                                            (97, "fetch")])
        m, _ = _events61("F28-out-fc-fence-cl27-n0-pE-w0", refresh_wb="hold", **_OLD85)
        self.assertEqual(_span(m, 76, 98), [(82, "fetch"), (87, "refresh"), (95, "io_write"),
                                            (98, "fetch")])

    def test_no_refresh_while_the_out_waits_for_the_write_back(self):
        # refresh_wb=free_wait (state B): F28-out-fc-fence-cl26-n0-pE-w0, the request on M0's
        # start 72, its wbsync 72-73: silicon R74 F79 R88 I93 (free: R72 F77 I86 R89)
        m, s = _events61("F28-out-fc-fence-cl26-n0-pE-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 70, 96), [(74, "refresh"), (79, "fetch"), (88, "refresh"),
                                            (93, "io_write"), (96, "fetch")])
        m, _ = _events61("F28-out-fc-fence-cl26-n0-pE-w0", refresh_wb="free")
        self.assertEqual(_span(m, 70, 96), [(72, "refresh"), (77, "fetch"), (86, "io_write"),
                                            (89, "refresh"), (94, "fetch")])

    def test_the_refresh_waits_for_a_relatched_issue(self):
        # refresh_relatch=issue: the same cl27 run, M0's I/O counted out at 87 and relatched to
        # 89 by the closing OUT's port take at 86, the request at 88: silicon R89 I94 (free:
        # R87 I92)
        m, _ = _events61("F28-out-fc-fence-cl27-n0-pE-w0", refresh_relatch="free")
        self.assertEqual(_span(m, 76, 98), [(80, "fetch"), (87, "refresh"), (92, "io_write"),
                                            (95, "fetch")])

    def test_the_fetch_free_window_as_posted(self):
        # refresh_window=posted: F28-push-fc-tail-shlcl8-outb-n0-pO-w0, M1's PUSH write moved in
        # on the X OUT's issue 158, the request at 160: silicon R162 S167 (need: R164 S169)
        m, s = _events61("F28-push-fc-tail-shlcl8-outb-n0-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 156, 175), [(158, "io_write"), (162, "refresh"),
                                              (167, "stack_write"), (170, "fetch"),
                                              (173, "fetch")])
        m, _ = _events61("F28-push-fc-tail-shlcl8-outb-n0-pO-w0", refresh_window="need")
        self.assertEqual(_span(m, 156, 175), [(158, "io_write"), (164, "refresh"),
                                              (169, "stack_write"), (172, "fetch"),
                                              (175, "fetch")])

    def test_the_start_clock_keeps_its_boundary(self):
        # refresh_start_seam=start: F28-out-fc-beat-adddwi-n1-k1-pE-w0, ADD DW,imm16 starts at
        # 103 taking its ModR/M, the request at 103: silicon R103 F108 (seam: F103 R107)
        m, s = _events61("F28-out-fc-beat-adddwi-n1-k1-pE-w0")
        self.assertEqual(_span(m, 99, 115), _span(s, 99, 115))
        self.assertEqual(_span(s, 99, 109), [(99, "io_write"), (103, "refresh"), (108, "fetch")])
        m, _ = _events61("F28-out-fc-beat-adddwi-n1-k1-pE-w0", refresh_start_seam="seam")
        self.assertEqual(_span(m, 99, 109), [(99, "io_write"), (103, "fetch"), (107, "refresh")])

    def test_the_step_takes_the_refresh_on_the_lead(self):
        # refresh_step_lead=step: F28-out-fc-fence-cl24-n0-pO-w0, the closing OUT's I/O posted
        # at 92 (steps 95, 97), the request at 96: silicon R97 I102 F105 (lead: F97 R100 I105)
        m, s = _events61("F28-out-fc-fence-cl24-n0-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 89, 108), [(89, "io_write"), (97, "refresh"),
                                             (102, "io_write"), (105, "fetch"), (108, "fetch")])
        m, _ = _events61("F28-out-fc-fence-cl24-n0-pO-w0", refresh_step_lead="lead", **_OLD85)
        self.assertEqual(_span(m, 89, 108), [(89, "io_write"), (97, "fetch"), (100, "refresh"),
                                             (105, "io_write"), (108, "fetch")])

    def test_the_beaten_fetch_successor(self):
        # refresh_beat_b2b=imm: F28-out-fc-beat-movawi-n0-k2-pE-w0, R103 F108, the second MOV
        # AW,imm16 in its pre clocks on the delivery clock 111: silicon F112 (none, take: F111);
        # F27-out-fc-room-movawi-n0-k2-pO-w0, the closing OUT starting on 121 right after MOV
        # DW,imm16: silicon F122 (none: F121); F27-push-fc-room-movawi-n0-k3-pE-w0, a MOV
        # starting on the delivery clock: F112 on time under both
        for kw, f in (({}, 112), ({"refresh_beat_b2b": "none"}, 111),
                      ({"refresh_beat_b2b": "take"}, 111)):
            m, s = _events61("F28-out-fc-beat-movawi-n0-k2-pE-w0", **kw)
            self.assertEqual(_span(m, 100, 112)[-1], (f, "fetch"), kw)
        self.assertEqual(_span(s, 100, 116), [(103, "refresh"), (108, "fetch"), (112, "fetch"),
                                              (115, "fetch")])
        m, s = _events61("F27-out-fc-room-movawi-n0-k2-pO-w0")
        self.assertEqual(m, s)
        m, _ = _events61("F27-out-fc-room-movawi-n0-k2-pO-w0", refresh_beat_b2b="none")
        self.assertEqual(_span(m, 113, 122), [(113, "refresh"), (118, "fetch"), (121, "fetch")])
        for kw in ({}, {"refresh_beat_b2b": "none"}):
            m, s = _events61("F27-push-fc-room-movawi-n0-k3-pE-w0", **kw)
            self.assertEqual(m, s)

    def test_an_operand_take_delays_the_successor(self):
        # refresh_beat_b2b=take: F28-out-fc-beat-adddwi-n2-k1-pE-w0, ADD DW,imm16 takes an
        # immediate byte on the delivery clock 111 (no IR load): silicon F112 (none: F111)
        m, s = _events61("F28-out-fc-beat-adddwi-n2-k1-pE-w0", refresh_beat_b2b="take")
        self.assertIn((112, "fetch"), _span(s, 108, 113))
        self.assertIn((112, "fetch"), _span(m, 108, 113))
        m, _ = _events61("F28-out-fc-beat-adddwi-n2-k1-pE-w0", refresh_beat_b2b="none")
        self.assertIn((111, "fetch"), _span(m, 108, 113))

    def test_the_group_displacement_hold(self):
        # grp_disp=hold: INC [BW+200h] under the OUT marker (F29, refresh off). n1 pO: the
        # displacement taken at 92: silicon F95 D98 (none: F92 D98); n0 pO, the take at 83 and
        # M0's I/O 85-87: F91 D94 (none: F88 F91 D94); n1 pE, the take at 91 empties a word:
        # F91 F94 D97 (none: F91 D97)
        cases = (("F29-out-ec-gih-incd16-n1-pO-w0", 85, 99, [(85, "io_write"), (89, "fetch"),
                                                              (92, "fetch"), (98, "data_read")]),
                 ("F29-out-ec-gih-incd16-n0-pO-w0", 85, 95, [(85, "io_write"), (88, "fetch"),
                                                              (91, "fetch"), (94, "data_read")]),
                 ("F29-out-ec-gih-incd16-n1-pE-w0", 84, 98, [(84, "io_write"), (88, "fetch"),
                                                              (91, "fetch"), (97, "data_read")]))
        for cid, lo, hi, old in cases:
            m, s = _events61(cid)
            self.assertEqual(m, s, cid)
            m, _ = _events61(cid, grp_disp="none")
            self.assertEqual(_span(m, lo, hi), old, cid)
        m, s = _events61("F29-out-ec-gih-incd16-n1-pO-w0")
        self.assertEqual(_span(s, 85, 99), [(85, "io_write"), (89, "fetch"), (95, "fetch"),
                                            (98, "data_read")])

    def test_the_moved_dw_request_runs_first(self):
        # dw_lift=moved: F29-out-ec-dio-dw-stbwd8-n0-pO-w0, OUT DW,AL right after M0, moved in
        # on M0's issue 85 where the IR load raises the fetch: silicon I85 I92 F95 (posted:
        # I85 F90 I93)
        m, s = _events61("F29-out-ec-dio-dw-stbwd8-n0-pO-w0")
        self.assertEqual(m, s)
        self.assertEqual(_span(s, 85, 98), [(85, "io_write"), (92, "io_write"), (95, "fetch"),
                                            (98, "data_write")])
        m, _ = _events61("F29-out-ec-dio-dw-stbwd8-n0-pO-w0", dw_lift="posted")
        self.assertEqual(_span(m, 85, 98), [(85, "io_write"), (90, "fetch"), (93, "io_write"),
                                            (98, "data_write")])

    def test_refresh_off_runs_read_no_refresh_field(self):
        # the six refresh enums at their old values change no refresh-off run (they are read
        # only with the refresh machine)
        old = {n: OPTIONS[n][0] for n in WP61_REFRESH}
        for cid in ("F3-out-shl_cl2-k1-pE-w2", "F28-out-ec-fence-cl27-n0-pE-w0",
                    "F28-out-ec-beat-movawi-n0-k2-pE-w0", "F29-out-ec-gih-incd16-n1-pO-w0",
                    "F16-l-out-shli4-pE-w1"):
            a, s = _events61(cid)
            b, _ = _events61(cid, **old)
            self.assertEqual(a, b, cid)
            self.assertEqual(a, s, cid)

    def test_the_group_hold_leaves_other_forms(self):
        # grp_disp: the [BW] forms (F26) and the immediate forms with a displacement keep
        # their timing
        for cid in ("F26-out-gih-inc-n1-pE-w0", "F26-out-gih-inc-n2-pO-w0"):
            a, s = _events61(cid)
            b, _ = _events61(cid, grp_disp="none")
            self.assertEqual(a, b, cid)
            self.assertEqual(a, s, cid)

    def test_wp61_defaults_are_the_old_model(self):
        for name in WP61:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
            self.assertIn(WP61[name], OPTIONS[name], name)


# (WP70, F24) the new string enums at their found values and the integers the stage-13 fit moved
# with them; equal to Config.fitted() once the fit is adopted (replace is then a no-op)
WP70 = {"str_last": "all", "str_io_latch": "write", "str_count": "dw"}
WP70_INTS = {"str_move.setup": 9, "str_cmp.setup": 9, "str_store.setup": 11, "str_load.setup": 9,
             "str_load.exec": 2, "str_scan.setup": 10, "str_out.setup": 10}


def _f24(cid, **over):
    """(silicon, model) event lists from t_fill under the tracked fit with WP70 (+ over)."""
    run = next(r for r in _runs("F24") if r["chain"]["id"] == cid)
    s = normalize(run)
    cfg = Config.fitted().replace(**{**WP70, **WP70_INTS, **over})
    m = simulate_normalized(s.chain, cfg, s.chain_base)
    return [e[:2] for e in aligned(s)], [e[:2] for e in aligned(m)]


class StringForms(unittest.TestCase):
    """(WP67, F24) the string and block forms: decode (a REP prefix is part of the form, the
    str_* class with the prefix byte), the template per class (the element's cycles in bus
    order at the walk's addresses), the REP compare's overrun (str_overrun), CW = 0 (no
    element: zexit), the odd word's split, REP against the single form, and the F24 chains
    simulate."""

    REGS = {**FORMS_REGS, "AW": 0, "CW": 3, "DW": 0x40, "IX": 0x0A40, "IY": 0x0C40}
    CLASSES = ("str_move", "str_cmp", "str_store", "str_load", "str_scan", "str_in", "str_out")

    def _chain(self, cid):
        return next(c for c in generate(["F24"], waits=(int(cid[-1]),),
                                        parities=("even" if "-pE-" in cid else "odd",))
                    if c.id == cid)

    def test_decode(self):
        from validation.v35s.chains.forms import F24_STRING_FORMS, STRING_FORMS
        for name in F24_STRING_FORMS:
            form, sop = FORMS[name], STRING_FORMS[name]
            op = decode(form.code, 0, dict(self.REGS))
            self.assertEqual((op.cls, op.length, op.width), (form.cls, len(form.code), sop.width),
                             name)
            self.assertEqual(op.rep, form.code[0] if sop.rep else None, name)
            self.assertEqual(op.n, 3 if sop.rep else 1, name)       # CW, or one element
            self.assertEqual((op.ix, op.iy), (0x0A40, 0x0C40), name)
            self.assertEqual(op.port, 0x40 if form.cls in ("str_in", "str_out") else None, name)
        # a segment prefix stays its own pseudo-instruction; F2 / F3 only before a string opcode
        self.assertEqual(decode(bytes([0x26, 0xA5]), 0, dict(self.REGS)).cls, "prefix")

    def test_execute_steps_the_registers(self):
        from validation.v35s.chains.sim.templates import execute
        regs = dict(self.REGS)
        code = FORMS["rep_movbk_w"].code
        execute(decode(code, 0, regs), code, regs)
        self.assertEqual((regs["IX"], regs["IY"], regs["CW"]), (0x0A46, 0x0C46, 0))
        regs = dict(self.REGS)
        code = FORMS["stm_b"].code
        execute(decode(code, 0, regs), code, regs)
        self.assertEqual((regs["IX"], regs["IY"], regs["CW"]), (0x0A40, 0x0C41, 3))

    def _data(self, op, cfg=DEFAULT):
        from validation.v35s.chains.sim.templates import steps
        return [s[1:3] for s in steps(op, cfg) if s[0] == "data"]

    def test_template_per_class_matches_the_walk(self):
        """Every F24 r-series chain at n = 3: the template's data steps, in order, are the
        normaliser's expected accesses of the form (the overrun included with
        str_overrun=read)."""
        from validation.v35s.chains.forms import STRING_FORMS
        from validation.v35s.chains.normalize import string_elements
        cfg = DEFAULT.replace(str_overrun="read")
        kinds = {"read": "data_read", "write": "data_write", "io_read": "io_read",
                 "io_write": "io_write"}
        seen = set()
        for chain in generate(["F24"], waits=(0,), parities=("even",)):
            if "-r-" not in chain.id or not chain.id.endswith("-n3-pE-w0"):
                continue
            k = next((k for k, i in enumerate(chain.instrs) if i.role == "x"
                      and i.form in STRING_FORMS), None)
            if k is None:
                continue                         # the MOV CW,n control
            run = string_elements(chain)[k]
            op = decode(FORMS[chain.instrs[k].form].code, 0, dict(self.REGS))
            op.n, op.cond = len(run.elements), run.cond
            got = [(kinds[kind], addr) for kind, addr in self._data(op, cfg)]
            want = [(a.kind, a.addr) for e in run.elements for a in e] + [
                (a.kind, a.addr) for a in run.overrun]
            self.assertEqual(got, want, chain.id)
            seen.add(op.cls)
        self.assertEqual(seen, set(self.CLASSES))

    def test_overrun_is_the_compares_and_off_by_default(self):
        for name, compare in (("repe_cmpbk_w", True), ("repne_cmpm_b", True),
                              ("rep_ldm_w", False), ("rep_movbk_b", False)):
            op = decode(FORMS[name].code, 0, dict(self.REGS))
            plain = self._data(op)
            over = self._data(op, DEFAULT.replace(str_overrun="read"))
            per = len(plain) // 3
            self.assertEqual(len(over), len(plain) + (per if compare else 0), name)
            if compare:
                # the next element's reads at the next addresses, after the last element
                w = op.width
                self.assertEqual([a for _, a in over[-per:]],
                                 [a + w for _, a in plain[-per:]], name)

    def test_cw_zero_runs_no_element(self):
        from validation.v35s.chains.sim.templates import steps
        cfg = DEFAULT.replace(**{"str_store.zexit": 7})
        op = decode(FORMS["rep_stm_w"].code, 0, {**self.REGS, "CW": 0})
        seq = steps(op, cfg)
        self.assertFalse([s for s in seq if s[0] == "data"])
        self.assertEqual(seq[-1], ("clocks", 7))
        chain = self._chain("F24-out-r-rep-movbk-w-n0-pE-w0")
        self.assertFalse([e for e in simulate(chain) if e.kind.startswith("data")])

    def test_rep_against_the_single_form(self):
        from validation.v35s.chains.sim.templates import steps
        single = steps(decode(FORMS["movbk_w"].code, 0, dict(self.REGS)), DEFAULT)
        rep = steps(decode(FORMS["rep_movbk_w"].code, 0, dict(self.REGS)), DEFAULT)
        self.assertFalse([s for s in single if s[0] == "take"])     # no operand byte
        self.assertEqual(rep[0][:2], ("take", 1))                   # the opcode after F3
        self.assertEqual(steps(decode(FORMS["rep_movbk_w"].code, 0, dict(self.REGS)),
                               DEFAULT.replace(str_take="chain"))[0], ("take", 1, "chain"))
        quiet = steps(decode(FORMS["rep_movbk_w"].code, 0, dict(self.REGS)),
                      DEFAULT.replace(str_take="quiet", str_setup="nowait"))
        self.assertEqual(quiet[:2], [("take", 1, "chain"), ("quiet",)])
        self.assertEqual(quiet[2][0], "nowait")                    # rpre, not in wait states
        self.assertEqual(rep[1][0], "clocks")
        self.assertEqual(len([s for s in single if s[0] == "data"]), 2)
        self.assertEqual(len([s for s in rep if s[0] == "data"]), 6)
        # the exit: rexit when CW ran out, cexit when a compare's condition ended it
        cfg = DEFAULT.replace(**{"str_scan.rexit": 5, "str_scan.cexit": 4})
        op = decode(FORMS["repe_cmpm_w"].code, 0, dict(self.REGS))
        self.assertEqual(steps(op, cfg)[-1], ("clocks", 5))
        op.cond = True
        self.assertEqual(steps(op, cfg)[-1], ("clocks", 4))

    def test_walk_count_and_exit_reach_the_eu(self):
        """The early exit on the condition comes from the chain walk: REPE CMPM on the fill
        compares one element at CW = 4 (and with the overrun reads one more)."""
        chain = self._chain("F24-out-t-repe-cmpm-w-n4-fill-pE-w0")
        cfg = Config.fitted().replace(str_overrun="read")
        reads = [e for e in simulate(chain, cfg) if e.kind == "data_read"]
        self.assertEqual([e.addr for e in reads], [0x0C40, 0x0C42])
        m = Machine(chain, cfg)
        self.assertEqual(list(m.eu.strings.values()), [(1, True)])

    def test_odd_word_split(self):
        chain = self._chain("F24-out-a-rep-movbk-w-n1-ixiy-pE-w0")
        data = [(e.kind, e.addr, e.width) for e in simulate(chain)
                if e.kind.startswith("data")]
        self.assertEqual(data, [("data_read", 0x0A41, "hi"), ("data_read", 0x0A42, "lo"),
                                ("data_write", 0x0C41, "hi"), ("data_write", 0x0C42, "lo")])

    def test_f24_simulates(self):
        for chain in generate(["F24"], waits=(0, 1, 2)):
            with self.subTest(chain=chain.id):
                for cfg in (DEFAULT, Config.fitted()):
                    events = simulate(chain, cfg)
                    self.assertEqual(events[-1].kind, "io_write")
                    self.assertEqual(events[-1].addr, 0xFF00)

    def test_defaults_are_the_old_model(self):
        for name in ("str_take", "str_setup", "str_overrun", "str_hold"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        for cls in self.CLASSES:
            self.assertIn(cls, DEFAULT.cost, cls)

    def test_wp70_defaults_are_the_old_model(self):
        """(WP70) the new enums' DEFAULT is the old model."""
        for name in WP70:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
            self.assertIn(WP70[name], OPTIONS[name], name)

    def test_str_last_single_outm_io(self):
        # the read at 94, the OUTM's I/O (its one element is the CW-ending one) at 103
        sil, mod = _f24("F24-out-s-outm-b-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((103, "io_write"), mod)
        _, rep = _f24("F24-out-s-outm-b-k1-pE-w0", str_last="rep")
        self.assertIn((102, "io_write"), rep)
        self.assertNotIn((103, "io_write"), rep)

    def test_str_io_latch_holds_the_closing_outs_fetch(self):
        # OUTM's I/O 103-105, then the closing OUT (a port form) waits for the data latch:
        # the fetch at 107; a second OUTM after it (no port byte) lets it go at 106
        sil, mod = _f24("F24-out-s-outm-b-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((107, "fetch"), mod)
        _, none = _f24("F24-out-s-outm-b-k1-pE-w0", str_io_latch="none")
        self.assertIn((106, "fetch"), none)
        sil2, mod2 = _f24("F24-out-s-outm-b-k2-pE-w0")
        self.assertEqual(mod2[:6], sil2[:6])
        self.assertIn((106, "fetch"), sil2)

    def test_str_count_pairs(self):
        # STM pair: the first moves in on M0's I/O issue 84 and writes at 95; the second's
        # write at D1end+11 (pO, 109) and D1end+12+w (pE, the fetch on its post clock: 109)
        for cid, want in (("F24-out-s-stm-b-k2-pE-w0", (109, "data_write")),
                          ("F24-out-s-stm-b-k2-pO-w0", (109, "data_write")),
                          ("F24-out-s-stm-b-k2-pE-w2", (115, "data_write")),
                          ("F24-out-s-ldm-b-k2-pE-w1", (110, "data_read"))):
            sil, mod = _f24(cid)
            self.assertEqual(mod, sil, cid)
            self.assertIn(want, mod, cid)
            _, data = _f24(cid, str_count="data")
            self.assertNotEqual(data, sil, cid)

    def test_str_count_leaves_the_rep_streams(self):
        # no fetch inside a REP stream: the REP series is the same under both counts
        for cid in ("F24-out-r-rep-stm-w-n4-pE-w1", "F24-out-r-rep-movbk-b-n2-pO-w2"):
            self.assertEqual(_f24(cid)[1], _f24(cid, str_count="data")[1], cid)


# (WP72, F23, F25) the new enums at their found values, imm_latch's flip and the integers the
# stage-14 fit moved with them; equal to Config.fitted() once the fit is adopted (replace is
# then a no-op)
WP72 = {"xfer_abort": "word", "cond_gap": "own", "burst_count": "dw", "lea_io": "recover",
        "lea_room": "ir", "prepare_sync": "run"}
WP72_FLIPS = {"imm_latch": "wait"}
WP72_INTS = {"branch_short.cfgap": 8, "push_r.setup": 9, "prepare.exec": 11, "prepare.wb": 2,
             "dispose.setup": 7, "lea.nx": 0}


def _ev72(cid, **over):
    """(silicon, model) event lists from t_fill under the tracked fit with WP72 (+ over)."""
    run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
    s = normalize(run)
    cfg = Config.fitted().replace(**{**WP72, **WP72_FLIPS, **WP72_INTS, **over})
    m = simulate_normalized(s.chain, cfg, s.chain_base)
    return [e[:2] for e in aligned(s)], [e[:2] for e in aligned(m)]


class TransferAndFrameMisses(unittest.TestCase):
    """(WP72) F23's and F25's misses of the thirty-ninth fit: each new enum against its
    alternative on its deciding run (clocks rel t_fill)."""

    def test_wp72_defaults_are_the_old_model(self):
        for name in WP72:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
            self.assertIn(WP72[name], OPTIONS[name], name)
        self.assertEqual(OPTIONS["imm_latch"], ("free", "wait"))

    def test_xfer_abort_br_short_at_odd_room(self):
        # BR short starts on 81 with its displacement's take and the IR load, 3 bytes of room:
        # the aborted cycle 81-83, the fetch on 84
        sil, mod = _ev72("F23-push-br-n0-pO-w0")
        self.assertEqual(mod, sil)
        self.assertIn((84, "fetch"), mod)
        _, none = _ev72("F23-push-br-n0-pO-w0", xfer_abort="none")
        self.assertIn((81, "fetch"), none)
        self.assertNotIn((84, "fetch"), none)
        # pE: 4 bytes of room, the fetch on the start clock either way
        sil, mod = _ev72("F23-push-br-n0-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((81, "fetch"), mod)

    def test_cond_gap_be_target_fetch(self):
        # the last pre-flush fetch 94-98: BE's target fetch at its end + 9
        sil, mod = _ev72("F23-out-be-n0-pE-w2")
        self.assertEqual(mod, sil)
        self.assertIn((107, "fetch"), mod)
        _, fgap = _ev72("F23-out-be-n0-pE-w2", cond_gap="fgap")
        self.assertIn((106, "fetch"), fgap)
        # BR short (no condition field) is the same under both: its target at end + 6
        a = _ev72("F23-out-br-n0-pE-w2")
        self.assertEqual(a[1], a[0])
        self.assertEqual(_ev72("F23-out-br-n0-pE-w2", cond_gap="fgap")[1], a[1])

    def test_burst_count_push_r_first_write(self):
        # PUSH R from M0's write end: the first write 9 counted clocks on (pO 89; pE w1 a fetch
        # on the start clock, its start clock and wait state not counted: 92)
        for cid, want in (("F25-push-pushr-pO-w0", (89, "stack_write")),
                          ("F25-push-pushr-pE-w1", (92, "stack_write"))):
            sil, mod = _ev72(cid)
            self.assertEqual(mod, sil, cid)
            self.assertIn(want, mod, cid)
        # data needs setup 10 under OUT (the write moves in on M0's I/O issue 84 and goes at
        # 93) and 9 under PUSH at pO: no one setup serves both
        _, data = _ev72("F25-push-pushr-pO-w0", burst_count="data", **{"push_r.setup": 10})
        self.assertIn((90, "stack_write"), data)
        sil, mod = _ev72("F25-out-pushr-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((93, "stack_write"), mod)
        _, data = _ev72("F25-out-pushr-pE-w0", burst_count="data")
        self.assertIn((92, "stack_write"), data)

    def test_lea_io_after_the_io_recovery(self):
        # LDEA [BW] on M0's I/O issue 85 (pO): its EA clocks after the I/O and its recovery
        sil, mod = _ev72("F25-out-ldea-bw-pO-w0")
        self.assertEqual(mod, sil)
        self.assertIn((103, "io_write"), mod)
        _, free = _ev72("F25-out-ldea-bw-pO-w0", lea_io="free")
        self.assertIn((102, "io_write"), free)

    def test_lea_room_ir_during_the_ea_clocks(self):
        # LDEA [BW] at pO: the fetch on 84 with M1's PUSH in the IR, M1's write 93
        sil, mod = _ev72("F25-push-ldea-bw-pO-w0")
        self.assertEqual(mod, sil)
        self.assertIn((84, "fetch"), mod)
        self.assertIn((93, "stack_write"), mod)
        _, none = _ev72("F25-push-ldea-bw-pO-w0", lea_room="none")
        self.assertIn((92, "stack_write"), none)
        self.assertNotIn((84, "fetch"), none)

    def test_prepare_sync_on_the_refill_run(self):
        # M1's write at the second refill fetch's end + 18 at every wait
        for cid, want in (("F25-push-prepare-pE-w0", (117, "stack_write")),
                          ("F25-push-prepare-pE-w1", (121, "stack_write")),
                          ("F25-push-prepare-pE-w2", (126, "stack_write"))):
            sil, mod = _ev72(cid)
            self.assertEqual(mod, sil, cid)
            self.assertIn(want, mod, cid)
        sil, take = _ev72("F25-push-prepare-pE-w0", prepare_sync="take")
        self.assertNotEqual(take, sil)
        # under OUT the closing OUT waits for PREPARE's write-back (prepare.wb)
        sil, mod = _ev72("F25-out-prepare-pE-w1")
        self.assertEqual(mod, sil)
        self.assertNotEqual(_ev72("F25-out-prepare-pE-w1", **{"prepare.wb": 0})[1], sil)

    def test_imm_latch_push_imm_behind_the_out(self):
        # M0's I/O at 85: PUSH imm8's stack write at I+9, imm16's at I+10
        for cid, want in (("F25-out-push_imm8-pO-w0", (94, "stack_write")),
                          ("F25-out-push_imm16-pO-w0", (95, "stack_write"))):
            sil, mod = _ev72(cid)
            self.assertEqual(mod, sil, cid)
            self.assertIn(want, mod, cid)
        _, free = _ev72("F25-out-push_imm8-pO-w0", imm_latch="free")
        self.assertIn((91, "stack_write"), free)


# (WP76, F30, F31) the facts-only shapes the probe families read: the new enums as the hand
# start of the forty-first fit has them, with the integers they read
WP76 = {"xfer_odd": "idle", "str_exit": "wb", "str_split": "floor", "str_io_setup": "run",
        "str_start": "skip", "str_fetch": "hold", "sreg_io": "hold", "sreg_store": "own",
        "lea_disp": "split"}
WP76_INTS = {**{f"{c}.xwb": 2 for c in ("str_move", "str_cmp", "str_store", "str_load",
                                         "str_scan", "str_in", "str_out")},
             **{f"{c}.xsplit": 4 for c in ("str_move", "str_cmp", "str_store", "str_load",
                                            "str_scan", "str_in", "str_out")},
             **{f"{c}.xfetch": 8 for c in ("str_move", "str_cmp", "str_store", "str_load",
                                            "str_scan", "str_in")},
             "str_out.xfetch": 9, "str_out.nx": 0,
             "str_move.zfetch": 6, "str_cmp.zfetch": 6, "str_store.zfetch": 6,
             "str_load.zfetch": 5, "str_scan.zfetch": 6, "str_in.zfetch": 7, "str_out.zfetch": 7}


def _ev76(cid, **over):
    """(silicon, model) event lists from t_fill under the tracked fit with WP76 (+ over)."""
    run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
    s = normalize(run)
    cfg = Config.fitted().replace(**{**WP76, **WP76_INTS, **over})
    m = simulate_normalized(s.chain, cfg, s.chain_base)
    return [e[:2] for e in aligned(s)], [e[:2] for e in aligned(m)]


class ProbeShapes(unittest.TestCase):
    """(WP76) F30's and F31's readings as mechanisms: each new enum against its alternative on
    its deciding run (clocks rel t_fill), and REPC / REPNC decoded as REP prefixes."""

    def test_wp76_defaults_are_the_old_model(self):
        for name in WP76:
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
            self.assertIn(WP76[name], OPTIONS[name], name)
        for cls in ("str_move", "str_cmp", "str_store", "str_load", "str_scan", "str_in",
                    "str_out"):
            for name in ("xwb", "xsplit", "xfetch", "zfetch"):
                self.assertEqual(DEFAULT.c(cls, name), 0, (cls, name))

    def test_xfer_odd_short_jump_on_an_idle_bus(self):
        # BR short at 1004F starts on M0's I/O issue 87, no fetch on the bus: the target's
        # fetch at 98 is the next
        sil, mod = _ev76("F30-out-br-short-n0-pad1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertNotIn((90, "fetch"), mod)
        _, hold = _ev76("F30-out-br-short-n0-pad1-pE-w0", xfer_odd="hold")
        self.assertIn((90, "fetch"), hold)
        # an even-address BR short and BR near at an odd address are the same under both
        for cid in ("F30-out-br-short-n0-nop-pE-w0", "F23-out-brnear-n0-pO-w0"):
            sil, mod = _ev76(cid)
            self.assertEqual(mod, sil, cid)
            self.assertEqual(_ev76(cid, xfer_odd="hold")[1], mod, cid)

    def test_str_exit_write_back(self):
        # REP STM's write 112-114, a NOP after it: silicon's next fetch 132, M1's I/O 139
        sil, mod = _ev76("F31-out-alf-stm-n1-nop-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((132, "fetch"), mod)
        self.assertIn((139, "io_write"), mod)
        _, eu = _ev76("F31-out-alf-stm-n1-nop-pE-w0", str_exit="eu")
        self.assertIn((134, "fetch"), eu)
        # M1 (a port-form OUT, wbsync) straight after: the same under both
        sil, mod = _ev76("F31-out-alf-stm-n1-end-pE-w0")
        self.assertEqual(mod, sil)
        self.assertEqual(_ev76("F31-out-alf-stm-n1-end-pE-w0", str_exit="eu")[1], mod)

    def test_str_split_floor(self):
        # the split write 112-114, 115-117 at w0: silicon's next fetch 139, M1's I/O 142
        sil, mod = _ev76("F30-out-odd-stm-iy-n1-end-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((139, "fetch"), mod)
        _, none = _ev76("F30-out-odd-stm-iy-n1-end-pE-w0", str_split="none")
        self.assertIn((138, "fetch"), none)
        # at w1 the end + 1 bound holds: the same under both; LDM with IX odd (a single read)
        for cid in ("F30-out-odd-stm-iy-n1-end-pE-w1", "F30-out-odd-ldm-ix-n1-end-pE-w0"):
            sil, mod = _ev76(cid)
            self.assertEqual(mod, sil, cid)
            self.assertEqual(_ev76(cid, str_split="none")[1], mod, cid)

    def test_str_io_setup_wait_clock_of_the_refill_run(self):
        # the refill 89, 93, 97 back to back, REP INM's setup from 97: the I/O at 115
        sil, mod = _ev76("F30-out-str-inm-w-n1-l0-pE-w1")
        self.assertEqual(mod, sil)
        self.assertIn((115, "io_read"), mod)
        _, nowait = _ev76("F30-out-str-inm-w-n1-l0-pE-w1", str_io_setup="nowait")
        self.assertIn((116, "io_read"), nowait)
        # STM in the same frame counts no wait clock either way
        sil, mod = _ev76("F30-out-str-stm-w-n1-l0-pE-w1")
        self.assertEqual(mod, sil)
        self.assertEqual(_ev76("F30-out-str-stm-w-n1-l0-pE-w1", str_io_setup="nowait")[1], mod)

    def test_str_start_and_fetch_after_a_long_gap(self):
        # REP STM starts at 120 after SHL AW,8 (the aborted cycle 120-122): the write at 140,
        # the fetch the aborted cycle left at the write's end + 9 (151)
        sil, mod = _ev76("F30-out-str-stm-w-n1-sep-pO-w0")
        self.assertEqual(mod, sil)
        self.assertIn((140, "data_write"), mod)
        self.assertIn((151, "fetch"), mod)
        _, count = _ev76("F30-out-str-stm-w-n1-sep-pO-w0", str_start="count")
        self.assertIn((141, "data_write"), count)
        _, room = _ev76("F30-out-str-stm-w-n1-sep-pO-w0", str_fetch="room")
        self.assertNotIn((151, "fetch"), room)
        # CW = 0: the request raised zfetch clocks into the exit (132)
        sil, mod = _ev76("F30-out-str-stm-w-n0-sep-pO-w0")
        self.assertEqual(mod, sil)
        self.assertIn((132, "fetch"), mod)
        self.assertNotIn((132, "fetch"), _ev76("F30-out-str-stm-w-n0-sep-pO-w0",
                                               str_fetch="room")[1])

    def test_sreg_io_8e_behind_the_out(self):
        # 8E decoded behind M0 before its I/O counted out (84): the I/O at 85
        sil, mod = _ev76("F30-out-seg-8e-ds1-aw-n0-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((85, "io_write"), mod)
        _, free = _ev76("F30-out-seg-8e-ds1-aw-n0-pE-w0", sreg_io="free")
        self.assertIn((84, "io_write"), free)
        # pO: the I/O waits behind a fetch to 85 anyway; 8C after the OUT: no hold
        for cid in ("F30-out-seg-8e-ds1-aw-n0-pO-w0", "F30-out-seg-8c-aw-ds1-n0-pE-w0"):
            sil, mod = _ev76(cid)
            self.assertEqual(mod, sil, cid)
            self.assertEqual(_ev76(cid, sreg_io="free")[1], mod, cid)

    def test_sreg_store_datum_a_clock_later(self):
        # MOV [BW],DS1 behind M0's I/O 85-87: the write at 91 (MOV [BW],AW's 90)
        sil, mod = _ev76("F30-out-seg-8c-bw-ds1-n0-pO-w0")
        self.assertEqual(mod, sil)
        self.assertIn((91, "data_write"), mod)
        _, store = _ev76("F30-out-seg-8c-bw-ds1-n0-pO-w0", sreg_store="store")
        self.assertIn((90, "data_write"), store)
        # behind a fetch (posted on its last clock) the same under both
        sil, mod = _ev76("F30-push-seg-8c-bw-ds1-n0-pE-w0")
        self.assertEqual(mod, sil)
        self.assertEqual(_ev76("F30-push-seg-8c-bw-ds1-n0-pE-w0", sreg_store="store")[1], mod)

    def test_lea_disp_split_displacement(self):
        # LDEA [BW+200h] at 1004D (the d16 across two words), the refill 82, 86, 90 back to
        # back: M1's PUSH write at the third fetch's end + 7 (100)
        sil, mod = _ev76("F30-push-lea-bw_d16-k1-pE-w1")
        self.assertEqual(mod, sil)
        self.assertIn((100, "stack_write"), mod)
        _, none = _ev76("F30-push-lea-bw_d16-k1-pE-w1", lea_disp="none")
        self.assertIn((96, "stack_write"), none)
        # pO: the d16 in one word, the same under both
        sil, mod = _ev76("F30-push-lea-bw_d16-k1-pO-w1")
        self.assertEqual(mod, sil)
        self.assertEqual(_ev76("F30-push-lea-bw_d16-k1-pO-w1", lea_disp="none")[1], mod)

    def test_repc_repnc_decode_as_rep_prefixes(self):
        from validation.v35s.chains.sim.templates import REP_PREFIXES
        for code, rep in ((bytes([0x65, 0xA7]), 0x65), (bytes([0x64, 0xAF]), 0x64)):
            op = decode(code, 0, {"AW": 0, "BW": 0, "CW": 3, "DW": 0x40, "SP": 0xF00, "BP": 0,
                                  "IX": 0xA40, "IY": 0xC40})
            self.assertEqual((op.length, op.rep, op.n), (2, rep, 3))
            self.assertIn(op.cls, ("str_cmp", "str_scan"))
        self.assertIn(0x64, REP_PREFIXES)
        self.assertIn(0x65, REP_PREFIXES)

    def test_repc_repnc_carry_exit_through_the_simulator(self):
        # F33 (generator-only: STC / CLC are not decoded) with its flag byte as a NOP: the
        # model's data cycles are silicon's, the exit the carry's (the walk's), not Z's: REPC
        # CMPBK on the fill stops after element 1 (no borrow), REPNC CMPBK runs CW out, REPNC
        # CMPM stops after element 1 (0 - 9090h borrows)
        import dataclasses
        nop = bytes([0x90])
        for cid, reads in (("F33-out-repc-cmpbk-w-n4-clc-pE-w0", 4),
                           ("F33-out-repnc-cmpbk-w-n4-clc-pE-w0", 10),
                           ("F33-out-repnc-cmpm-w-n4-stc-pE-w0", 2),
                           ("F33-out-repc-cmpm-w-n4-clc-pat-pE-w0", 3)):
            run = next(r for r in _runs("F33") if r["chain"]["id"] == cid)
            s = normalize(run)
            ch = dataclasses.replace(s.chain, instrs=[
                dataclasses.replace(i, code=nop, form="nop") if i.form in ("stc", "clc") else i
                for i in s.chain.instrs])
            m = simulate_normalized(ch, Config.fitted().replace(**WP76, **WP76_INTS),
                                    s.chain_base)
            a = [e[1:4] for e in aligned(s) if e[1].startswith("data")]
            b = [e[1:4] for e in aligned(m) if e[1].startswith("data")]
            self.assertEqual(b, a, cid)
            self.assertEqual(len(a), reads, cid)


class PageAndMiscellanyDecode(unittest.TestCase):
    """(WP78) F32's 0F page and F33's register miscellany: every form decodes to its catalog
    class and length, runs a template, and changes the registers a later form reads."""

    REGS = {"AW": 0x1234, "BW": 0x0800, "CW": 0x001F, "DW": 0x0608, "SP": 0x0F00, "BP": 0x0A00,
            "IX": 0x0A40, "IY": 0x0C40, "DS0": 0, "DS1": 0, "SS": 0}

    def test_every_form_decodes_to_its_class(self):
        from validation.v35s.chains.forms import F32_FORMS, F33_FORMS
        from validation.v35s.chains.sim.templates import steps
        for name in F32_FORMS + F33_FORMS:
            form = FORMS[name]
            regs = dict(self.REGS)
            k, ops = 0, []
            while k < form.length:
                op = decode(form.code, k, regs)
                ops.append(op)
                k += op.length
            self.assertEqual(k, form.length, name)
            op = ops[-1]                 # after a segment prefix (pfx_*: its own class)
            self.assertEqual(op.cls, form.cls, name)
            self.assertTrue(steps(op, DEFAULT), name)

    def test_page_and_operands(self):
        from validation.v35s.chains.sim.templates import BASE_CLASS, base_class
        regs = dict(self.REGS)
        op = decode(FORMS["set1_mw_cl_bw_d16"].code, 0, regs)
        self.assertEqual((op.cls, op.page, op.modrm, op.ea, op.mode_class, op.disp, op.cl_count),
                         ("bit1_rmw", 1, True, 0x0A00, "base_disp", 2, True))
        op = decode(FORMS["not1_mb_imm"].code, 0, regs)
        self.assertEqual((op.cls, op.width, op.imm_bytes, op.cl_count), ("bit1_rmw", 1, 1, False))
        op = decode(FORMS["add4s"].code, 0, {**regs, "CW": 0x0008})
        self.assertEqual((op.cls, op.n, op.ix, op.iy, op.width), ("bcd4s", 4, 0x0A40, 0x0C40, 1))
        self.assertEqual(decode(FORMS["cmp4s"].code, 0, {**regs, "CW": 3}).n, 2)
        op = decode(FORMS["mul_aw_m_imm8"].code, 0, regs)
        self.assertEqual((op.cls, op.ea, op.imm_bytes, op.signed), ("mul_imm", 0x0800, 1, True))
        self.assertEqual(decode(FORMS["mul_cw"].code, 0, regs).cls, "mul")
        self.assertEqual((decode(FORMS["incb_m"].code, 0, regs).cls,
                          decode(FORMS["incb_m"].code, 0, regs).width), ("rmw", 1))
        # every class with a base runs the base's structure (eu.py)
        self.assertEqual(base_class("adjust_b"), "reg")
        self.assertEqual(base_class("convert"), "imm")
        self.assertEqual(base_class("bit1_clr"), "rmw")
        self.assertEqual(base_class("bcd4s"), "bcd4s")
        # (WP88) and the F35 / F36 classes' bases: the transfers', the load's, POP's
        self.assertEqual(set(BASE_CLASS.values()), {"reg", "imm", "load_alu", "rmw", "mul",
                                                    "dbnz", "ret", "call", "branch_near",
                                                    "load", "pop"})

    def test_bit_field_cost_and_registers(self):
        from validation.v35s.chains.sim.templates import bf_cost, execute
        # docs/v35s-eu-timing.md's formula at F32's seven cases
        for op, o, w, cost in (("bf_ext", 0, 6, 83), ("bf_ext", 8, 6, 67), ("bf_ext", 8, 8, 77),
                               ("bf_ext", 8, 0, 91), ("bf_ext", 0, 7, 79), ("bf_ext", 8, 7, 63),
                               ("bf_ext", 8, 11, 77), ("bf_ins", 0, 6, 92), ("bf_ins", 8, 6, 94),
                               ("bf_ins", 8, 8, 128), ("bf_ins", 8, 7, 86),
                               ("bf_ins", 8, 11, 140), ("bf_ins", 0, 15, 84)):
            self.assertEqual(bf_cost(op, o, w), cost, (op, o, w))
        # EXT DL,DH (0F 33 F2): offset DL = 8, width DH = 6; then DL = 15, IX unchanged; the
        # second instance at offset 15 crosses into the next word, IX steps by 2
        regs = dict(self.REGS)
        code = FORMS["ext_dl_dh"].code
        op = decode(code, 0, regs)
        self.assertEqual(op.bf, (8, 6, False, 67))
        execute(op, code, regs)
        self.assertEqual((regs["DW"] & 0xFF, regs["IX"]), (15, 0x0A40))
        op = decode(code, 0, regs)
        self.assertEqual(op.bf[:3], (15, 6, True))
        execute(op, code, regs)
        self.assertEqual((regs["DW"] & 0xFF, regs["IX"]), (6, 0x0A42))
        # the registers are used whole: DL = 78h is not reduced to 8
        op = decode(code, 0, {**self.REGS, "DW": 0x5678})
        self.assertEqual(op.bf[:3], (0x78, 0x56, True))
        # INS BH,BL: the offset in ModR/M bits 2:0 (BH = 8), the width in bits 5:3 (BL = 0)
        op = decode(FORMS["ins_bh_bl"].code, 0, dict(self.REGS))
        self.assertEqual(op.bf[:3], (8, 0, False))

    def test_register_effects(self):
        from validation.v35s.chains.sim.templates import execute

        def run(name, **regs):
            r = {**self.REGS, **regs}
            code = FORMS[name].code
            execute(decode(code, 0, r), code, r)
            return r
        self.assertEqual(run("inc_sp")["SP"], 0x0F01)
        self.assertEqual(run("dec_iy")["IY"], 0x0C3F)
        self.assertEqual(run("dec_al", AW=0x1200)["AW"], 0x12FF)
        self.assertEqual(run("inc_dh")["DW"], 0x0708)
        self.assertEqual(run("cvtbw", AW=0x0080)["AW"], 0xFF80)
        self.assertEqual(run("cvtwl", AW=0x8080)["DW"], 0xFFFF)
        self.assertEqual(run("cvtbd", AW=0x0023)["AW"], 0x0305)
        self.assertEqual(run("cvtdb", AW=0x0305)["AW"], 0x0023)
        r = run("mul_cw", AW=0xFFFF, CW=2)
        self.assertEqual((r["AW"], r["DW"]), (0xFFFE, 0xFFFF))
        r = run("div_cw", AW=0xFFF6, DW=0xFFFF, CW=3)       # -10 / 3: -3 rem -1
        self.assertEqual((r["AW"], r["DW"]), (0xFFFD, 0xFFFF))
        self.assertEqual(run("mul_aw_cw_imm8", CW=0x0010)["AW"], 0x0050)
        for name in ("clc", "stc", "cli", "sti", "adj4a"):
            r = run(name)
            self.assertEqual({k: r[k] for k in ("CW", "DW", "SP", "IX", "IY")},
                             {k: self.REGS[k] for k in ("CW", "DW", "SP", "IX", "IY")}, name)

    def test_bcd_pairs_from_the_walk(self):
        # the EU takes a BCD string's byte pairs from the chain walk, keyed by its 0F opcode
        # (after the DS1: prefix the pfx form carries)
        from validation.v35s.chains.sim.machine import Machine
        for cid, n in (("F32-out-add4s-n8-k1-pE-w0", 4), ("F32-out-pfx_add4s-n4-k1-pO-w0", 2),
                       ("F32-out-cmp4s-n2-k2-pE-w0", 1)):
            chain = next(c for c in generate(["F32"], waits=(0,)) if c.id == cid)
            m = Machine(chain, DEFAULT)
            self.assertEqual(sorted(v[0] for v in m.eu.strings.values()),
                             [n] * (2 if "-k2-" in cid else 1), cid)
            from validation.v35s.chains.forms import F32_BCD
            x = next(i for i in chain.instrs if i.role == "x" and i.form in F32_BCD)
            self.assertIn(x.offset + (1 if x.code[0] == 0x26 else 0), m.eu.strings, cid)


# (WP78) the hand start of stage 16 (sim/config.py DEFAULT_COST) with the two adopted enums and
# the integers the tests read (the candidate's where stage 16 moved them): the tests pin the
# mechanisms at these values, independent of the tracked fit
WP78 = {"bf_count": "dw", "page_grp": "group",
        # (fit 57) WP112's 0F-memory enums and WP113's bit1_test.nx move pinned to their old values
        "page_cl": "free", "page_ir": "none", "page_dio": "extend"}
WP78_INTS = {"adjust.nx0": 8, "adjust.pre0": 10, "adjust.wb": 2, "mul.sexec": 41,
             "div.sexec": 58, "bf_ext.setup": 12, "bf_ext.setup_free": 0, "bf_ext.span": 14,
             # (fit 50) WP94's EXT write-back moved span / xspan / wb together: pin all three
             "bf_ext.xspan": 42, "bf_ext.wb": 0,
             # (fit 57) WP113 moved bit1_test.nx 2 -> 0: pinned to WP78's value
             "bit1_test.nx": 2,
             # (fit 62) WP122 moved page_commit start -> post: pinned to WP78's value
             "page_commit": "start",
             "bcd4s.first": 16, "bcd4s.mid": 7, "bcd4s.wmid": 10, "bcd4s.loop": 7,
             "bcd4s.exec": 12, "bcd4s.wb": 2, "bit1_rmw.cl": 1, "bit1_rmw.dfloor": 4,
             "bit1_rmw.pre": 7, "bit1_rmw.grp": 0}


def _ev78(cid, **over):
    """(silicon, model) event lists from t_fill under the tracked fit with WP78 (+ over)."""
    run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
    s = normalize(run)
    cfg = Config.fitted().replace(**{**WP78, **WP78_INTS, **over})
    m = simulate_normalized(s.chain, cfg, s.chain_base)
    return [e[:2] for e in aligned(s)], [e[:2] for e in aligned(m)]


class PageAndMiscellany(unittest.TestCase):
    """(WP78) F32's and F33's forms as mechanisms: each new enum and format integer against its
    alternative on a deciding run (clocks rel t_fill), each new template on a run."""

    def test_wp78_defaults_are_the_old_model(self):
        for name in ("bf_count", "page_grp"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        for name, value in WP78.items():
            self.assertIn(value, OPTIONS[name], name)
        # the format integers absent from every existing class: nothing old reads them
        from validation.v35s.chains.sim.config import DEFAULT_COST
        for cls, d in DEFAULT_COST.items():
            if cls.startswith("str_") or cls in ("reg", "imm", "load", "load_alu", "rmw",
                                                  "rmw_imm", "store", "out", "in", "push"):
                for name in ("nx0", "cl", "span"):
                    self.assertNotIn(name, d, cls)

    def test_bf_count_dw(self):
        # EXT BL,DH at pO w0: the read 12 clocks after M0's I/O at 85 whatever the fetch at 88
        # (counted as a DW-form request's setup: only wait states stop it): silicon R97
        sil, mod = _ev78("F32-out-ext_bl_dh-k1-pO-w0")
        self.assertEqual(mod, sil)
        self.assertIn((97, "data_read"), mod)
        # (the forty-third fit's bf_read=fixed supersedes the count: pinned to the forty-second's)
        _, data = _ev78("F32-out-ext_bl_dh-k1-pO-w0", bf_count="data", bf_read="count")
        self.assertIn((96, "data_read"), data)

    def test_page_grp_group_setup(self):
        # SET1 [BW],CL byte at pE w0: the refill 87, 90 back to back, silicon's read 95 and
        # write 100; the CL index's clocks in the group setup (fetch-free at its end) put the
        # read on the fetch end + 3; as EU clocks before the read (none) it is a clock later
        sil, mod = _ev78("F32-out-set1_mb_cl-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((95, "data_read"), mod)
        # (the forty-third fit's page_mem=fixed has no group setup: pinned to the forty-second's)
        _, none = _ev78("F32-out-set1_mb_cl-k1-pE-w0", page_grp="none", page_mem="group")
        self.assertIn((96, "data_read"), none)

    def test_nx0_long_one_byte_form(self):
        # ADJ4A after the OUT marker at pE: the loader busy 8 clocks from its start (84), the
        # refill fetch at 92; at once (nx0 0) it goes at 94
        sil, mod = _ev78("F33-out-adj4a-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((92, "fetch"), mod)
        # (the forty-third fit's wb_fetch=hold holds that fetch a clock: pinned to the forty-second's)
        _, zero = _ev78("F33-out-adj4a-k1-pE-w0", **{"adjust.nx0": 0, "wb_fetch": "free"})
        self.assertIn((94, "fetch"), zero)

    def test_sexec_signed_register_multiply(self):
        # MUL CW (F7 /5, signed) behind the lead: M1's fetch 147, I/O 154; at MULU's exec 137
        sil, mod = _ev78("F33-out-mul_cw-ld-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((154, "io_write"), mod)
        _, plain = _ev78("F33-out-mul_cw-ld-k1-pE-w0", **{"mul.sexec": 31})
        self.assertIn((144, "io_write"), plain)
        sil, mod = _ev78("F33-out-div_cw-ld-k1-pE-w0")
        self.assertEqual(mod, sil)

    def test_bcd_byte_pair_loop(self):
        # ADD4S, CL = 4: two pairs, read IX + i, read IY + i 9 later, the write 12 after that
        sil, mod = _ev78("F32-out-add4s-n4-k1-pE-w0")
        self.assertEqual(mod, sil)
        data = [e for e in mod if e[1].startswith("data")]
        self.assertEqual(data, [(107, "data_read"), (116, "data_read"), (128, "data_write"),
                                (137, "data_read"), (146, "data_read"), (158, "data_write")])
        # CMP4S writes nothing
        sil, mod = _ev78("F32-out-cmp4s-n4-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertFalse([e for e in mod if e[1] == "data_write"])

    def test_templates_simulate_their_cycles(self):
        # every F32 / F33 form's data cycles are the walk's (the normaliser raises otherwise),
        # and the bit field's crossing reads / writes two words
        for cid in ("F32-out-ins_dl_bh-k1-pE-w0", "F32-out-ext_dl_i11-k1-pO-w0",
                    "F32-out-clr1_mw_imm-k2-pE-w1", "F32-out-ror4_m-k1-pO-w2",
                    "F33-out-mul_aw_m_imm8-k2-pE-w0", "F33-out-incb_m-k1-pO-w0"):
            sil, mod = _ev78(cid)
            self.assertEqual([k for _, k in mod if k.startswith("data")],
                             [k for _, k in sil if k.startswith("data")], cid)
        _, mod = _ev78("F32-out-ins_dl_bh-k1-pE-w0")
        self.assertEqual([k for _, k in mod if k.startswith("data")],
                         ["data_read", "data_write", "data_read", "data_write"])

    def test_classes_run_their_base_structure(self):
        # a long one-byte form behind the OUT marker obeys the register forms' I/O interlock
        # as NOP does: it starts no earlier than the marker's I/O issue
        from validation.v35s.chains.sim.machine import Machine
        chain = next(c for c in generate(["F33"], waits=(0,), parities=("even",))
                     if c.id == "F33-out-adj4a-k1-pE-w0")
        m = Machine(chain, Config.fitted().replace(**WP78, **WP78_INTS))
        cycles = m.run()
        io = [c.start for c in cycles if c.kind == "io_write"]
        starts = [t for t, off, cls in m.eu.trace if cls == "adjust"]
        self.assertTrue(starts and starts[0] >= io[0], (starts, io))


# (WP81) the forty-third fit's candidate (scratchpad wp81/fit-wp81b.json): the new enums and the
# integers stage 17 moved or added, over the tracked fit
WP81 = {"xfer_nt": "odd", "stack_wb": "ret", "page_take": "own", "page_mem": "fixed",
        "bf_read": "fixed", "mul_imm_read": "issue", "mul_imm_hold": "word", "wb_fetch": "hold"}
WP81_INTS = {"bf_ext.fsetup": 7, "bf_ext.nx": 1, "bf_ext.pre": 1, "bf_ins.fsetup": 7,
             "bf_ins.nx": 1, "bf_ins.pre": 1, "bit1.exec": 2, "bit1.nx": 5, "bit1.pre": 1,
             "bit1.wb": 2, "bit1_clr.fsetup": 3, "bit1_clr.pre": 1, "bit1_rmw.cl": 3,
             "bit1_rmw.dfloor": 2, "bit1_rmw.fsetup": 3, "bit1_rmw.nx": 0, "bit1_rmw.pre": 1,
             "bit1_test.exec": 2, "bit1_test.fsetup": 3, "bit1_test.pre": 4,
             "branch_short.nhold": 3, "branch_short.wb": 2, "dbnz.nhold": 4, "dbnz.wb": 2,
             "mul_imm.mexec": 43, "mul_imm.mhold": 41, "mul_imm.rsetup": 2,
             "rol4_mem.fsetup": 1, "ror4_mem.fsetup": 3, "ror4_mem.nx": 1, "ror4_mem.pre": 5}


def _ev81(cid, **over):
    """(silicon, model) event lists from t_fill under the tracked fit with WP81 (+ over)."""
    run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
    s = normalize(run)
    cfg = Config.fitted().replace(**{**WP81, **WP81_INTS, **over})
    m = simulate_normalized(s.chain, cfg, s.chain_base)
    return [e[:2] for e in aligned(s)], [e[:2] for e in aligned(m)]


class MissShapes(unittest.TestCase):
    """(WP81) F34's readings as mechanisms: each new enum against its alternative on its deciding
    run (clocks rel t_fill)."""

    def test_wp81_defaults_are_the_old_model(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST
        for name, value in WP81.items():
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
            self.assertIn(value, OPTIONS[name], name)
        # the new integers: unread by the tracked fit's enums, absent from the classes before
        for cls in ("branch_short", "dbnz"):
            self.assertEqual(DEFAULT_COST[cls]["nhold"], 0)
        for cls in ("bit1_test", "bit1_rmw", "bit1_clr", "rol4_mem", "ror4_mem", "bf_ext",
                    "bf_ins"):
            self.assertIn("fsetup", DEFAULT_COST[cls])
        self.assertEqual(DEFAULT_COST["mul_imm"]["mhold"], 0)

    def test_xfer_nt_odd_not_taken_hold(self):
        # BNE not taken at an odd address starts at 97 with an aborted cycle 97-99: no request
        # until 3 clocks into the flag test, silicon's fetch 103; none: re-raised at 100
        sil, mod = _ev81("F34-out-nt-bne-d-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((103, "fetch"), mod)
        _, none = _ev81("F34-out-nt-bne-d-k1-pE-w0", xfer_nt="none")
        self.assertIn((100, "fetch"), none)
        # DBNZ at an odd address holds even the fetch committed back to back on its start
        sil, mod = _ev81("F34-out-nt-dbnz-l0-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((99, "fetch"), mod)
        _, none = _ev81("F34-out-nt-dbnz-l0-k1-pE-w0", xfer_nt="none")
        self.assertIn((94, "fetch"), none)

    def test_not_taken_write_back(self):
        # BNE not taken: its last 2 clocks a write-back only the port OUT waits for (I118 at
        # pE behind the drainer); the PUSH frame's stack write is the same either way
        sil, mod = _ev81("F34-out-nt-bne-nop-k1-pE-w0")
        self.assertEqual(mod, sil)
        _, zero = _ev81("F34-out-nt-bne-nop-k1-pE-w0", **{"branch_short.wb": 0})
        self.assertNotEqual(zero, sil)
        for wb in (0, 2):
            sil, mod = _ev81("F34-push-nt-bne-l0-k1-pE-w0", **{"branch_short.wb": wb})
            self.assertEqual(mod, sil, wb)

    def test_stack_wb_ret_after_a_shift(self):
        # SHL AW,8 ends at 143 and the RET starts on 144: its stack read 151 (none: 150)
        sil, mod = _ev81("F34-out-cr-shl8-l0-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((151, "stack_read"), mod)
        _, none = _ev81("F34-out-cr-shl8-l0-pE-w0", stack_wb="none")
        self.assertIn((150, "stack_read"), none)
        # a NOP between the shift and the RET: exact either way
        for v in ("none", "ret"):
            sil, mod = _ev81("F34-out-cr-shl8nop-l0-pE-w0", stack_wb=v)
            self.assertEqual(mod, sil, v)

    def test_page_take_own(self):
        # the NOP at 85 loads 0F, SET1 AW,imm starts at 89 and its second opcode byte leaves the
        # queue there: silicon's fetch 89 and 92 (operand: the room freed with the take step's
        # end, F91 at the candidate's integers, F90 at the tracked fit's)
        sil, mod = _ev81("F34-out-rbit-set1_rw_imm-nop-k1-pO-w0")
        self.assertIn((89, "fetch"), sil)
        self.assertEqual(mod[:5], sil[:5])
        _, operand = _ev81("F34-out-rbit-set1_rw_imm-nop-k1-pO-w0", page_take="operand")
        self.assertNotIn((89, "fetch"), operand)

    def test_page_mem_fixed(self):
        # TEST1 [BW],CL at pE: the refill 87, 90 (committed back to back), silicon's read 95
        # = F87's end + 6 counted clocks; at pO (F88 alone) 96; SET1 the same clocks
        for cid, r in (("F34-out-mbit-test1_mw_cl-l0-k1-pE-w0", 95),
                       ("F34-out-mbit-test1_mw_cl-l0-k1-pO-w0", 96),
                       ("F34-out-mbit-set1_mw_cl-l0-k1-pE-w0", 95)):
            sil, mod = _ev81(cid)
            self.assertIn((r, "data_read"), sil, cid)
            self.assertIn((r, "data_read"), mod, cid)
        _, group = _ev81("F34-out-mbit-test1_mw_cl-l0-k1-pE-w0", page_mem="group")
        self.assertNotIn((95, "data_read"), group)

    def test_bf_read_fixed(self):
        # EXT BL,DH behind a NOP at pE: the refill 88, 91; silicon's read 100, the last fetch's
        # end + 6 (count: 105)
        sil, mod = _ev81("F34-out-bf-ext_bl_dh-nop-k1-pE-w0")
        self.assertIn((100, "data_read"), sil)
        self.assertIn((100, "data_read"), mod)
        _, count = _ev81("F34-out-bf-ext_bl_dh-nop-k1-pE-w0", bf_read="count")
        self.assertNotIn((100, "data_read"), count)

    def test_mul_imm_hold_word(self):
        # MUL AW,[BW],5 at pE: the immediate the even byte of its word, the next opcode its
        # second: no fetch from the read until near the multiply's end (silicon F134)
        sil, mod = _ev81("F34-out-mul-mul_aw_m_imm8-l0-k1-pE-w0")
        self.assertIn((134, "fetch"), sil)
        fetches = [t for t, k in mod if k == "fetch" and 92 <= t < 130]
        self.assertEqual(fetches, [])
        _, none = _ev81("F34-out-mul-mul_aw_m_imm8-l0-k1-pE-w0", mul_imm_hold="none")
        self.assertTrue([t for t, k in none if k == "fetch" and 88 <= t < 130])

    def test_wb_fetch_hold(self):
        # INC AW 85-87, the OUT starts on 88 behind its write-back: silicon F89 F93 I101
        # (free: F88 F92 I100); with a NOP between exact either way
        sil, mod = _ev81("F34-out-inc-inc_aw-l0-k1-n0-pE-w1")
        self.assertEqual(mod, sil)
        _, free = _ev81("F34-out-inc-inc_aw-l0-k1-n0-pE-w1", wb_fetch="free")
        self.assertIn((88, "fetch"), free)
        for v in ("free", "hold"):
            sil, mod = _ev81("F34-out-inc-inc_aw-l0-k1-n1-pE-w1", wb_fetch=v)
            self.assertEqual(mod, sil, v)


# WP84: refresh_scope, a causal refresh. Under live the refresh counter exists for every chain
# and the EU runs its refresh templates and rules only while RFEN is in force (Refresh.eu_on);
# under any (the old behaviour) a chain whose own RFM store turns refresh on runs them from
# clock 0. Base: the tracked fit.
def _run84(cid):
    fam = cid.split("-")[0]
    w = int(cid.rsplit("-w", 1)[1])
    return normalize(next(r for r in _runs(fam) if r["chain"]["id"] == cid
                          and r["chain"]["waits"] == w))


def _model84(s, cfg):
    from validation.v35s.chains.sim.machine import refresh_anchor
    n = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    return [(e.clock, e.kind, e.addr, e.width, e.length) for e in n.pre + n.events], n.t_fill


class RefreshScope(unittest.TestCase):
    """WP84: refresh_scope=live against any (scratchpad wp84/facts.txt)."""

    @classmethod
    def setUpClass(cls):
        cls.any = Config.fitted().replace(refresh_scope="any")   # (forty-fourth fit: live)
        cls.live = cls.any.replace(refresh_scope="live")

    def test_default_is_the_old_behaviour(self):
        self.assertEqual(OPTIONS["refresh_scope"], ("any", "live"))
        self.assertEqual(DEFAULT.refresh_scope, "any")

    def test_live_equals_any_on_refresh_off_chains(self):
        # a chain whose RFEN never sets: the counter fires nothing and the templates are the
        # refresh-off ones (F17-e: its own store writes ECh)
        for cid in ("F0-ls-pE-w0", "F1-out-m2-pE-w1", "F9-push-nop1-pE-w2",
                    "F17-e-n0-empty-pE-w1", "F17-w-ec-n2-pE-w1", "F18-a-push-ec-empty-pO-w0"):
            try:
                s = _run84(cid)
            except StopIteration:
                self.fail(f"no run {cid}")
            self.assertEqual(_model84(s, self.live), _model84(s, self.any), cid)

    def test_live_counter_exists_for_a_chain_with_a_store(self):
        # F17-e: the store writes ECh: under live the counter exists, the EU never sees it
        s = _run84("F17-e-n0-empty-pE-w1")
        m = Machine(s.chain, self.live, s.chain_base)
        self.assertIsNotNone(m.refresh)
        self.assertIsNone(m.eu.refresh)          # RFEN clear: no refresh templates or rules
        m.run()
        self.assertEqual(m.refresh.served, [])
        self.assertEqual([w[2] for w in m.refresh.writes], [0xEC])
        self.assertIsNone(Machine(s.chain, self.any, s.chain_base).refresh)

    def test_no_store_no_refresh_on_reads_no_scope(self):
        # a chain with neither refresh on nor an RFM store can never set RFEN: its counter is
        # unobservable and not built, and refresh_scope is not read (the fit's cache key)
        from validation.v35s.chains import fit
        s = _run84("F0-ls-pE-w0")
        rc = fit.recording(self.live)
        simulate_normalized(s.chain, rc, s.chain_base)
        self.assertNotIn("refresh_scope", rc._reads)
        self.assertIsNone(Machine(s.chain, self.live, s.chain_base).refresh)

    def test_live_no_refresh_before_the_store(self):
        # F17-s-n0-shlcl4-pO-w0 (prelude ECh, the RFMON store FCh after the first LS): under
        # live the EU sees no refresh controller before the store's effect and no request is
        # raised before it; under any the controller is the EU's from clock 0
        from validation.v35s.chains.sim import machine as M
        s = _run84("F17-s-n0-shlcl4-pO-w0")
        for cfg, before in ((self.live, False), (self.any, True)):
            seen = []

            class Probe(M.Machine):
                def run(self):
                    eu, tick = self.eu, self.eu.tick

                    def probe(t):
                        seen.append((t, eu.refresh is not None))
                        return tick(t)
                    eu.tick = probe
                    return super().run()
            phase = (64 - M.POP_COUNTER[(s.chain.rfm, s.chain.wtc)]) % 128
            m = Probe(s.chain, cfg, s.chain_base, phase, 0)
            m.run()
            (issue, effect, value), = m.refresh.writes
            self.assertEqual(value, 0xFC)
            self.assertEqual(effect, issue + cfg.rfm_delay)
            self.assertTrue(m.refresh.served)
            self.assertTrue(all(r >= effect for r, _ in m.refresh.served))
            pre = {on for t, on in seen if t < effect}
            post = {on for t, on in seen if t >= effect}
            self.assertEqual(pre, {before}, cfg.refresh_scope)
            self.assertEqual(post, {True}, cfg.refresh_scope)

    def test_live_equals_any_on_store_chains(self):
        # the store-turns-refresh-on runs: the next instruction starts on the store's effect
        # clock, so every refresh falls in an instruction whose template live chose with RFEN
        # seen (F17 S/D/W/C, F18 B/BD/AC; a sample of each series, exact and not)
        for cid in ("F17-s-n0-shlcl4-pO-w0", "F17-d-n1-shlcl16-pE-w0", "F17-w-fd-n5-pE-w0",
                    "F17-c-push-mulu-pO-w0", "F18-b-n1-shlmcl-pE-w2", "F18-bd-n0-shlcl4-pE-w0",
                    "F18-ac-out-fc-pO-w0", "F17-s-n3-rmw-pE-w1"):
            s = _run84(cid)
            self.assertEqual(_model84(s, self.live), _model84(s, self.any), cid)

    def test_live_on_a_refresh_on_prelude(self):
        # the prelude's RFEN: the EU sees the controller from clock 0 under both
        s = _run84("F17-p-n0-empty-pE-w0")
        self.assertEqual(_model84(s, self.live), _model84(s, self.any))


# WP85: the forty-third fit's refresh-on misses of F27 and F28, the I/O sequencer beside a refresh
WP85 = {"port_ready_count": "count", "port_refresh": "late", "refresh_pair_post": "before",
        "io_step_restart": "last", "refresh_lead_step": "step"}
WP85_OLD = {"port_ready_count": "ready", "port_refresh": "none", "refresh_pair_post": "any",
            "io_step_restart": "max", "refresh_lead_step": "block"}


def _aligned85(cid, cfg):
    from validation.v35s.chains.sim.machine import refresh_anchor
    s = _run84(cid)
    n = simulate_normalized(s.chain, cfg, s.chain_base, refresh=refresh_anchor(s))
    return aligned(s), aligned(n)


class RefreshSequencerF27F28(unittest.TestCase):
    """WP85: the five new rules against their old values on their deciding runs (clocks rel
    t_fill; scratchpad wp85/facts.txt), refresh_scope=live equal to any under them."""

    @classmethod
    def setUpClass(cls):
        cls.new = Config.fitted().replace(**WP85)

    def test_defaults_are_the_old_behaviour(self):
        for name, old in WP85_OLD.items():
            self.assertEqual(getattr(DEFAULT, name), old, name)
            self.assertEqual(OPTIONS[name][0], old, name)
            self.assertEqual(set(OPTIONS[name]), {old, WP85[name]}, name)

    def _check(self, cid, name, kind, sil, old):
        """Exact under the new rules; with name at its old value the first divergence is the
        kind event at old where silicon has it at sil."""
        a, b = _aligned85(cid, self.new)
        self.assertEqual(a, b, cid)
        self.assertIn(sil, [e[0] for e in a if e[1] == kind], cid)
        a, b = _aligned85(cid, self.new.replace(**{name: WP85_OLD[name]}))
        k = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
        self.assertEqual((a[k][0], a[k][1]), (sil, kind), cid)
        self.assertEqual(b[k][0], old, cid)

    def test_port_ready_count(self):
        # the X's OUT 40h,AL posted 115, the refresh 120-124, its count's end and M1's port take
        # on 125: the I/O issues there (ready: relatched, with port_refresh=late from 126, I129)
        self._check("F27-out-fc-port-outb-n3-pE-w0", "port_ready_count", "io_write", 125, 129)

    def test_port_refresh(self):
        # M0's I/O posted 86, the refresh 89-93, M1's take on 94 (the clock after it), the
        # count out on 96: I98 (none: the relatch from 94, I97)
        self._check("F28-out-fc-fence-cl29-n0-pE-w0", "port_refresh", "io_write", 98, 97)

    def test_refresh_pair_post(self):
        # the refresh 127-131, M1 posts on 132, the beaten fetch's issue clock: no pair, I140
        # (any: the pair's second fetch on 136, I141)
        a, b = _aligned85("F27-out-fc-room-movawi-n0-k2-pE-w1", self.new)
        self.assertEqual(a, b)
        self.assertIn((140, "io_write"), [e[:2] for e in a])
        self.assertNotIn(136, [e[0] for e in a if e[1] == "fetch"])
        a, b = _aligned85("F27-out-fc-room-movawi-n0-k2-pE-w1",
                          self.new.replace(refresh_pair_post="any"))
        self.assertIn(136, [e[0] for e in b if e[1] == "fetch"])

    def test_io_step_restart(self):
        # M1's I/O posted 139 behind the fetch 138-140, the request 144: the steps 141, 143, 145
        # (max: from 142, the refresh on 144)
        self._check("F27-out-fc-beat-ds1-n4-pO-w0", "io_step_restart", "refresh", 145, 144)

    def test_refresh_lead_step(self):
        # the same run: the step 145 is the lead's last clock (block: the refresh on 146)
        self._check("F27-out-fc-beat-ds1-n4-pO-w0", "refresh_lead_step", "refresh", 145, 146)

    def test_live_equals_any_under_the_new_rules(self):
        live = self.new.replace(refresh_scope="live")
        for cid in ("F27-out-fc-port-outb-n3-pE-w0", "F28-out-fc-fence-cl29-n0-pE-w0",
                    "F27-out-fc-room-movawi-n0-k2-pE-w1", "F27-out-fc-beat-ds1-n4-pO-w0",
                    "F17-s-n0-shlcl4-pO-w0", "F18-b-n1-shlmcl-pE-w2", "F18-ac-out-fc-pO-w0",
                    "F13-c-out-shlcl8-pO-w1", "F8-out-empty-pE-w1"):
            s = _run84(cid)
            self.assertEqual(_model84(s, live), _model84(s, self.new), cid)

    def test_refresh_off_runs_unchanged_and_unread(self):
        # every rule reads a refresh-on state only (a refresh cycle on the bus, a refresh-on I/O
        # request's fields, the pair after a beaten fetch); port_ready_count is read beside any
        # port take with a request still counting, and changes nothing without a refresh
        from validation.v35s.chains import fit
        old = Config.fitted()
        for cid in ("F7-out-out_imm_al-ld_bw-pO-w0", "F26-out-pi-oo-none-n0-pO-w0",
                    "F29-out-ec-pi-oo-movawi-n0-pO-w0", "F27-out-ec-port-outb-n3-pE-w0",
                    "F28-out-ec-tail-shlcl8-outb-n1-pE-w0"):
            s = _run84(cid)
            self.assertEqual(_model84(s, self.new), _model84(s, old), cid)
            rc = fit.recording(self.new)
            simulate_normalized(s.chain, rc, s.chain_base)
            for name in ("port_refresh", "refresh_pair_post", "io_step_restart",
                         "refresh_lead_step"):
                self.assertNotIn(name, rc._reads, cid)


WP86 = {"page_b2b": "reg", "page_run": "field"}


def _ev86(cid, **over):
    """(silicon, model) (clock, kind) lists from t_fill under the tracked fit with WP86 (+ over)."""
    run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**WP86, **over}), s.chain_base)
    return [e[:2] for e in aligned(s)], [e[:2] for e in aligned(m)]


class PageFormRuns(unittest.TestCase):
    """(WP86) two of the 0F forms' remaining miss shapes as mechanisms (scratchpad
    wp86/facts.txt): each new enum against its old value on its deciding run (clocks rel
    t_fill)."""

    def test_defaults_are_the_old_behaviour(self):
        for name, new in WP86.items():
            self.assertEqual(getattr(DEFAULT, name), "none", name)
            self.assertEqual(OPTIONS[name][0], "none", name)
            self.assertEqual(OPTIONS[name][-1], new, name)
        self.assertEqual(OPTIONS["page_run"], ("none", "mem", "field"))

    def test_page_b2b_register_form_run(self):
        # SET1 AW,CL starts on 85 under M0's I/O, its ModR/M taken on 87, F88 issued: silicon
        # runs F91 back to back (none: the room rule waits, F98)
        sil, mod = _ev86("F34-out-rbit-set1_rw_cl-l0-k1-pO-w0")
        self.assertEqual(mod, sil)
        self.assertIn((91, "fetch"), mod)
        # bit1.nx pinned at its pre-WP120 value 5 (the sixtieth fit, 2026-11-01, moved it to 4,
        # which reaches F91 without page_b2b)
        _, none = _ev86("F34-out-rbit-set1_rw_cl-l0-k1-pO-w0", page_b2b="none", **{"bit1.nx": 5})
        self.assertNotIn((91, "fetch"), none)
        self.assertIn((98, "fetch"), none)
        # byte = word, TEST1 = SET1: the same cell exact under the rule
        for cid in ("F34-out-rbit-set1_rb_cl-l0-k1-pO-w0", "F34-out-rbit-test1_rw_cl-l0-k1-pO-w0"):
            sil, mod = _ev86(cid)
            self.assertEqual(mod, sil, cid)

    def test_page_b2b_not_after_an_early_ir_load(self):
        # ROR4 DL loads the next opcode on its take clock, before the fetch issues: no run
        for over in ({}, {"page_b2b": "none"}):
            sil, mod = _ev86("F32-out-ror4_dl-k1-pO-w0", **over)
            self.assertEqual(mod, sil, over)

    def test_page_b2b_never_overfills(self):
        # the word committed only where the queue can hold it (the corpus's k = 2 CL cells)
        for cid in ("F34-out-rbit-set1_rw_cl-d-k1-pE-w0", "F32-out-set1_rw_cl-k2-pE-w0"):
            run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
            s = normalize(run)
            simulate_normalized(s.chain, Config.fitted().replace(**WP86), s.chain_base)

    def test_page_run_committed_refill(self):
        # the form's takes end on 82 under M0's I/O, the refill F87 with room for a word on its
        # last clock: silicon F87 F90 D95 W100 (none: no F90, the read on 95 after F87)
        sil, mod = _ev86("F34-out-mbit-set1_mw_cl-l0-k1-pE-w0")
        self.assertEqual(mod, sil)
        self.assertIn((90, "fetch"), mod)
        self.assertIn((95, "data_read"), mod)
        _, none = _ev86("F34-out-mbit-set1_mw_cl-l0-k1-pE-w0", page_run="none")
        self.assertNotIn((90, "fetch"), none)
        # the committed fetch's wait clocks do not count toward the read's setup: D98 / D101
        for cid, read in (("F34-out-mbit-set1_mw_cl-l0-k1-pE-w1", 98),
                          ("F34-out-mbit-set1_mw_cl-l0-k1-pE-w2", 101),
                          ("F32-out-set1_mw_cl-k1-pE-w0", 95)):
            sil, mod = _ev86(cid)
            self.assertEqual(mod, sil, cid)
            self.assertIn((read, "data_read"), mod, cid)

    def test_page_run_field(self):
        # EXT BL,DH: its read posted under M0's I/O, the refill F87 with room for a word on its
        # last clock: silicon F87 F90 D96 (mem, the memory forms only: no F90, D96 then F99)
        for cid in ("F34-out-bf-ext_bl_dh-l0-k1-pE-w0", "F34-out-bf-ext_bl_dh-l0-k1-pE-w1"):
            sil, mod = _ev86(cid)
            self.assertEqual(mod, sil, cid)
        _, mem = _ev86("F34-out-bf-ext_bl_dh-l0-k1-pE-w0", page_run="mem")
        self.assertNotIn((90, "fetch"), mem)
        self.assertIn((99, "fetch"), mem)
        # the memory forms are the same under mem and field
        for cid in ("F34-out-mbit-set1_mw_cl-l0-k1-pE-w1", "F32-out-set1_mw_cl-k1-pE-w0"):
            self.assertEqual(_ev86(cid, page_run="mem")[1], _ev86(cid)[1], cid)

    def test_page_run_once_per_form(self):
        # [BW+d8]: the request rule already committed a fetch after the start (deferred by M0's
        # I/O to F89): no second one, the read on 98 (silicon F82 O86 F89 D98)
        sil, mod = _ev86("F32-out-set1_mw_cl_bw_d8-k1-pO-w1")
        self.assertEqual(mod, sil)
        self.assertIn((98, "data_read"), mod)

    def test_other_families_do_not_read_the_rules(self):
        from validation.v35s.chains import fit
        for cid in ("F7-out-out_imm_al-ld_bw-pO-w0", "F33-out-inc_al-k1-pE-w1",
                    "F30-out-nt-bne-k2-n2-pE-w2"):
            run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
            s = normalize(run)
            new = simulate_normalized(s.chain, Config.fitted().replace(**WP86), s.chain_base)
            old = simulate_normalized(s.chain, Config.fitted(), s.chain_base)
            self.assertEqual(aligned(new), aligned(old), cid)


# (WP88) the candidate's moves over the tracked fit (the forty-fourth): stage 21's chosen enum and
# integers; the new classes' other integers are DEFAULT_COST's (the hand start the stage kept)
WP88 = {"ret_imm_hold": "word", "call_far.spre": 2, "load_ptr.wb": 2, "pop_psw.wb": 2,
        "ret_far_imm.setup": 6, "ret_far_imm.setup_free": 4, "ret_far_imm.wsetup": 8}


def _ev88(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with WP88 (+ over)."""
    fam = cid.split("-", 1)[0]
    w = int(cid.rsplit("-w", 1)[1])
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid and r["chain"]["waits"] == w)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**WP88, **over}), s.chain_base)
    return aligned(s), aligned(m)


class CoverageDecode(unittest.TestCase):
    """(WP88, F35, F36) the decoder and execute on the forms F35 and F36 add: every condition of the
    70-7F row from the flags, the loop format's Z test, BCWZ, the register-indirect and far
    transfers' absolute targets and stack words, the class-equivalent forms in their classes."""

    REGS = {"AW": 0, "BW": 0x0800, "CW": 0, "DW": 0x5678, "SP": 0x0F00, "BP": 0x0A00,
            "IX": 0x0100, "IY": 0x0180}

    def _flags(self, code):
        from validation.v35s.chains.sim.templates import execute
        regs = dict(self.REGS)
        op = decode(code, 0, regs)
        execute(op, code, regs)
        return regs

    def test_flags_and_every_condition(self):
        from validation.v35s.chains.forms import F35_COND, F35_CONTROLS, f35_cond_taken
        from validation.v35s.chains.sim.templates import cond_taken
        for ctl, (form, flags) in F35_CONTROLS.items():
            regs = self._flags(FORMS[form].code)
            self.assertEqual({k: regs[k] for k in flags}, flags, ctl)
            for cond, op in F35_COND.items():
                self.assertEqual(cond_taken(op, regs), f35_cond_taken(cond, flags), (ctl, cond))
                taken = decode(bytes([op, 2]), 0, regs).target is not None
                self.assertEqual(taken, f35_cond_taken(cond, flags), (ctl, cond))
        with self.assertRaises(ValueError):        # a condition whose flag is not known
            decode(bytes([0x70, 0]), 0, {**self.REGS, "Z": 1})

    def test_loop_format(self):
        r = dict(self.REGS)
        # BCWZ: taken iff CW = 0, CW unchanged
        self.assertEqual(decode(bytes([0xE3, 2]), 0, {**r, "CW": 0}).target, 4)
        self.assertIsNone(decode(bytes([0xE3, 2]), 0, {**r, "CW": 1}).target)
        self.assertEqual(decode(bytes([0xE3, 2]), 0, r).cls, "bcwz")
        # DBNZE / DBNZNE: the Z test first (zfail), then the count
        for op, z, cw, taken, zfail in ((0xE1, 1, 2, True, False), (0xE1, 0, 2, False, True),
                                        (0xE1, 1, 1, False, False), (0xE0, 1, 2, False, True),
                                        (0xE0, 0, 2, True, False), (0xE0, 0, 1, False, False)):
            o = decode(bytes([op, 0]), 0, {**r, "CW": cw, "Z": z})
            self.assertEqual((o.cls, o.target is not None, o.zfail), ("dbnz_z", taken, zfail),
                             (op, z, cw))
        from validation.v35s.chains.sim.templates import execute
        regs = {**r, "CW": 2, "Z": 1}
        execute(decode(bytes([0xE1, 0]), 0, regs), bytes([0xE1, 0]), regs)
        self.assertEqual(regs["CW"], 1)
        regs = {**r, "CW": 0}
        execute(decode(bytes([0xE3, 0]), 0, regs), bytes([0xE3, 0]), regs)
        self.assertEqual(regs["CW"], 0)

    def test_transfers_and_stack(self):
        from validation.v35s.chains.sim.templates import execute
        r = {**self.REGS, "code_at": 0x40}
        op = decode(FORMS["brf_t0053"].code, 0, r)
        self.assertEqual((op.cls, op.length, op.target), ("branch_far", 5, 0x53 - 0x40))
        code = FORMS["callf_t0056"].code
        regs = dict(r)
        op = decode(code, 0, regs)
        self.assertEqual((op.cls, op.target, op.stack), ("call_far", 0x16, (None, 0x0EFE)))
        execute(op, code, regs)
        self.assertEqual((regs["SP"], regs["ret0EFC"]), (0x0EFC, 5))
        code = FORMS["retf_imm2"].code
        op = decode(code, 0, regs)
        self.assertEqual((op.cls, op.imm_bytes, op.target), ("ret_far_imm", 2, 5))
        execute(op, code, regs)
        self.assertEqual(regs["SP"], 0x0F02)
        regs = {**r, "BW": 0x52}
        op = decode(FORMS["call_bw"].code, 0, regs)
        self.assertEqual((op.cls, op.target, op.modrm), ("call_reg", 0x12, False))
        self.assertEqual(decode(FORMS["br_bw"].code, 0, regs).cls, "br_reg")
        op = decode(FORMS["ret_imm2"].code, 0, {**r, "ret0F00": 9})
        self.assertEqual((op.cls, op.imm_bytes, op.target), ("ret_imm", 2, 9))
        op = decode(FORMS["les_aw_ix"].code, 0, r)
        self.assertEqual((op.cls, op.ea, op.length), ("load_ptr", 0x0100, 2))

    def test_class_equivalent_forms(self):
        r = {**self.REGS, "CW": 31}
        for name, cls in (("push_bp", "push"), ("pop_iy", "pop"), ("push_psw", "push"),
                          ("pop_psw", "pop_psw"), ("xch_aw_sp", "reg"), ("mov_dh_imm8", "imm"),
                          ("mov_ix_imm16", "imm"), ("subc_aw_dw", "reg"),
                          ("xor_aw_imm16", "imm"), ("ld_al_dir", "load"), ("st_al_dir", "store"),
                          ("shl_al_cl", "shift_cl"), ("shlb_m_cl", "rmw"), ("lahf", "flag"),
                          ("sahf", "flag"), ("test_dl_al", "test_reg"),
                          ("addb_m_imm8_82", "rmw_imm"), ("cmpb_m_imm8_80", "load_alu")):
            op = decode(FORMS[name].code, 0, r)
            self.assertEqual((op.cls, op.length), (cls, FORMS[name].length), name)
        for name in ("ld_al_dir", "st_al_dir", "shlb_m_cl", "addb_m_imm8_80"):
            self.assertEqual(decode(FORMS[name].code, 0, r).width, 1, name)
        self.assertEqual(decode(FORMS["shl_al_cl"].code, 0, r).count, 31)
        # BUSLOCK: a prefix pseudo-instruction, then the form
        code = FORMS["lock_add_m_aw"].code
        self.assertEqual(decode(code, 0, r).cls, "prefix")
        self.assertEqual(decode(code, 1, r).cls, "rmw")


class CoverageForms(unittest.TestCase):
    """(WP88, F35, F36) each new class on its deciding run (scratchpad wp88/facts.txt; clocks rel
    t_fill), the class-equivalent forms exact under their classes, ret_imm_hold against its old
    value, and the earlier families untouched."""

    def _exact(self, cid, **over):
        sil, mod = _ev88(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_every_condition_is_be_bne(self):
        # taken and not taken, every condition, under each control: exact where BE / BNE are
        for cid in ("F35-out-cc-bv-t-n0-pE-w0", "F35-out-cc-bgt-t-n2-pO-w1",
                    "F35-out-cc-ble-nt-n2-pE-w2", "F35-out-cc-bc-t-n0-pO-w2",
                    "F35-push-cc-bpe-t-n0-pO-w0", "F35-push-cc-blt-nt-n0-pE-w1",
                    "F35-out-cc-bp-nt-n0-pO-w0"):
            self._exact(cid)

    def test_bcwz(self):
        # BCWZ = DBNZ - 3 taken, - 2 not taken: its own exec / nexec
        for cid in ("F35-out-cw-bcwz-t-n0-pE-w0", "F35-push-cw-bcwz-nt-n0-pE-w1"):
            self._exact(cid)
        dbnz = {"bcwz.exec": 14, "bcwz.nexec": 6}
        for cid in ("F35-out-cw-bcwz-t-n0-pE-w0", "F35-push-cw-bcwz-nt-n0-pE-w1"):
            sil, mod = _ev88(cid, **dbnz)
            self.assertNotEqual(mod, sil, cid)

    def test_dbnz_z(self):
        # the Z test first: a Z exit zexec, a count exit nexec (3 apart)
        for cid in ("F35-out-cw-dbnze-c1-cmpad-pO-w0", "F35-out-cw-dbnze-c1-cmpaa-pO-w1",
                    "F35-out-cw-dbnzne-c2-cmpad-pE-w0", "F35-push-cw-dbnzne-c1-cmpad-pE-w2"):
            self._exact(cid)
        sil, mod = _ev88("F35-out-cw-dbnze-c1-cmpad-pO-w0", **{"dbnz_z.zexec": 7})
        self.assertNotEqual(mod, sil)

    def test_ret_imm_hold(self):
        # RET 0 at 10052, its immediate 53-54 (the word half-taken): the read 122, no fetch until
        # the return target's at 133 (none: F125 1005A)
        mod = self._exact("F35-out-ret-imm0-pO-w0")
        self.assertIn((122, "stack_read", 0x0EFE, "word", 3), mod)
        self.assertNotIn((125, "fetch", 0x1005A, "word", 3), mod)
        _, none = _ev88("F35-out-ret-imm0-pO-w0", ret_imm_hold="none")
        self.assertIn((125, "fetch", 0x1005A, "word", 3), none)
        # the pE twin (the immediate 54-55: a whole word freed) fetches 1005A after its read
        for over in ({}, {"ret_imm_hold": "none"}):
            mod = self._exact("F35-out-ret-imm0-pE-w0", **over)
            self.assertIn((127, "fetch", 0x1005A, "word", 3), mod)

    def test_register_and_far_transfers(self):
        # CALL BW: the third fetch back to back at pE (F94), the write 7 after its end (w103)
        mod = self._exact("F35-out-ind-callr-pE-w0")
        self.assertIn((94, "fetch", 0x10058, "word", 3), mod)
        self.assertIn((103, "stack_write", 0x0EFE, "word", 3), mod)
        for cid in ("F35-out-ind-callr-pO-w2", "F35-out-ind-brr-n0-pE-w1",
                    "F35-push-ind-brr-n1-pO-w0", "F35-out-ind-callr-ret-pE-w2",
                    "F35-out-far-brf-n0-pO-w0", "F35-out-far-brf-n1-pE-w2"):
            self._exact(cid)

    def test_pointer_psw_and_test(self):
        # LES: the offset at IX, the segment word at IX+2 seven clocks later
        mod = self._exact("F36-out-ptr-les_aw_ix-pE-w0")
        self.assertIn((90, "data_read", 0x0100, "word", 3), mod)
        self.assertIn((97, "data_read", 0x0102, "word", 3), mod)
        for cid in ("F36-push-ptr-lds_aw_ix-pO-w2", "F36-out-stack-push_psw-pop_psw-pO-w0",
                    "F36-push-stack-push_psw-pop_psw-pE-w1", "F36-out-test-test_dl_al-pE-w0",
                    "F36-push-test-test_dl_al-pE-w2"):
            self._exact(cid)
        # TEST DL,AL at the two-byte register forms' cost misses
        sil, mod = _ev88("F36-out-test-test_dl_al-pE-w0", **{"test_reg.pre": 0})
        self.assertNotEqual(mod, sil)

    def test_class_equivalent_forms_exact(self):
        for cid in ("F36-out-xch-xch_aw_bp-pE-w0", "F36-push-stack-push_ix-pO-w1",
                    "F36-out-stack-push_sp-pop_sp-pE-w2", "F36-out-mov-mov_bh_imm8-pO-w1",
                    "F36-push-mov-mov_iy_imm16-pE-w2", "F36-out-alu-subc_aw_dw-pE-w0",
                    "F36-out-alu-cmp_aw_imm16-pO-w2", "F36-push-alu-addb_m_imm8_82-pO-w0",
                    "F36-out-alu-cmpb_m_imm8_80-pE-w1", "F36-out-shift-shlb_m_cl-pE-w2",
                    "F36-push-shift-shl_al_cl-pO-w0", "F36-out-mov-ld_al_dir-pO-w1",
                    "F36-push-mov-st_al_dir-pE-w0", "F36-out-lock-lock_mov_aw_dw-pE-w1",
                    "F36-push-lock-lock_add_m_aw-pO-w2", "F36-out-psw-lahf-sahf-pO-w0"):
            self._exact(cid)

    def test_earlier_families_untouched(self):
        # no earlier class reads a WP88 rule or integer
        for cid in ("F23-out-callret-pO-w1", "F30-out-nt-dbnz-k1-n0-pO-w0",
                    "F34-out-cr-shl8-l0-pE-w0", "F25-push-pushr-pE-w2"):
            fam = cid.split("-", 1)[0]
            run = next((r for r in _runs(fam) if r["chain"]["id"] == cid), None)
            if run is None:
                continue
            s = normalize(run)
            new = simulate_normalized(s.chain, Config.fitted().replace(**WP88), s.chain_base)
            old = simulate_normalized(s.chain, Config.fitted(), s.chain_base)
            self.assertEqual(aligned(new), aligned(old), cid)

    def test_default_is_the_old_behaviour(self):
        self.assertEqual(DEFAULT.ret_imm_hold, "none")
        self.assertEqual(OPTIONS["ret_imm_hold"], ("none", "word"))


# (WP89) the candidate's moves over the tracked fit (the forty-fifth): stage 22's chosen enums and
# integers
WP89 = {"xfer_nt_b2b": "decide", "decide_abort": "cycle", "dbnz_z.nhold": 2, "dbnz_z.chold": 5}


def _ev89(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with WP89 (+ over)."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**WP89, **over}), s.chain_base)
    return aligned(s), aligned(m)


class NotTakenBackToBack(unittest.TestCase):
    """(WP89, F23 F30 F34 F35) a short conditional transfer not taken: a fetch ending in its decide
    step with a byte of room commits the bus unit to one more fetch back to back, and the test
    does not wait for it (scratchpad wp89/facts.txt; clocks rel t_fill)."""

    def _exact(self, cid, **over):
        sil, mod = _ev89(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_default_is_the_old_behaviour(self):
        self.assertEqual(DEFAULT.xfer_nt_b2b, "none")
        self.assertEqual(OPTIONS["xfer_nt_b2b"], ("none", "decide"))
        self.assertEqual(DEFAULT.decide_abort, "fetch")
        self.assertEqual(OPTIONS["decide_abort"], ("fetch", "cycle"))

    def test_deciding_run(self):
        # BNE at 10050 starts on F87's issue, F90 back to back ends on 92 in the decide step with
        # room 1: silicon F93 back to back, M1's I/O 107 (none: F100 after M1's start, I107)
        mod = self._exact("F23-out-bne-n0-k1-pE-w0")
        self.assertIn((93, "fetch", 0x10058, "word", 3), mod)
        self.assertIn((107, "io_write", 0x21, "hi", 3), mod)
        _, none = _ev89("F23-out-bne-n0-k1-pE-w0", xfer_nt_b2b="none")
        self.assertNotIn((93, "fetch", 0x10058, "word", 3), none)
        self.assertIn((100, "fetch", 0x10058, "word", 3), none)

    def test_every_condition_wait_and_frame(self):
        # every condition behind CMP, each wait, k = 2 and 3, NOPs after, the PUSH frame's second
        # BNE at an even address
        for cid in ("F35-out-cc-bv-nt-n0-pE-w1", "F35-out-cc-bgt-nt-n2-pE-w2",
                    "F34-out-nt-be-l0-k2-pE-w1", "F30-out-nt-bne-k3-n0-pE-w0",
                    "F30-out-nt-bne-k1-n3-pE-w2", "F23-out-bne-n2-pE-w2",
                    "F30-push-nt-bne-k2-n0-pO-w0", "F30-push-nt-bne-k3-n0-pO-w1"):
            self._exact(cid)

    def test_not_in_the_cond_clocks(self):
        # the fetch running on the start clock ends in the cond clocks with room 1: no run (PUSH
        # frame, BNE at an even address); the odd address, the twin and the leads exact either way
        for cid in ("F23-push-bne-n0-k1-pO-w0", "F23-out-bne-n0-k1-pO-w0",
                    "F34-out-nt-twin-l0-k1-pE-w0", "F34-out-nt-bne-d2-k1-pE-w0",
                    "F34-out-nt-bne-nop2-k1-pE-w0", "F35-out-cc-bnv-nt-n0-pE-w0"):
            for over in ({}, {"xfer_nt_b2b": "none"}):
                self._exact(cid, **over)

    def test_loop_classes_untouched(self):
        # DBNZ, BCWZ, DBNZE / DBNZNE: their decide step starts on the take; xfer_nt_b2b reads
        # branch_short only
        for cid in ("F34-out-nt-dbnz-l0-k1-pE-w0", "F35-out-cw-bcwz-nt-n0-pE-w0",
                    "F35-out-cw-dbnze-c1-cmpaa-pE-w0", "F23-out-dbnz-c1-n0-pE-w0",
                    "F35-out-loop-dbnz-nop-pO-w0"):
            sil, new = _ev89(cid)
            _, old = _ev89(cid, xfer_nt_b2b="none")
            self.assertEqual(new, old, cid)

    def test_decide_abort_deciding_run(self):
        # DBNZ at 10053 (odd) starts on 99 with the request answered by an aborted cycle 99-101:
        # its decide step's gap counts from 101, the odd hold ends nhold clocks into its nexec
        # clocks: silicon F107 (fetch: the gap from F96's end, F106)
        mod = self._exact("F34-out-nt-dbnz-d-k1-pO-w0")
        self.assertIn((107, "fetch", 0x1005A, "word", 3), mod)
        _, old = _ev89("F34-out-nt-dbnz-d-k1-pO-w0", decide_abort="fetch")
        self.assertIn((106, "fetch", 0x1005A, "word", 3), old)
        # started on a fetch's issue instead: exact either way (the gap from that fetch's end)
        for over in ({}, {"decide_abort": "fetch"}):
            self._exact("F34-out-nt-dbnz-l0-k1-pE-w0", **over)

    def test_decide_abort_every_wait_and_the_loop(self):
        # the drainer and NOP leads at every wait, the backward DBNZ's second (not-taken) pass,
        # DBNZE / DBNZNE's exits at an odd address (their holds one lower with the rule)
        for cid in ("F34-out-nt-dbnz-d3-k1-pO-w2", "F34-out-nt-dbnz-nop2-k1-pE-w1",
                    "F34-push-nt-dbnz-nop-k1-pE-w2", "F35-out-loop-dbnz-nop-pO-w0",
                    "F35-push-loop-dbnz-reg-pO-w1", "F35-out-loop-dbnz-nop-pE-w2",
                    "F35-out-cw-dbnze-c1-cmpaa-pE-w0", "F35-push-cw-dbnzne-c2-cmpaa-pE-w1",
                    "F35-out-cw-dbnzne-c1-cmpad-pO-w2"):
            self._exact(cid)


WP92 = dict(lea_slot="ea", lea_disp="run")


def _ev92(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with WP92 (+ over)."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**WP92, **over}), s.chain_base)
    return aligned(s), aligned(m)


class LdeaDisplacement(unittest.TestCase):
    """(WP92, F25 F30) a displaced LDEA: its EA clocks give the empty IR no seventh slot on a
    delivery clock, as a displaced memory form's do (lea_slot), and its split two-byte
    displacement holds the successor off a back-to-back fetch's issue only when it was taken
    inside the refill run (lea_disp=run) (scratchpad wp92/facts.txt; clocks rel t_fill)."""

    def _exact(self, cid, **over):
        sil, mod = _ev92(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_default_is_the_old_behaviour(self):
        self.assertEqual(DEFAULT.lea_slot, "none")
        self.assertEqual(OPTIONS["lea_slot"], ("none", "ea"))
        self.assertEqual(DEFAULT.lea_disp, "none")
        self.assertEqual(OPTIONS["lea_disp"], ("none", "split", "run"))

    def test_lea_slot_deciding_run(self):
        # LDEA [BW+IX+200h] at 1004D starts on fetch 81-83, its EA clocks 82-84, the word
        # delivered on 84 with the d16 still to take: silicon F85 F88 W94 (none: F84 F87 W96)
        mod = self._exact("F25-push-ldea-bw_ix_d16-pE-w0")
        self.assertIn((85, "fetch", 0x10054, "word", 3), mod)
        self.assertIn((94, "stack_write", 0x0EFC, "word", 3), mod)
        _, none = _ev92("F25-push-ldea-bw_ix_d16-pE-w0", lea_slot="none")
        self.assertIn((84, "fetch", 0x10054, "word", 3), none)
        self.assertNotIn((85, "fetch", 0x10054, "word", 3), none)

    def test_lea_slot_every_base_index_mode_and_the_load(self):
        # the four base+index+d16 modes at pE w0 and F30's OUT frame behind a NOP; the load in
        # the same cell (ea_ir_room's deciding run) and the base-only d16 (its EA clocks over
        # before the delivery) exact either way
        for cid in ("F25-push-ldea-bw_iy_d16-pE-w0", "F25-push-ldea-bp_ix_d16-pE-w0",
                    "F25-push-ldea-bp_iy_d16-pE-w0", "F30-out-lea-bw_ix_d16-nopb-pE-w0"):
            self._exact(cid)
        for cid in ("F21-push-l0-ld-bw_ix_d16-pE-w0", "F25-push-ldea-bw_d16-pE-w0",
                    "F25-push-ldea-bw_ix_d16-pO-w0", "F25-push-ldea-bw_ix_d16-pE-w1"):
            for over in ({}, {"lea_slot": "none"}):
                self._exact(cid, **over)

    def test_lea_disp_run_deciding_run(self):
        # NOP, then LDEA [BW+200h] at 1004E: the d16 taken on 88 with the bus idle since 83,
        # fetch 88 issued on the take, 91 back to back: silicon's PUSH on 91's issue, W97
        # (split: W100)
        mod = self._exact("F30-push-lea-bw_d16-nopb-pO-w0")
        self.assertIn((97, "stack_write", 0x0EFC, "word", 3), mod)
        _, split = _ev92("F30-push-lea-bw_d16-nopb-pO-w0", lea_disp="split")
        self.assertIn((100, "stack_write", 0x0EFC, "word", 3), split)
        for cid in ("F30-push-lea-bw_ix_d16-nopb-pO-w0", "F30-push-lea-dir-nopb-pO-w0"):
            self._exact(cid)

    def test_lea_disp_run_keeps_the_hold_inside_the_run(self):
        # the d16 taken on a delivery clock (w0), a fetch's last clock (w1), a wait clock (w2):
        # the hold stays, W = the third fetch's end + 7 (none: the PUSH on the third's issue)
        for cid in ("F25-push-ldea-bw_d16-pE-w0", "F25-push-ldea-bw_d16-pE-w1",
                    "F25-push-ldea-bw_d16-pE-w2", "F30-push-lea-bw_d16-k1-pE-w1",
                    "F25-push-ldea-dir-pE-w2", "F30-out-lea-dir-nopb-pE-w1"):
            self._exact(cid)
            for over in ({"lea_disp": "split"},):
                self._exact(cid, **over)

    def test_other_classes_untouched(self):
        # no run without LDEA reads either enum
        for cid in ("F21-push-l0-ld-bw_ix_d16-pE-w0", "F21-push-n1-st-bw_d16-pE-w1",
                    "F23-out-bne-n0-k1-pE-w0", "F30-push-seg-8c-bw-ds1-n0-pO-w0"):
            _, new = _ev92(cid)
            _, old = _ev92(cid, lea_slot="none", lea_disp="split")
            self.assertEqual(new, old, cid)
# (WP91) the candidate's moves over the tracked fit (the forty-fifth): the three enums; the six
# classes' integers are DEFAULT_COST's (the hand start, read off F37 and tuned by scoring)
WP91 = {"xfer_mem_head": "lead", "xfer_mem_disp": "grp", "xfer_mem_ir": "hold"}


def _ev91(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with WP91 (+ over)."""
    fam = cid.split("-", 1)[0]
    w = int(cid.rsplit("-w", 1)[1])
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid and r["chain"]["waits"] == w)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**WP91, **over}), s.chain_base)
    return aligned(s), aligned(m)


class CoverageF37Decode(unittest.TestCase):
    """(WP91, F37) the decoder and execute on F37's transfers: the memory image of the words the
    chain stores, the pointer's and the vector's targets (absolute offsets in PS), the stack
    words and the SP walk (CALL [m] 2, CALL far [m] 4, BRK 6 down; RETI 6 up)."""

    REGS = {"AW": 0, "BW": 0x0C00, "CW": 0, "DW": 0x5678, "SP": 0x0F00, "BP": 0x0A00,
            "IX": 0x0100, "IY": 0x0180, "code_at": 0x40}

    def _run(self, names, regs=None):
        """decode and execute the forms in order; [(op, regs after)]."""
        from validation.v35s.chains.sim.templates import execute
        regs = dict(regs or self.REGS)
        code = b"".join(FORMS[n].code for n in names)
        out, k = [], 0
        for _ in names:
            op = decode(code, k, regs)
            execute(op, code, regs)
            out.append((op, dict(regs)))
            k += op.length
        return out

    def test_memory_image(self):
        # MOV AW,58h ; MOV [0C00h],AW: the word kept at 0C00h
        (_, _), (op, regs) = self._run(["mov_aw_t0058", "st_acc_dir"])
        self.assertEqual((op.cls, op.ea, regs["mem0C00"]), ("store", 0x0C00, 0x58))
        # an unwritten pointer is not modelled
        with self.assertRaises(ValueError):
            decode(FORMS["call_m_dir"].code, 0, dict(self.REGS))

    def test_near_and_far_through_memory(self):
        lead = ["mov_aw_t0058", "st_acc_dir"]
        ops = self._run(lead + ["call_m_dir"])
        op, regs = ops[-1]
        self.assertEqual((op.cls, op.target, op.ea, op.mode_class, op.modrm, op.stack),
                         ("call_mem", 0x58 - 0x40, 0x0C00, "direct", True, (None, 0x0EFE)))
        self.assertEqual((regs["SP"], regs["ret0EFE"]), (0x0EFE, 6 + 4))
        op, regs = self._run(lead + ["br_m_bw"])[-1]
        self.assertEqual((op.cls, op.target, op.ea, op.mode_class, regs["SP"]),
                         ("br_mem", 0x18, 0x0C00, "base", 0x0F00))
        far = ["mov_aw_t0058", "st_acc_dir", "mov_aw_1000", "st_acc_0c02"]
        op, regs = self._run(far + ["callf_m_dir"])[-1]
        self.assertEqual((op.cls, op.target, op.stack), ("call_far_mem", 0x18, (None, 0x0EFE)))
        self.assertEqual((regs["SP"], regs["ret0EFC"]), (0x0EFC, 12 + 4))
        op, _ = self._run(far + ["brf_m_bw"])[-1]
        self.assertEqual((op.cls, op.target, op.length), ("branch_far_mem", 0x18, 2))
        # a far pointer whose segment is not PS (1234h), or never written, is not modelled
        with self.assertRaises(ValueError):
            self._run(lead + ["mov_aw_imm", "st_acc_0c02", "brf_m_dir"])
        with self.assertRaises(ValueError):
            self._run(lead + ["brf_m_dir"])

    def test_brk_and_reti(self):
        for n, name, store in ((3, "brk3", ("st_acc_000c", "st_acc_000e")),
                               (5, "brk5", ("st_acc_0014", "st_acc_0016"))):
            lead = ["mov_aw_t005d", store[0], "mov_aw_1000", store[1]]
            ops = self._run(lead + [name])
            op, regs = ops[-1]
            self.assertEqual((op.cls, op.vec, op.target, op.length, op.stack, op.ea),
                             ("brk", 4 * n, 0x1D, 1 if n == 3 else 2, (None, 0x0EFE), None))
            self.assertEqual((regs["SP"], regs["ret0EFA"]), (0x0EFA, 12 + op.length))
            code = FORMS["reti"].code
            op = decode(code, 0, regs)
            self.assertEqual((op.cls, op.target, op.stack), ("reti", 12 + 1 + (n == 5), (0x0EFA, None)))
            from validation.v35s.chains.sim.templates import execute
            execute(op, code, regs)
            self.assertEqual(regs["SP"], 0x0F00)

    def test_base_classes(self):
        from validation.v35s.chains.sim.templates import BASE_CLASS
        self.assertEqual({c: BASE_CLASS[c] for c in ("call_mem", "call_far_mem", "brk", "br_mem",
                                                       "branch_far_mem", "reti")},
                         {"call_mem": "call", "call_far_mem": "call", "brk": "call",
                          "br_mem": "branch_near", "branch_far_mem": "branch_near",
                          "reti": "ret"})


class CoverageF37Forms(unittest.TestCase):
    """(WP91, F37) each new class on its deciding runs (scratchpad wp91/facts.txt; clocks rel
    t_fill), the three enums against their old values, and the earlier families untouched."""

    def _exact(self, cid, **over):
        sil, mod = _ev91(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def _miss(self, cid, **over):
        sil, mod = _ev91(cid, **over)
        self.assertNotEqual(mod, sil, cid)
        return mod

    def test_call_mem(self):
        # CALL near [0C00h]: the fetch held 3 clocks after the displacement (F106), the read
        # right after it (R109), the push 7 after the read's end (w118), the target's fetch 9
        # after the push's end (F10058 at 129)
        mod = self._exact("F37-out-indm-callm-n0-pE-w0")
        for e in ((106, "fetch", 0x1005C, "word", 3), (109, "data_read", 0x0C00, "word", 3),
                  (118, "stack_write", 0x0EFE, "word", 3), (129, "fetch", 0x10058, "word", 3)):
            self.assertIn(e, mod)
        # CALL near [BW]: the read 6 fetch-free clocks after the start, no fetch before it (R114)
        mod = self._exact("F37-out-indm-callbw-n0-pE-w0")
        self.assertIn((114, "data_read", 0x0C00, "word", 3), mod)
        for cid in ("F37-push-indm-callm-ret-pO-w2", "F37-out-indm-callbw-ret-pO-w1",
                    "F37-out-indm-callm-sep-pO-w0"):
            self._exact(cid)
        self._miss("F37-out-indm-callm-n0-pE-w0", **{"call_mem.setup": 8})
        self._miss("F37-out-indm-callbw-n0-pE-w0", **{"call_mem.grp": 5})

    def test_br_mem(self):
        mod = self._exact("F37-out-indm-brm-n0-pE-w0")
        self.assertIn((109, "data_read", 0x0C00, "word", 3), mod)
        self.assertIn((120, "fetch", 0x10058, "word", 3), mod)       # 9 after the read's end
        for cid in ("F37-push-indm-brm-n1-pE-w1", "F37-out-indm-brbw-n1-pO-w2"):
            self._exact(cid)
        self._miss("F37-out-indm-brm-n0-pE-w0", **{"br_mem.exec": 7})

    def test_far_through_memory(self):
        # CALL far [0C00h]: the offset (R125), the segment 7 later (R132), PS then the return
        # offset at 9 clocks issue to issue (w141, w150)
        mod = self._exact("F37-out-farm-callfm-n0-pE-w0")
        for e in ((125, "data_read", 0x0C00, "word", 3), (132, "data_read", 0x0C02, "word", 3),
                  (141, "stack_write", 0x0EFE, "word", 3), (150, "stack_write", 0x0EFC, "word", 3)):
            self.assertIn(e, mod)
        # BR far [BW] at one wait: the reads 8 apart (R142, R150)
        mod = self._exact("F37-out-farm-brfbw-n0-pO-w1")
        self.assertIn((150, "data_read", 0x0C02, "word", 4), mod)
        for cid in ("F37-push-farm-callfbw-retf-pE-w2", "F37-out-farm-brfm-n1-pO-w0"):
            self._exact(cid)
        self._miss("F37-out-farm-callfm-n0-pE-w0", **{"call_far_mem.rwsetup": 6})
        self._miss("F37-out-farm-brfbw-n0-pO-w1", **{"branch_far_mem.rwsetup": 4})

    def test_brk_and_reti(self):
        # BRK 3: the vector's offset (R0C at 127), PSW (w133), its segment (R0E at 141), PS (w147)
        # and the return offset (w156); the handler's fetch 9 after (F1005D at 167); RETI's pops
        # at 9 clocks issue to issue (r185 r194 r203), the return's fetch 15 after (F1005B 220)
        mod = self._exact("F37-out-brk-brk3-pE-w0")
        for e in ((127, "data_read", 0x000C, "word", 3), (133, "stack_write", 0x0EFE, "word", 3),
                  (141, "data_read", 0x000E, "word", 3), (147, "stack_write", 0x0EFC, "word", 3),
                  (156, "stack_write", 0x0EFA, "word", 3), (167, "fetch", 0x1005D, "word", 3),
                  (185, "stack_read", 0x0EFA, "word", 3), (203, "stack_read", 0x0EFE, "word", 3),
                  (220, "fetch", 0x1005B, "word", 3)):
            self.assertIn(e, mod)
        # BRK 5: a fetch after its start (F119), the vector read 8 fetch-free clocks after it
        mod = self._exact("F37-out-brk-brk5-pE-w0")
        self.assertIn((129, "data_read", 0x0014, "word", 3), mod)
        for cid in ("F37-push-brk-brk3-nop-pO-w2", "F37-out-brk-brk5-sep-pO-w1",
                    "F37-push-brk-brk5-pE-w1"):
            self._exact(cid)
        self._miss("F37-out-brk-brk5-pE-w0", **{"brk.rfree": 9})
        self._miss("F37-out-brk-brk3-pE-w0", **{"brk.rexec": 4})
        self._miss("F37-out-brk-brk3-pE-w0", **{"reti.exec": 13})

    def test_xfer_mem_head(self):
        # the ModR/M byte on the start: CALL [0C00h] at pO, its fetch at 106 (split: 107)
        self._exact("F37-out-indm-callm-n0-pO-w0")
        self._miss("F37-out-indm-callm-n0-pO-w0", xfer_mem_head="split")
        self._miss("F37-out-indm-callbw-n0-pE-w0", xfer_mem_head="split")

    def test_xfer_mem_disp(self):
        # the d16's fetch held dhold clocks after its take: F106, R109 (none: F103)
        mod = self._miss("F37-out-indm-callm-n0-pE-w0", xfer_mem_disp="none")
        self.assertIn((103, "fetch", 0x1005C, "word", 3), mod)
        self._miss("F37-out-indm-brm-n0-pO-w0", xfer_mem_disp="none")

    def test_xfer_mem_ir(self):
        # CALL [BW] at pO: no aborted cycle on its start, the fetch at 108 (none: 111)
        mod = self._exact("F37-out-indm-callbw-n0-pO-w0")
        self.assertIn((108, "fetch", 0x1005C, "word", 3), mod)
        mod = self._miss("F37-out-indm-callbw-n0-pO-w0", xfer_mem_ir="none")
        self.assertIn((111, "fetch", 0x1005C, "word", 3), mod)

    def test_earlier_families_untouched(self):
        # no earlier class reads a WP91 rule (grp_disp and ir_load see the new classes only)
        for fam in ("F14", "F19", "F21", "F23", "F35"):
            for run in _runs(fam)[::40]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(**WP91), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted(), s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)

    def test_default_is_the_old_behaviour(self):
        self.assertEqual((DEFAULT.xfer_mem_head, DEFAULT.xfer_mem_disp, DEFAULT.xfer_mem_ir),
                         ("split", "none", "none"))
        self.assertEqual(OPTIONS["xfer_mem_head"], ("split", "lead"))
        self.assertEqual(OPTIONS["xfer_mem_disp"], ("none", "grp"))
        self.assertEqual(OPTIONS["xfer_mem_ir"], ("none", "hold"))


# (WP95) the candidate's moves over the tracked fit (the forty-eighth): the two enums; uwb and ugap
# are DEFAULT_COST's (the hand start read off F24's series s)
WP95 = {"str_single_wb": "wb", "str_single_start": "delivery",
        # (fit 52) WP101 read uwb 2 with str_single_wb=index: WP95's wb is pinned with its uwb 1
        "str_move.uwb": 1, "str_cmp.uwb": 1, "str_in.uwb": 1}


def _ev95(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with WP95 (+ over)."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**WP95, **over}), s.chain_base)
    return aligned(s), aligned(m)


class StringPairSecondInstance(unittest.TestCase):
    """(WP95, F24) the second instance of an unprefixed string pair: the first instance's exec
    ends uwb clocks early for every successor but a wbsync form (str_single_wb), and an
    unprefixed form starts no earlier than ugap clocks after a fetch's delivery
    (str_single_start) (scratchpad wp95/facts.txt; clocks rel t_fill)."""

    def _exact(self, cid, **over):
        sil, mod = _ev95(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_default_is_the_old_behaviour(self):
        self.assertEqual(DEFAULT.str_single_wb, "none")
        # (WP101) each widened by a third value (StringSuccessorWP101)
        self.assertEqual(OPTIONS["str_single_wb"][:2], ("none", "wb"))
        self.assertEqual(DEFAULT.str_single_start, "any")
        self.assertEqual(OPTIONS["str_single_start"][:2], ("any", "delivery"))

    def test_str_single_wb_deciding_run(self):
        # the first MOVBK's write 103-105, no fetch: silicon's second read 117 (none: 118)
        mod = self._exact("F24-out-s-movbk-b-k2-pO-w0")
        self.assertIn((117, "data_read", 0x0A41, "hi", 3), mod)
        _, none = _ev95("F24-out-s-movbk-b-k2-pO-w0", str_single_wb="none")
        self.assertIn((118, "data_read", 0x0A41, "hi", 3), none)
        # the same write-back clock in INM and CMPBK, every wait and width at pO
        for cid in ("F24-out-s-inm-w-k2-pO-w1", "F24-out-s-cmpbk-b-k2-pO-w2",
                    "F24-out-s-movbk-w-k2-pO-w2"):
            self._exact(cid)

    def test_str_single_wb_leaves_the_out_after_one_instance(self):
        # the OUT after one instance (k1) waits the write-back out (wbsync): exact either way
        for cid in ("F24-out-s-movbk-b-k1-pO-w0", "F24-out-s-inm-w-k1-pO-w1",
                    "F24-out-s-cmpbk-b-k1-pE-w0", "F24-out-s-movbk-w-k1-pE-w2"):
            for over in ({}, {"str_single_wb": "none", "str_single_start": "any"}):
                self._exact(cid, **over)

    def test_str_single_start_deciding_run(self):
        # write 104-107, fetch 108-111 delivered on 112: silicon's second read 121 (any: 120)
        mod = self._exact("F24-out-s-movbk-b-k2-pE-w1")
        self.assertIn((121, "data_read", 0x0A41, "hi", 4), mod)
        _, anyw = _ev95("F24-out-s-movbk-b-k2-pE-w1", str_single_start="any")
        self.assertIn((120, "data_read", 0x0A41, "hi", 4), anyw)
        for cid in ("F24-out-s-cmpm-b-k2-pE-w2", "F24-out-s-cmpbk-w-k2-pE-w1",
                    "F24-out-s-inm-b-k2-pE-w2", "F24-out-s-movbk-b-k2-pE-w0"):
            self._exact(cid)

    def test_one_cycle_pairs_exact_either_way(self):
        # STM and LDM pairs (LDM's second instance on the delivery: ugap 0)
        for cid in ("F24-out-s-stm-b-k2-pE-w1", "F24-out-s-ldm-w-k2-pE-w2",
                    "F24-out-s-ldm-b-k2-pO-w0", "F24-out-s-stm-w-k2-pO-w2"):
            for over in ({}, {"str_single_wb": "none", "str_single_start": "any"}):
                self._exact(cid, **over)

    def test_rep_forms_untouched(self):
        # neither rule reads a REP form (str_exit=wb keeps its own xwb; CW = 0 included)
        for cid in ("F24-out-r-rep-movbk-b-n0-pE-w0", "F24-out-r-rep-movbk-b-n2-pO-w0",
                    "F24-out-r-rep-stm-w-n1-pE-w1"):
            _, new = _ev95(cid)
            _, old = _ev95(cid, str_single_wb="none", str_single_start="any")
            self.assertEqual(new, old, cid)

    def test_other_families_untouched(self):
        # no run without an unprefixed string form reads either enum
        for fam in ("F14", "F21", "F23", "F35"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(**WP95), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted(), s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)
# (WP94) the 0F page's remaining misses read as shapes (scratchpad wp94/facts.txt): two enums,
# each against its old value on its deciding run (clocks rel t_fill)
WP94 = {"bf_imm_hold": "word", "page_imm_run": "delivery"}


def _ev94(cid, **over):
    """(silicon, model) (clock, kind) lists from t_fill under the tracked fit with WP94 (+ over)."""
    run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**WP94, **over}), s.chain_base)
    return [e[:2] for e in aligned(s)], [e[:2] for e in aligned(m)]


class PageHoldsWP94(unittest.TestCase):
    """(WP94, F32 F34) an imm4 bit field's half-taken width word holds the fetch requests
    (bf_imm_hold), and a delivery-clock fetch runs inside a 0F memory form's immediate-index read
    setup (page_imm_run)."""

    def test_defaults_are_the_old_behaviour(self):
        for name, new in WP94.items():
            self.assertEqual(getattr(DEFAULT, name), "none", name)
            self.assertEqual(OPTIONS[name], ("none", new), name)

    def test_bf_imm_hold_deciding_run(self):
        # EXT BL,7 at 10050 (the width byte 10052 even, the next opcode 10053) starts on F88's
        # issue: silicon F88 F91 D101 F165, no fetch between F91 and the read (none: F94 and the
        # read restarted to 104, the next fetch at 180)
        cid = "F34-out-bf-ext_bl_i7-nop-k1-pE-w0"
        sil, mod = _ev94(cid)
        self.assertEqual(mod, sil)
        self.assertIn((101, "data_read"), mod)
        self.assertIn((165, "fetch"), mod)
        _, none = _ev94(cid, bf_imm_hold="none")
        self.assertIn((94, "fetch"), none)
        self.assertIn((104, "data_read"), none)

    def test_bf_imm_hold_request_before_the_take_runs(self):
        # behind M0's I/O the refill F88, requested before the width byte's take on its issue
        # clock, still runs; F91, committed after it, does not (none: F91 back to back)
        cid = "F34-out-bf-ext_bl_i7-l0-k1-pO-w0"
        sil, mod = _ev94(cid)
        self.assertEqual(mod, sil)
        self.assertIn((88, "fetch"), mod)
        self.assertNotIn((91, "fetch"), mod)
        _, none = _ev94(cid, bf_imm_hold="none")
        self.assertIn((91, "fetch"), none)
        # INS: the hold ends with the form (bf_ins.hrel 0): the next fetch on the next start
        sil, mod = _ev94("F34-out-bf-ins_bl_i7-nop-k1-pE-w0")
        self.assertEqual(mod, sil)

    def test_bf_imm_hold_other_alignment_untouched(self):
        # the width byte the odd (last) half of its word: no hold, the same events either way
        for cid in ("F34-out-bf-ext_bl_i7-nop-k1-pO-w0", "F34-out-bf-ins_dl_i11-l0-k1-pE-w0"):
            sil, mod = _ev94(cid)
            self.assertEqual(mod, sil, cid)
            self.assertEqual(_ev94(cid, bf_imm_hold="none")[1], mod, cid)

    def test_page_imm_run_deciding_run(self):
        # SET1 [BW],7 starts 80 under M0's OUT; the refill F87 is not committed (room 1 on its
        # last clock) and F90 is raised on its delivery clock: silicon reads at 93, F90's end + 1
        # (none: F90 restarts the fetch-free setup, D95)
        cid = "F32-out-set1_mw_imm-k1-pE-w0"
        sil, mod = _ev94(cid)
        self.assertEqual(mod, sil)
        self.assertIn((93, "data_read"), mod)
        _, none = _ev94(cid, page_imm_run="none")
        self.assertIn((95, "data_read"), none)

    def test_page_imm_run_not_before_the_head(self):
        # the fetch followed was issued on the form's start (behind a NOP) or before its ModR/M
        # byte was taken (the DS1: prefix): silicon restarts the setup, as the old rule did
        for cid in ("F34-out-mbit-set1_mw_imm-nop-k1-pO-w0", "F32-out-pfx_set1_mb_imm-k1-pO-w0"):
            sil, mod = _ev94(cid)
            self.assertEqual(mod, sil, cid)
            self.assertEqual(_ev94(cid, page_imm_run="none")[1], mod, cid)

    def test_other_families_do_not_read_the_rules(self):
        for cid in ("F7-out-out_imm_al-ld_bw-pO-w0", "F33-out-inc_al-k1-pE-w1",
                    "F30-out-nt-bne-k2-n2-pE-w2", "F34-out-mul-mul_aw_m_imm8-l0-k1-pE-w0"):
            run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
            s = normalize(run)
            new = simulate_normalized(s.chain, Config.fitted().replace(**WP94), s.chain_base)
            old = simulate_normalized(s.chain, Config.fitted(), s.chain_base)
            self.assertEqual(aligned(new), aligned(old), cid)


class PageB2bWindowWP94(unittest.TestCase):
    """(WP94, F32 F34) page_b2b_win: a register 0F form's back-to-back commitment also reaches the
    fetch issued back to back after the one running at its last operand take, when the take came
    after that fetch's issue clock (clocks rel t_fill)."""

    def _ev(self, cid, win):
        run = next(r for r in _runs(cid.split("-", 1)[0]) if r["chain"]["id"] == cid)
        s = normalize(run)
        m = simulate_normalized(s.chain, Config.fitted().replace(page_b2b_win=win), s.chain_base)
        return [e[:2] for e in aligned(s)], [e[:2] for e in aligned(m)]

    def test_default_is_the_old_behaviour(self):
        self.assertEqual(DEFAULT.page_b2b_win, "take")
        self.assertEqual(OPTIONS["page_b2b_win"], ("take", "run"))

    def test_deciding_run(self):
        # SET1 AW,CL starts on F89's issue, its ModR/M taken on F89's wait clock (91), F93
        # committed by the request rule: silicon F97 back to back after F93 (take: F104)
        cid = "F34-out-rbit-set1_rw_cl-nop-k1-pE-w1"
        sil, mod = self._ev(cid, "run")
        self.assertEqual(mod, sil)
        self.assertIn((97, "fetch"), mod)
        _, take = self._ev(cid, "take")
        self.assertNotIn((97, "fetch"), take)
        self.assertIn((104, "fetch"), take)

    def test_take_on_the_issue_clock_and_w0_untouched(self):
        # the imm form at l0 pE takes its immediate on F87's issue clock: no second commitment;
        # at w0 the take falls on the fetch's last clock: the old window already covers it
        for cid in ("F32-out-set1_rw_imm-k1-pE-w0", "F34-out-rbit-set1_rw_cl-nop-k1-pE-w0",
                    "F34-out-rbit-set1_rw_cl-l0-k1-pO-w0"):
            sil, mod = self._ev(cid, "run")
            self.assertEqual(mod, sil, cid)
            self.assertEqual(self._ev(cid, "take")[1], mod, cid)


def _ev98(cid):
    """(silicon, model) aligned event lists from t_fill under the tracked fit."""
    fam = cid.split("-", 1)[0]
    w = int(cid.rsplit("-w", 1)[1])
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid and r["chain"]["waits"] == w)
    s = normalize(run)
    return aligned(s), aligned(simulate_normalized(s.chain, Config.fitted(), s.chain_base))


class DecodeF38WP98(unittest.TestCase):
    """(WP98, F38) the eleven forms WP97 left undecoded, taken into their existing classes with no
    template change: op AL,imm8 (04 0C 14 1C 24 2C 34 3C) the imm class as TEST AL,imm8 (A8);
    C0 the byte form of C1 (SHL AL,imm8: shift_imm with the count byte); C0 / C1 with a memory
    operand the rmw class as D1 / D3's memory forms (count, shift, the count from the immediate
    byte, no imm_bytes: the rmw head takes every operand byte)."""

    REGS = {"AW": 0x1200, "BW": 0x0800, "CW": 0, "DW": 0, "SP": 0x0F00, "BP": 0, "IX": 0,
            "IY": 0, "CY": 1}

    def test_al_imm8(self):
        from validation.v35s.chains.sim.templates import execute, steps
        for op_ in (0x04, 0x0C, 0x14, 0x1C, 0x24, 0x2C, 0x34, 0x3C):
            code = bytes([op_, 0x34])
            op = decode(code, 0, dict(self.REGS))
            self.assertEqual((op.cls, op.length, op.imm_bytes, op.ea, op.modrm),
                             ("imm", 2, 1, None, False), hex(op_))
            regs = dict(self.REGS, AW=0x1281)
            execute(op, code, regs)
            # AL's value (AH kept), the eight operations in bits 5:3 (ADDC / SUBC with CY = 1)
            want = {0x04: 0xB5, 0x0C: 0xB5, 0x14: 0xB6, 0x1C: 0x4C, 0x24: 0x00, 0x2C: 0x4D,
                    0x34: 0xB5, 0x3C: 0x81}[op_]
            self.assertEqual(regs["AW"], 0x1200 | want, hex(op_))
        # its steps are A8's
        cfg = Config.fitted()
        a8 = steps(decode(bytes([0xA8, 0x34]), 0, dict(self.REGS)), cfg)
        self.assertEqual(steps(decode(bytes([0x2C, 0x34]), 0, dict(self.REGS)), cfg), a8)

    def test_c0_register(self):
        from validation.v35s.chains.sim.templates import execute, steps
        code = bytes([0xC0, 0xE0, 0x04])
        op = decode(code, 0, dict(self.REGS))
        self.assertEqual((op.cls, op.length, op.width, op.count, op.imm_bytes, op.shift),
                         ("shift_imm", 3, 1, 4, 1, False))
        regs = dict(self.REGS, AW=0x1233)
        execute(op, code, regs)
        self.assertEqual(regs["AW"], 0x1230)            # SHL AL,4: AH kept
        cfg = Config.fitted()
        c1 = decode(bytes([0xC1, 0xE0, 0x04]), 0, dict(self.REGS))
        self.assertEqual(steps(op, cfg), steps(c1, cfg))

    def test_memory_shift_by_imm8(self):
        # C1 /4 and C0 /4 at [BW]: a read and a write of 0800h (word / byte), count 4 from the
        # immediate byte, every operand byte taken (the ModR/M byte, then the count)
        from validation.v35s.chains.sim.templates import steps
        cfg = Config.fitted()
        for code, width in ((bytes([0xC1, 0x27, 0x04]), 2), (bytes([0xC0, 0x27, 0x04]), 1)):
            op = decode(code, 0, dict(self.REGS))
            self.assertEqual((op.cls, op.length, op.width, op.ea, op.mode_class, op.count,
                              op.shift, op.imm_bytes, op.group, op.cl_count),
                             ("rmw", 3, width, 0x0800, "base", 4, True, 0, True, False),
                             code.hex())
            seq = steps(op, cfg)
            data = [(s[1], s[2], s[3]) for s in seq if s[0] in ("data", "post")]
            self.assertEqual(data, [("read", 0x0800, width), ("write", 0x0800, width)],
                             code.hex())
            self.assertEqual(sum(s[1] for s in seq if s[0] == "take"), 2, code.hex())
        # D1 /4 at [BW] (count 1) keeps its decode
        op = decode(bytes([0xD1, 0x27]), 0, dict(self.REGS))
        self.assertEqual((op.cls, op.length, op.count, op.shift, op.imm_bytes),
                         ("rmw", 2, 1, True, 0))

    def test_exact_runs(self):
        # each newly decoded register shape exact on F38 runs under the tracked fit
        for cid in ("F38-out-imm8-add_al_imm8-pE-w0", "F38-push-imm8-cmp_al_imm8-pO-w2",
                    "F38-out-imm8-subc_al_imm8-pO-w1", "F38-out-shb-shl_al_imm4-pE-w0",
                    "F38-push-shb-shl_al_imm4-pO-w2"):
            sil, mod = _ev98(cid)
            self.assertEqual(mod, sil, cid)

    def test_memory_shift_runs(self):
        # C1 / C0 /4 at [BW]: the model's read and write are silicon's (kind, address, width,
        # order). Not exact under the tracked fit (WP98's fact, reported, no rule added): silicon
        # posts the read before the count byte's take (pE-w0 OUT: R90, the model F90 R93, both
        # W110); the D1 mate shl_m1 is exact in every cell
        pick = lambda ev: [e[1:4] for e in ev if e[1] in ("data_read", "data_write")]
        for cid in ("F38-out-shb-shl_m_imm4-pE-w0", "F38-out-shb-shlb_m_imm4-pO-w1",
                    "F38-push-shb-shl_m_imm4-pE-w2"):
            sil, mod = _ev98(cid)
            self.assertEqual(pick(mod), pick(sil), cid)
            self.assertEqual(len(pick(mod)), 2, cid)
        for cid in ("F38-out-shb-shl_m1-pE-w0", "F38-push-shb-shl_m1-pO-w2"):
            sil, mod = _ev98(cid)
            self.assertEqual(mod, sil, cid)


def _ev99(cid, cfg):
    """(silicon, model) aligned event lists from t_fill under cfg (refresh off)."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    return aligned(s), aligned(simulate_normalized(s.chain, cfg, s.chain_base))


class ShiftMemImmWP99(unittest.TestCase):
    """(WP99, F38) shift_mem_imm: the memory shift by imm8 (C0 / C1 on memory, Op.count_byte) runs
    the rmw template with the count byte in its head (rmw, WP98's decode, the old value) or the
    immediate RMW's (rmw_imm: the read posted after the ModR/M byte, the count byte taken as the
    immediate once the read is on the bus), its ALU step the shift's (shift_imm.exec,
    per_shift_count, rmw_imm.sexec) as the posted write's setup, the first rmw_imm.sthru clocks
    counting through a fetch in flight (scratchpad wp99/facts.txt)."""

    REGS = {"AW": 0x1200, "BW": 0x0800, "CW": 0x001F, "DW": 0, "SP": 0x0F00, "BP": 0, "IX": 0,
            "IY": 0, "CY": 1}

    def _new(self):
        # the tracked fit with the new value (the integers DEFAULT_COST's until adoption)
        return Config.fitted().replace(shift_mem_imm="rmw_imm")

    def test_option(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST
        self.assertEqual(OPTIONS["shift_mem_imm"], ("rmw", "rmw_imm"))
        self.assertEqual(DEFAULT.shift_mem_imm, "rmw")      # the old behaviour
        self.assertEqual((DEFAULT_COST["rmw_imm"]["sexec"], DEFAULT_COST["rmw_imm"]["sthru"]),
                         (3, 2))

    def test_count_byte(self):
        # a format property of the C0 / C1 memory forms only: decode keeps the rmw class
        for code, want in ((bytes([0xC1, 0x27, 0x04]), True), (bytes([0xC0, 0x27, 0x04]), True),
                           (bytes([0xD1, 0x27]), False), (bytes([0xD3, 0x27]), False),
                           (bytes([0xC1, 0xE0, 0x04]), False), (bytes([0x83, 0x07, 0x05]), False)):
            op = decode(code, 0, dict(self.REGS))
            self.assertEqual(op.count_byte, want, code.hex())
            if want:
                self.assertEqual((op.cls, op.imm_bytes, op.count, op.shift),
                                 ("rmw", 0, 4, True), code.hex())

    def test_template(self):
        # under rmw_imm: the read posted, the count byte taken once it is on the bus, the write
        # posted with the ALU step as its setup (3 + 6 + 2 x 3 + 3 = 18), its last 16 fetch-free
        from validation.v35s.chains.sim.templates import Op, steps
        cfg = self._new()
        op = decode(bytes([0xC1, 0x27, 0x04]), 0, dict(self.REGS))
        op = Op(**{**op.__dict__, "cls": "rmw_imm", "imm_bytes": 1})
        seq = steps(op, cfg)
        kinds = [s[0] for s in seq]
        self.assertLess(kinds.index("post"), kinds.index("issued"))
        k = kinds.index("issued")
        self.assertEqual(seq[k + 1], ("take", 1, "chain"))
        self.assertEqual(seq[k + 2], ("wait",))
        write = next(s for s in seq if s[0] == "data" and s[1] == "write")
        self.assertEqual(write, ("data", "write", 0x0800, 2, 18, 16))
        # ADD [BW],imm8 (83 /0) keeps its write: no shift clocks, the class's setup_free
        add = decode(bytes([0x83, 0x07, 0x05]), 0, dict(self.REGS))
        self.assertEqual(steps(add, cfg), steps(add, Config.fitted().replace(shift_mem_imm="rmw")))

    def test_d1_d3_untouched(self):
        # the memory shifts by 1 and by CL keep their template and runs under both values
        from validation.v35s.chains.sim.templates import steps
        old, new = Config.fitted().replace(shift_mem_imm="rmw"), self._new()
        for code in (bytes([0xD1, 0x27]), bytes([0xD3, 0x27]), bytes([0xD0, 0x27])):
            op = decode(code, 0, dict(self.REGS))
            self.assertEqual(steps(op, new), steps(op, old), code.hex())
        for cid in ("F38-out-shb-shl_m1-pO-w0", "F38-push-shb-shl_m1-pE-w2",
                    "F14-g-push-shl_bw_cl-pO-w1", "F14-g-out-shl_bw_1-pE-w0"):
            for cfg in (old, new):
                sil, mod = _ev99(cid, cfg)
                self.assertEqual(mod, sil, cid)

    def test_deciding_runs(self):
        # OUT pE w0 (no fetch between read and write: W = the read's end + 18), OUT pO w0 / w2
        # (fetch 94 / 98 after the read: W = its end + 16), PUSH pO, the byte form
        new = self._new()
        for cid in ("F38-out-shb-shl_m_imm4-pE-w0", "F38-out-shb-shl_m_imm4-pO-w0",
                    "F38-out-shb-shlb_m_imm4-pO-w2", "F38-push-shb-shl_m_imm4-pO-w0",
                    "F38-push-shb-shlb_m_imm4-pE-w1"):
            sil, mod = _ev99(cid, new)
            self.assertEqual(mod, sil, cid)
        # the old value: the count byte in the head, the read 3 clocks late (R93 for R90)
        sil, mod = _ev99("F38-out-shb-shl_m_imm4-pE-w0",
                         Config.fitted().replace(shift_mem_imm="rmw"))
        self.assertNotEqual(mod, sil)
        rd = lambda ev: next(e[0] for e in ev if e[1] == "data_read")
        self.assertEqual(rd(mod) - rd(sil), 3)

    def test_fetch_free_clocks_decide_po(self):
        # every write setup clock counting through a fetch (sthru 18): pE stays exact, the OUT pO
        # write comes on the read's end + 18 inside the fetch's shadow, 1 + w clocks early
        cfg = self._new().replace(**{"rmw_imm.sthru": 18})
        sil, mod = _ev99("F38-out-shb-shl_m_imm4-pE-w1", cfg)
        self.assertEqual(mod, sil)
        sil, mod = _ev99("F38-out-shb-shl_m_imm4-pO-w1", cfg)
        wr = lambda ev: next(e[0] for e in ev if e[1] == "data_write")
        self.assertEqual(wr(mod) - wr(sil), -2)

    def test_run_classes(self):
        # the fit's projection key: a count-byte memory shift reads rmw_imm's integers
        from validation.v35s.chains import fit
        c = next(c for c in generate(["F38"]) if c.id == "F38-out-shb-shl_m_imm4-pE-w0")
        classes, _ = fit.run_classes(c)
        self.assertIn("rmw_imm", classes)
        self.assertIn("shift_imm", classes)


# (WP101) the string forms' successors in F39: str_single_wb=index with uwb 2 (the hand start read
# off F39's series str) and str_single_start=write, over the tracked fit
WP101 = {"str_single_wb": "index", "str_single_start": "write",
         "str_move.uwb": 2, "str_cmp.uwb": 2, "str_in.uwb": 2}


def _ev101(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with WP101 (+ over)."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**WP101, **over}), s.chain_base)
    return aligned(s), aligned(m)


class StringSuccessorWP101(unittest.TestCase):
    """(WP101, F39) an unprefixed MOVBK, CMPBK or INM's last two exec clocks are a write-back
    (uwb 2) that the port OUT waits out in full, the next unprefixed string form all but its last
    clock, every other form not at all (str_single_wb=index); an unprefixed string form's first
    cycle issues no earlier than ugap + setup clocks after a memory write's last clock
    (str_single_start=write) (scratchpad wp101/facts.txt; clocks rel t_fill)."""

    def _exact(self, cid, **over):
        sil, mod = _ev101(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_default_is_the_old_behaviour(self):
        self.assertEqual(DEFAULT.str_single_wb, "none")
        self.assertEqual(OPTIONS["str_single_wb"], ("none", "wb", "index"))
        self.assertEqual(DEFAULT.str_single_start, "any")
        self.assertEqual(OPTIONS["str_single_start"], ("any", "delivery", "write"))

    def test_index_deciding_run(self):
        # MOVBK's write 103-105, no fetch (queue 5, room 1): the load starts 108, F108 D113
        mod = self._exact("F39-out-str-movbk-ld-pO-w0")
        self.assertIn((108, "fetch", 0x10054, "word", 3), mod)
        self.assertIn((113, "data_read", 0x0800, "word", 3), mod)
        # the old value with the tracked uwb 1: the load a clock later (F109)
        _, old = _ev101("F39-out-str-movbk-ld-pO-w0", str_single_wb="wb",
                        **{"str_move.uwb": 1})
        self.assertIn((109, "fetch", 0x10054, "word", 3), old)
        for cid in ("F39-out-str-cmpbk-push-pO-w1", "F39-out-str-inm-ld-pO-w2",
                    "F39-push-str-movbk-ld-pE-w0", "F39-push-ctl-cmpbk-s-pE-w2"):
            self._exact(cid)

    def test_index_keeps_the_second_instance(self):
        # uwb 2 under wb starts F24's second MOVBK a clock early (R116 for silicon's R117);
        # index holds it for all but the write-back's last clock
        mod = self._exact("F24-out-s-movbk-b-k2-pO-w0")
        self.assertIn((117, "data_read", 0x0A41, "hi", 3), mod)
        _, wb = _ev101("F24-out-s-movbk-b-k2-pO-w0", str_single_wb="wb")
        self.assertIn((116, "data_read", 0x0A41, "hi", 3), wb)
        for cid in ("F24-out-s-inm-w-k2-pO-w1", "F24-out-s-cmpbk-b-k2-pO-w2",
                    "F24-out-s-movbk-b-k1-pO-w0", "F24-out-s-cmpbk-b-k1-pE-w0",
                    "F39-out-str-movbk-out-pO-w0", "F39-out-str-inm-out-pE-w2"):
            self._exact(cid)

    def test_write_deciding_run(self):
        # M0's PUSH writes 78-80, MOVBK starts 81 on an idle bus: silicon reads at 90
        mod = self._exact("F39-push-ctl-movbk-s-pO-w0")
        self.assertIn((90, "data_read", 0x0A40, "word", 3), mod)
        _, old = _ev101("F39-push-ctl-movbk-s-pO-w0", str_single_start="delivery")
        self.assertIn((89, "data_read", 0x0A40, "word", 3), old)
        # at pE the fetch on its start clock already sets the read at 90: exact either way
        for over in ({}, {"str_single_start": "delivery"}):
            self._exact("F39-push-ctl-movbk-s-pE-w0", **over)
        for cid in ("F39-push-str-cmpbk-ld-pO-w1", "F39-push-str-inm-out-pO-w2",
                    "F39-push-str-movbk-push-pO-w0"):
            self._exact(cid)

    def test_rep_forms_untouched(self):
        for cid in ("F24-out-r-rep-movbk-b-n0-pE-w0", "F24-out-r-rep-movbk-b-n2-pO-w0",
                    "F24-out-r-rep-stm-w-n1-pE-w1"):
            _, new = _ev101(cid)
            _, old = _ev101(cid, str_single_wb="wb", str_single_start="delivery",
                            **{"str_move.uwb": 1, "str_cmp.uwb": 1, "str_in.uwb": 1})
            self.assertEqual(new, old, cid)

    def test_other_families_untouched(self):
        # no run without an unprefixed string form reads either value
        for fam in ("F14", "F21", "F23", "F35"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(**WP101), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted(), s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)


# (WP104, F40) the second instance's mechanisms, prototyped on the tracked fit with WP101's values
WP104 = {"one_idle": "flags", "xfer_nt": "dbnz_z", "br_reg.nx": 1, "brk_free": "format",
         "room_ir_pre": "test"}
# (fit 53) the pre-WP104 values, pinned for the "old" traces now that the tracked fit carries WP104's
_OLD104 = {"one_idle": "none", "xfer_nt": "odd", "br_reg.nx": 0, "brk_free": "type",
           "room_ir_pre": "none", "test_reg.nx": 1}


class SecondInstanceWP104(unittest.TestCase):
    """(WP104, F40) the second instance of the forms added since F23 (scratchpad wp104/facts.txt;
    clocks rel t_fill): a one-byte flag or INC/DEC r16 form started with the queue full and the bus
    idle runs a clock less, its last clock a write-back (one_idle=flags); a not-taken DBNZE holds
    its fetch request at either parity (xfer_nt=dbnz_z); BR r16's successor loads into the IR a
    clock after its ModR/M take (br_reg.nx 1); BRK 3 keeps 10 fetch-free clocks before its vector
    read (brk_free=format); TEST r,r counts the empty IR as room in its pre clocks
    (room_ir_pre=test). Each against its old value on its deciding run (_ev101: the tracked fit
    with WP101's values)."""

    def _exact(self, cid, **over):
        sil, mod = _ev101(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(DEFAULT.one_idle, "none")
        self.assertEqual(OPTIONS["one_idle"][:4], ("none", "flags", "reg1", "all1"))  # (WP114: + long)
        self.assertEqual(DEFAULT.xfer_nt, "none")
        self.assertEqual(OPTIONS["xfer_nt"], ("none", "odd", "dbnz_z", "dbnz"))
        self.assertEqual(DEFAULT.brk_free, "type")
        self.assertEqual(OPTIONS["brk_free"], ("type", "format"))
        self.assertEqual(DEFAULT.room_ir_pre, "none")
        self.assertEqual(OPTIONS["room_ir_pre"][:2], ("none", "test"))  # (WP114: + modrm)
        self.assertEqual(DEFAULT.c("br_reg", "nx"), 0)
        self.assertEqual(DEFAULT.c("brk", "rfree0"), 10)

    def test_one_idle_deciding_run(self):
        # LAHF starts 81 and 84 on fetch issues, 87 and 90 on an idle bus with the queue full:
        # silicon's PUSH AW writes at 97 (none: 99)
        mod = self._exact("F40-push-reg-lahf-k4-pO-w0", one_idle="flags")
        self.assertIn((97, "stack_write", 0x0EFC, "word", 3), mod)
        _, old = _ev101("F40-push-reg-lahf-k4-pO-w0", **_OLD104)
        self.assertIn((99, "stack_write", 0x0EFC, "word", 3), old)
        for cid in ("F40-push-page-stc-k4-pE-w1", "F40-push-page-incaw-k4-pO-w2",
                    # the port OUT waits out the write-back: as before
                    "F40-out-reg-lahf-k4-pO-w0", "F40-out-page-stc-k4-pO-w2",
                    # CVTBW keeps its three clocks (not in the class list)
                    "F40-push-page-cvtbw-k4-pO-w0", "F40-push-reg-lahf-k2-pO-w0"):
            self._exact(cid, one_idle="flags")

    def test_xfer_nt_dbnz_z_deciding_run(self):
        # the second DBNZE (even address, not taken) starts 103: silicon F109 (odd: F106)
        mod = self._exact("F40-out-xfer-dbnze-k2-pO-w0", xfer_nt="dbnz_z")
        self.assertIn((109, "fetch", 0x1005A, "word", 3), mod)
        _, old = _ev101("F40-out-xfer-dbnze-k2-pO-w0", **_OLD104)
        self.assertIn((106, "fetch", 0x1005A, "word", 3), old)
        for cid in ("F40-out-xfer-dbnze-k2-pE-w0", "F40-push-xfer-dbnze-k4-pE-w2",
                    "F40-out-ctl-dbnze-pO-w1"):
            self._exact(cid, xfer_nt="dbnz_z")

    def test_br_reg_nx_deciding_run(self):
        # the second BR BW starts 121 on the refill's delivery: silicon fetches there (nx 0: 124)
        mod = self._exact("F40-out-xfer-brbw-k2-pO-w0", **{"br_reg.nx": 1})
        self.assertIn((121, "fetch", 0x1005C, "word", 3), mod)
        _, old = _ev101("F40-out-xfer-brbw-k2-pO-w0", **_OLD104)
        self.assertIn((124, "fetch", 0x1005C, "word", 3), old)
        for cid in ("F40-out-xfer-brbw-k2-pE-w0", "F35-out-ind-brr-n0-pE-w0",
                    "F35-push-ind-brr-n1-pO-w2"):
            self._exact(cid, **{"br_reg.nx": 1})

    def test_brk_free_deciding_run(self):
        # the second BRK 3 starts 252 on F252's issue: silicon reads the vector at 264 (type: 263)
        mod = self._exact("F40-out-ind-brk3-k2-pE-w0", brk_free="format")
        self.assertIn((264, "data_read", 0x000C, "word", 3), mod)
        _, old = _ev101("F40-out-ind-brk3-k2-pE-w0", **_OLD104)
        self.assertIn((263, "data_read", 0x000C, "word", 3), old)
        for cid in ("F37-out-brk-brk3-pE-w0", "F37-out-brk-brk5-pE-w0",
                    "F37-push-brk-brk5-pO-w1"):
            self._exact(cid, brk_free="format")

    def test_room_ir_pre_deciding_run(self):
        # TEST DL,AL starts 81 on an idle bus with 5 bytes queued: silicon F81 (none: F84)
        mod = self._exact("F36-push-test-test_dl_al-pO-w0", room_ir_pre="test")
        self.assertIn((81, "fetch", 0x10052, "word", 3), mod)
        _, old = _ev101("F36-push-test-test_dl_al-pO-w0", **_OLD104)
        self.assertIn((84, "fetch", 0x10052, "word", 3), old)
        for cid in ("F36-out-test-test_dl_al-pO-w0", "F36-push-test-test_dl_al-pE-w1"):
            self._exact(cid, room_ir_pre="test")

    def test_old_families_untouched(self):
        # no sampled run of these families reads a WP104 value
        for fam in ("F5", "F14", "F21", "F24"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(**{**WP101, **WP104}),
                                          s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**WP101), s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)


WP107 = {"far_room": "take", "call_far_post": "take", "ret_far_fetch": "after",
         "ret_far_imm.setup": 7, "ret_far_imm.setup_free": 3}
# (fit 54) the pre-WP107 values, pinned for the "old" traces now that the tracked fit carries WP107's
_OLD107 = {"far_room": "none", "call_far_post": "sync", "ret_far_fetch": "hold",
           "ret_far_imm.setup": 6, "ret_far_imm.setup_free": 4}


class FarTransferWP107(unittest.TestCase):
    """(WP107, F35/F40) the far transfers (scratchpad wp107/facts.txt; clocks rel t_fill, the
    tracked fit with WP101's and WP104's values): BR far / CALL far with only the segment's last
    byte to take count no IR slot on a delivery clock (far_room=take); CALL far's first write at
    the later of the segment take + 6 and the last fetch's end + 3 (call_far_post=take, tsetup 6,
    tfree 3); RET far imm16's read at the later of its start + 6 and the last fetch's end + 3
    (ret_far_imm setup 7 / setup_free 3) and, with a whole-word immediate, its fetch back to back
    after the second read (ret_far_fetch=after). Each against its old value on its deciding run."""

    def _exact(self, cid, **over):
        sil, mod = _ev101(cid, **{**WP104, **over})
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(DEFAULT.far_room, "none")
        self.assertEqual(OPTIONS["far_room"], ("none", "take"))
        self.assertEqual(DEFAULT.call_far_post, "sync")
        self.assertEqual(OPTIONS["call_far_post"], ("sync", "take"))
        self.assertEqual(DEFAULT.ret_far_fetch, "hold")
        self.assertEqual(OPTIONS["ret_far_fetch"], ("hold", "after"))
        self.assertEqual(DEFAULT.c("call_far", "tsetup"), 6)
        self.assertEqual(DEFAULT.c("call_far", "tfree"), 3)

    def test_far_room_deciding_run(self):
        # CALL far (EOEOE) starts 84 on M0's I/O, its segment's low byte taken on 91, F88's
        # delivery: silicon F92 W98 (none: F91)
        mod = self._exact("F35-out-far-callf-pE-w0", **WP107)
        self.assertIn((92, "fetch", 0x10056, "word", 3), mod)
        _, old = _ev101("F35-out-far-callf-pE-w0", **{**WP104, **WP107, "far_room": "none"})
        self.assertIn((91, "fetch", 0x10056, "word", 3), old)
        for cid in ("F35-out-far-callf-pO-w0", "F35-push-far-callf-pO-w0",
                    "F40-out-xfer-brf-k2-pO-w1", "F40-out-xfer-callfretf-k4-pE-w0"):
            self._exact(cid, **WP107)

    def test_call_far_post_deciding_run(self):
        # the segment taken on 94, F90's delivery, F94 raised there: silicon W100 (sync: W101)
        mod = self._exact("F35-out-far-callf-pO-w1", **WP107)
        self.assertIn((100, "stack_write", 0x0EFE, "word", 4), mod)
        _, old = _ev101("F35-out-far-callf-pO-w1", **{**WP104, **_OLD107})
        self.assertIn((101, "stack_write", 0x0EFE, "word", 4), old)
        for cid in ("F35-out-far-callf-pE-w1", "F35-push-far-callf-pE-w2",
                    "F40-push-xfer-callfretf-k4-pO-w2"):
            self._exact(cid, **WP107)

    def test_ret_far_imm_read_and_fetch(self):
        # RETF 2 (OEO) starts on an idle bus: silicon S158 S169 F173 F182 (setup 6 / 4: S157;
        # ret_far_fetch=hold: no fetch, the refill F181)
        mod = self._exact("F35-out-far-callf-retf2-pO-w1", **WP107)
        self.assertIn((158, "stack_read", 0x0EFA, "word", 4), mod)
        self.assertIn((173, "fetch", 0x1005C, "word", 4), mod)
        _, old = _ev101("F35-out-far-callf-retf2-pO-w1",
                        **{**WP104, **WP107, "ret_far_fetch": "hold"})
        self.assertNotIn((173, "fetch", 0x1005C, "word", 4), old)
        self.assertIn((181, "fetch", 0x10053, "word", 4), old)
        # RETF 2 (EOE) starts on F143's issue: silicon S149 (setup 6 / 4: S150)
        self._exact("F35-out-far-callf-retf2-pE-w1", **WP107)
        _, old = _ev101("F35-out-far-callf-retf2-pE-w1",
                        **{**WP104, **WP107, "ret_far_imm.setup": 6, "ret_far_imm.setup_free": 4})
        self.assertIn((150, "stack_read", 0x0EFA, "word", 4), old)

    def test_br_far_refill_stays_a_fact(self):
        # BR far (EOEOE, w0): F95 committed back to back on the flush clock, silicon's refill at
        # its end + 4 (F101), the model's fgap 5 at F103
        sil, mod = _ev101("F35-out-far-brf-n0-pE-w0", **{**WP104, **WP107})
        self.assertIn((101, "fetch", 0x10053, "word", 3), sil)
        self.assertIn((103, "fetch", 0x10053, "word", 3), mod)

    def test_other_families_untouched(self):
        # no sampled run of these families reads a WP107 value
        for fam in ("F5", "F23", "F24", "F39"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**WP101, **WP104, **WP107}), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**{**WP101, **WP104}),
                                          s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)


# (WP106) the 0F register rotates' and TEST1 [m]'s wait-keyed trades read as structure
WP106_ROT4 = {"rot4_exec": "wait", "rol4.pre": 1, "rol4.exec": 13, "rol4.wb": 2}
WP106_TEST1 = {"test1_head": "set1", "page_commit": "post"}


class WaitKeyedWP106(unittest.TestCase):
    """(WP106, F32/F34/F39/F40) scratchpad wp106/facts.txt; clocks rel t_fill, the tracked fit with
    WP101's, WP104's and WP107's values. ROL4 / ROR4 on a register do not count an exec clock on
    which a fetch is in a wait state (rot4_exec=wait, with rol4.pre 1 / exec 13 / wb 2); TEST1 [m]
    runs SET1 [m]'s head (test1_head=set1) and a fetch committed back to back counts toward a 0F
    memory form's read setup only when committed after the read's post (page_commit=post). Each
    against its old value on its deciding run."""

    def _ev(self, cid, **over):
        return _ev101(cid, **{**WP104, **WP107, **over})

    def _exact(self, cid, **over):
        sil, mod = self._ev(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(DEFAULT.rot4_exec, "none")
        self.assertEqual(OPTIONS["rot4_exec"], ("none", "wait"))
        self.assertEqual(DEFAULT.test1_head, "own")
        self.assertEqual(OPTIONS["test1_head"], ("own", "set1"))
        self.assertEqual(DEFAULT.page_commit, "start")
        self.assertEqual(OPTIONS["page_commit"], ("start", "post"))

    def test_rot4_exec_deciding_run(self):
        # ROL4 DL starts 86 on M0's I/O; F89 (its take's) and F94 (committed back to back) run
        # through its exec: silicon reads at 114, 16 clocks after F94's last at every wait (none,
        # with the same integers: 112)
        mod = self._exact("F39-out-page-rol4-ld-pE-w2", **WP106_ROT4)
        self.assertIn((114, "data_read", 0x0800, "word", 5), mod)
        _, old = self._ev("F39-out-page-rol4-ld-pE-w2", **{**WP106_ROT4, "rot4_exec": "none"})
        self.assertIn((112, "data_read", 0x0800, "word", 5), old)
        for cid in ("F39-out-page-rol4-ld-pE-w0", "F39-out-page-rol4-ld-pE-w1",
                    "F39-push-ctl-rol4-pO-w1", "F39-out-page-rol4-out-pO-w2",
                    "F32-out-rol4_dl-k2-pE-w0", "F32-out-ror4_dl-k1-pE-w2",
                    "F40-out-page-rol4-k4-pE-w1", "F40-push-page-rol4-k2-pO-w0"):
            self._exact(cid, **WP106_ROT4)

    def test_test1_head_deciding_run(self):
        # TEST1 [BW],CL (even address) starts 81 on F81's issue: silicon F84 back to back, D92
        # (own: the ModR/M taken at 86, F86 D94)
        mod = self._exact("F39-push-page-test1-ld-pO-w0", **WP106_TEST1)
        self.assertIn((84, "fetch", 0x10054, "word", 3), mod)
        self.assertIn((92, "data_read", 0x0800, "word", 3), mod)
        # bit1_test.pre pinned at its pre-WP122 value 4 (the sixty-second fit, 2026-11-01, moved
        # it to 1, which fetches at 84 under test1_head=own as well)
        _, old = self._ev("F39-push-page-test1-ld-pO-w0",
                          **{**WP106_TEST1, "test1_head": "own", "bit1_test.pre": 4})
        self.assertIn((86, "fetch", 0x10054, "word", 3), old)
        for cid in ("F39-push-page-test1-ld-pO-w1", "F32-out-test1_mw_cl-k2-pE-w1",
                    "F34-out-mbit-test1_mw_cl-sep-k1-pE-w2", "F40-out-page-test1-k4-pO-w2",
                    "F32-out-test1_mw_imm-k2-pE-w0"):
            self._exact(cid, **WP106_TEST1)

    def test_page_commit_deciding_run(self):
        # DS1: at 84, TEST1 [BW],CL at 86; F90 committed on F87's last clock (89), before the
        # read's post (95): silicon D98, 6 fetch-free clocks after F90's last (start: D95)
        mod = self._exact("F32-out-pfx_test1_mw_cl-k1-pE-w0", **WP106_TEST1)
        self.assertIn((98, "data_read", 0x0800, "word", 3), mod)
        _, old = self._ev("F32-out-pfx_test1_mw_cl-k1-pE-w0",
                          **{**WP106_TEST1, "page_commit": "start"})
        self.assertIn((95, "data_read", 0x0800, "word", 3), old)
        for cid in ("F32-out-pfx_test1_mw_cl-k1-pO-w1", "F32-out-test1_mw_cl-k1-pE-w0"):
            self._exact(cid, **WP106_TEST1)

    def test_odd_fetch_issue_start_stays_a_fact(self):
        # TEST1 [BW],CL at an odd address starts on F94's issue with 5 bytes queued behind MOV
        # AW,1234h: silicon runs no fetch before its read (D102), the SET1 head one back to back
        sil, mod = self._ev("F34-out-mbit-test1_mw_cl-d-k1-pE-w0", **WP106_TEST1)
        self.assertIn((102, "data_read", 0x0800, "word", 3), sil)
        # (fit 57) WP112's page_ir=delivery holds the successor out of the IR until the read issues:
        # the back-to-back fetch at 97 is gone and the run is exact; under the old value it stays
        self.assertEqual(mod, sil)
        _, old = self._ev("F34-out-mbit-test1_mw_cl-d-k1-pE-w0", **{**WP106_TEST1, "page_ir": "none"})
        self.assertIn((97, "fetch", 0x1005A, "word", 3), old)

    def test_other_families_untouched(self):
        # no sampled run of these families reads a WP106 value
        for fam in ("F5", "F23", "F24", "F33", "F38"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**WP101, **WP104, **WP107, **WP106_ROT4, **WP106_TEST1}), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**WP101, **WP104, **WP107}), s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)



WP109 = {"mul_imm_count": "sync", "mul_imm_half": "room", "mul_imm_exec": "hold",
         "mul_data": "sign", "mul.smexec": 39}
# (fit 54) the pre-WP109 values, pinned for the "old" traces so they hold after an adoption: the
# four enums and mul.smexec, and the tracked values the MUL imm memory template reads with them
_OLD109 = {"mul_imm_count": "post", "mul_imm_half": "hold", "mul_imm_exec": "free",
           "mul_data": "none", "mul.smexec": 49, "mul_imm_read": "issue", "mul_imm_hold": "word",
           "mul_imm.rsetup": 2, "mul_imm.mhold": 41, "mul_imm.mexec": 43, "mul_imm.hphase": 2,
           "unit_hold": True}
_KEEP109 = {k: v for k, v in _OLD109.items() if k not in WP109}


def _ev109(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with the MUL imm
    template's tracked values pinned (_KEEP109) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**_KEEP109, **over}),
                            s.chain_base)
    return aligned(s), aligned(m)


class MulImmWP109(unittest.TestCase):
    """(WP109, F33/F34) the multiply's read and exec (scratchpad wp109/facts.txt; clocks rel
    t_fill): MUL imm memory's read counts rsetup and a clock per immediate byte from the clock
    after its EA clocks, restarted by a non-fetch cycle (the EU's previous request) or a fetch
    issued before that clock, a fetch issued on or after it running inside the count
    (mul_imm_count=sync); its half-taken immediate word holds fetch requests only while the queue
    has no room for a word besides the taken byte (mul_imm_half=room); its exec waits while a
    fetch is past its second clock, each such fetch costing its wait states + 1
    (mul_imm_exec=hold); MUL r/m16's exec adds the data book's sign clocks (mul_data=sign, with
    smexec the equal-sign cost 39). Each against its old value on its deciding run."""

    def _exact(self, cid, **over):
        sil, mod = _ev109(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(OPTIONS["mul_imm_count"], ("post", "sync"))
        self.assertEqual(OPTIONS["mul_imm_half"], ("hold", "room"))
        self.assertEqual(OPTIONS["mul_imm_exec"], ("free", "hold", "unit"))
        self.assertEqual(OPTIONS["mul_data"], ("none", "sign"))
        for name in ("mul_imm_count", "mul_imm_half", "mul_imm_exec", "mul_data"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)

    def test_mul_data_operands(self):
        regs = dict(FORMS_REGS)
        # AW = 0 x [BW] = 9090h (the fill): signs differ, the product's halves both zero
        self.assertEqual(decode(bytes([0xF7, 0x2F]), 0, {**regs, "AW": 0}).mneg, 10)
        self.assertEqual(decode(bytes([0xF7, 0x2F]), 0, {**regs, "AW": 0x1234}).mneg, 8)
        self.assertEqual(decode(bytes([0xF7, 0xE9]), 0, {**regs, "AW": 0x1234,
                                                         "CW": 0x001F}).mneg, 0)
        self.assertEqual(decode(bytes([0xF7, 0x27]), 0, {**regs, "AW": 0}).mneg, 0)   # MULU

    def test_count_deciding_runs(self):
        # the fetch on the start clock (88-91) and the committed one (92-95): silicon R97 =
        # 92 + rsetup 2 + 2 + the issue clock (post: R98)
        mod = self._exact("F34-out-mul-mul_aw_m_imm16-nop-k1-pE-w1", **WP109)
        self.assertIn((97, "data_read", 0x0800, "word", 4), mod)
        _, old = _ev109("F34-out-mul-mul_aw_m_imm16-nop-k1-pE-w1", **_OLD109)
        self.assertIn((98, "data_read", 0x0800, "word", 4), old)
        # M0's port write 85-87 restarts the count: silicon R92 (post: R90)
        self._exact("F34-out-mul-mul_aw_m_imm16-l0-k1-pO-w0", **WP109)
        _, old = _ev109("F34-out-mul-mul_aw_m_imm16-l0-k1-pO-w0",
                        **{**WP109, "mul_imm_count": "post"})
        self.assertIn((90, "data_read", 0x0800, "word", 3), old)
        for cid in ("F34-out-mul-mul_aw_m_imm8-l0-k1-pO-w2", "F33-out-mul_aw_m_imm16-k2-pE-w1",
                    "F34-out-mul-mul_aw_m_imm16-nop-k1-pE-w0"):
            self._exact(cid, **WP109)

    def test_half_deciding_run(self):
        # an idle start, 2 bytes left after the immediate: silicon R119 F122 F125 (hold: F163)
        mod = self._exact("F34-out-mul-mul_aw_m_imm16-sep-k1-pE-w0", **WP109)
        self.assertIn((122, "fetch", 0x10058, "word", 3), mod)
        _, old = _ev109("F34-out-mul-mul_aw_m_imm16-sep-k1-pE-w0",
                        **{**WP109, "mul_imm_half": "hold"})
        self.assertIn((163, "fetch", 0x10058, "word", 3), old)

    def test_exec_deciding_run(self):
        # R92, the fetch 96-99 in the exec: silicon F146 O154 (free: F144 O152)
        mod = self._exact("F34-out-mul-mul_aw_m_imm16-l0-k1-pE-w1", **WP109)
        self.assertIn((146, "fetch", 0x10058, "word", 4), mod)
        _, old = _ev109("F34-out-mul-mul_aw_m_imm16-l0-k1-pE-w1", **_OLD109)
        self.assertIn((144, "fetch", 0x10058, "word", 4), old)

    def test_data_deciding_run(self):
        # MUL [BW] with AW = 1234h: silicon F161 (none, smexec 49: F163); AW = 0 exact under both
        mod = self._exact("F33-out-mul_m-ld-k1-pE-w0", **WP109)
        self.assertIn((161, "fetch", 0x1005C, "word", 3), mod)
        _, old = _ev109("F33-out-mul_m-ld-k1-pE-w0", **_OLD109)
        self.assertIn((163, "fetch", 0x1005C, "word", 3), old)
        for cid in ("F33-out-mul_m-k1-pE-w0", "F16-r-push-mul-pO-w0"):
            self._exact(cid, **WP109)
            self._exact(cid, **_OLD109)

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP109's values
        for fam in ("F3", "F14", "F16", "F32"):
            for run in _runs(fam)[::50]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**_KEEP109, **WP109}), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**_OLD109),
                                          s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)



WP112_IR = {"page_ir": "delivery"}
WP112_DIO = {"page_dio": "free"}
WP112_CL = {"page_cl": "thru"}
WP112_TAIL = {"bf_ext.ftail": 2, "bf_ins.ftail": 2}
WP112 = {**WP112_IR, **WP112_DIO, **WP112_CL, **WP112_TAIL}
# (fit 55) the pre-WP112 values, pinned for the "old" traces so they hold after an adoption: the
# three enums and the two ftail integers, and the tracked values the 0F memory and bit-field
# templates read with them
_OLD112 = {"page_ir": "none", "page_dio": "extend", "page_cl": "free",
           "bf_ext.ftail": 0, "bf_ins.ftail": 0,
           "page_mem": "fixed", "page_run": "field", "page_take": "own", "page_grp": "group",
           "page_imm_run": "delivery", "page_commit": "start", "test1_head": "own",
           "bf_read": "fixed", "bf_imm_hold": "word", "ir_load": "disp_data", "disp_io": "extend",
           "hold_fetch": "le_q", "hold_run": False,
           "bit1_rmw.fsetup": 3, "bit1_rmw.cl": 3, "bit1_rmw.pre": 1,
           "bf_ext.fsetup": 7, "bf_ins.fsetup": 7, "bf_ext.pre": 1, "bf_ins.pre": 1}
_KEEP112 = {k: v for k, v in _OLD112.items() if k not in WP112}


def _ev112(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with the 0F memory
    and bit-field values pinned (_KEEP112) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**_KEEP112, **over}),
                            s.chain_base)
    return aligned(s), aligned(m)


def _at112(events):
    """(clock, kind) of each event."""
    return [(e[0], e[1]) for e in events]


class PageFormsWP112(unittest.TestCase):
    """(WP112, F32/F34) the 0F memory forms' and bit fields' remaining misses (scratchpad
    wp112/facts.txt; clocks rel t_fill). A 0F memory form whose last operand byte is taken on a
    word's delivery clock keeps its successor out of the IR until its read issues (page_ir=
    delivery); a displacement taken on an I/O cycle's issue clock by a 0F memory form does not
    hold that cycle a clock longer (page_dio=free); a 0F memory form's read with the bit index
    in CL counts its CL clocks through a fetch requested after the read's post (or by its
    two-byte displacement's take), its fsetup clocks fetch-free (page_cl=thru); a bit field's
    first read issues only ftail (+ the imm4 width byte) clocks after the last fetch's end
    (bf_ext / bf_ins ftail 2). Each against its old value on its deciding run."""

    def _exact(self, cid, **over):
        sil, mod = _ev112(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(OPTIONS["page_ir"], ("none", "delivery"))
        self.assertEqual(OPTIONS["page_dio"], ("extend", "free"))
        self.assertEqual(OPTIONS["page_cl"], ("free", "thru"))
        for name in ("page_ir", "page_dio", "page_cl"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        self.assertEqual(DEFAULT.c("bf_ext", "ftail"), 0)
        self.assertEqual(DEFAULT.c("bf_ins", "ftail"), 0)

    def test_page_ir_deciding_run(self):
        # SET1 [BW],CL behind MOV AW,imm at an odd address, started on F94's issue with 5 bytes
        # queued; its ModR/M taken on F94's delivery clock 97: silicon no fetch, R102 (none: the
        # IR loads, F97, R105)
        cid = "F34-out-mbit-set1_mw_cl-d-k1-pE-w0"
        mod = self._exact(cid, **WP112_IR)
        self.assertIn((102, "data_read"), _at112(mod))
        self.assertNotIn((97, "fetch"), _at112(mod))
        _, old = _ev112(cid, **_OLD112)
        self.assertIn((97, "fetch"), _at112(old))
        self.assertIn((105, "data_read"), _at112(old))
        # the two-byte displacement taken on a delivery clock: no fetch before the read
        self._exact("F34-out-mbit-set1_mw_cl_bw_d16-d-k1-pO-w0", **WP112_IR)

    def test_page_dio_deciding_run(self):
        # SET1 [BW+10h],CL takes its displacement on M0's I/O issue clock 85: silicon F88 right
        # after the I/O (extend: F89, R97)
        cid = "F34-out-mbit-set1_mw_cl_bw_d8-l0-k1-pO-w0"
        mod = self._exact(cid, **WP112_DIO)
        self.assertIn((88, "fetch"), _at112(mod))
        self.assertIn((96, "data_read"), _at112(mod))
        _, old = _ev112(cid, **_OLD112)
        self.assertIn((89, "fetch"), _at112(old))
        self.assertIn((97, "data_read"), _at112(old))

    def test_page_cl_deciding_runs(self):
        # SET1 [BW+200h],CL under M0's OUT: the refill F87, F90 back to back, the fetch the queue
        # asks on F90's last clock runs back to back (F93) inside the read's CL clocks: silicon
        # R96 (free: no F93, R95)
        cid = "F34-out-mbit-set1_mw_cl_bw_d16-l0-k1-pE-w0"
        mod = self._exact(cid, **WP112_CL)
        self.assertIn((93, "fetch"), _at112(mod))
        self.assertIn((96, "data_read"), _at112(mod))
        _, old = _ev112(cid, **_OLD112)
        self.assertNotIn((93, "fetch"), _at112(old))
        self.assertIn((95, "data_read"), _at112(old))
        # the displacement's own fetch F100 (3 fetch-free clocks after F94's end) runs inside
        # the setup: silicon R103 (free: F100 restarts the count, R108)
        cid = "F34-out-mbit-set1_mw_cl_bw_d16-d-k1-pE-w0"
        mod = self._exact(cid, **WP112_CL)
        self.assertIn((103, "data_read"), _at112(mod))
        _, old = _ev112(cid, **_OLD112)
        self.assertIn((108, "data_read"), _at112(old))
        # the displacement's fetch waits out fsetup: silicon F97, 3 clocks after F91's end, R100
        # (free: F94 back to back, R102)
        cid = "F34-out-mbit-set1_mw_cl_bw_d16-nop-k1-pE-w0"
        mod = self._exact(cid, **WP112_CL)
        self.assertIn((97, "fetch"), _at112(mod))
        _, old = _ev112(cid, **_OLD112)
        self.assertIn((94, "fetch"), _at112(old))
        # the plain and d8 forms are exact under both
        for c in ("F34-out-mbit-set1_mw_cl-l0-k1-pE-w0", "F34-out-mbit-set1_mw_cl-l0-k1-pO-w1",
                  "F34-out-mbit-set1_mw_cl_bw_d8-l0-k1-pO-w1"):
            self._exact(c, **WP112_CL)
            self._exact(c, **_OLD112)

    def test_ftail_deciding_run(self):
        # EXT BL,DH under M0's OUT at 2 waits: the refill F89, F94 committed back to back; silicon
        # R101, 2 fetch-free clocks after F94's last (98) (0: R100); at 1 wait exact under both
        cid = "F34-out-bf-ext_bl_dh-l0-k1-pE-w2"
        mod = self._exact(cid, **WP112_TAIL)
        self.assertIn((101, "data_read"), _at112(mod))
        _, old = _ev112(cid, **_OLD112)
        self.assertIn((100, "data_read"), _at112(old))
        for c in ("F34-out-bf-ext_bl_dh-l0-k1-pE-w1", "F34-out-bf-ext_bl_i7-l0-k1-pE-w0"):
            self._exact(c, **WP112_TAIL)
            self._exact(c, **_OLD112)
        self._exact("F34-out-bf-ext_bl_i7-l0-k1-pE-w2", **WP112_TAIL)

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP112's values
        for fam in ("F14", "F21", "F33", "F38"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**_KEEP112, **WP112}), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**_OLD112),
                                          s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)


# (WP114, F32/F33/F40) the register miscellany's remaining misses (scratchpad wp114/facts.txt)
WP114_R8 = {"room_ir_pre": "modrm", "incdec.nx": 0, "incdec.rwb": 0}
WP114_LONG = {"long_exec": "wait"}
WP114_IDLE = {"one_idle": "long"}
WP114_CVT = {"cvt_hold": "word", "convert.hrel": 1, "convert_d.hrel": 3}
WP114_MUL = {"mul_imm_reg": "gap", "mul_imm.igap": 2}
WP114_BCD = {"bcd_fetch": "hold", "bcd4s.hrel": 2, "bcd4s_cmp.hrel": 2}
WP114 = {**WP114_R8, **WP114_LONG, **WP114_IDLE, **WP114_CVT, **WP114_MUL, **WP114_BCD}
# the pre-WP114 values, pinned for the "old" traces so they hold after an adoption: the enums and
# integers WP114 moves (incdec.rwb 1 = incdec.wb, the old write-back of INC / DEC r8), WP112's
# candidate values (the base WP114 scored against) and the tracked values these forms read
_OLD114 = {"room_ir_pre": "test", "incdec.nx": 1, "incdec.rwb": 1, "long_exec": "none",
           "one_idle": "flags", "cvt_hold": "none", "mul_imm_reg": "take", "bcd_fetch": "free",
           "page_ir": "delivery", "page_dio": "free", "page_cl": "thru",
           "bf_ext.ftail": 2, "bf_ins.ftail": 2,
           "room_ir": "arrival_idle", "take_sync": "pending", "wb_fetch": "hold",
           "imm_latch": "wait", "unit_hold": True, "rot4_exec": "wait",
           "mul_imm_count": "sync", "mul_imm_half": "room", "mul_imm_exec": "hold",
           "incdec.wb": 1, "incdec.pre": 3, "incdec.exec": 0,
           "extend_w.pre0": 9, "extend_w.nx0": 8, "extend_w.wb": 3,
           "adjust.pre0": 10, "adjust.nx0": 8, "adjust.wb": 2,
           "flag_di.pre0": 4, "flag_di.nx0": 3, "flag_di.wb": 3,
           "convert.pre": 3, "convert.exec": 16, "convert.wb": 2,
           "convert_d.pre": 2, "convert_d.exec": 16, "convert_d.wb": 0,
           "mul_imm.exec": 35, "mul_imm.pre": 0,
           "bcd4s.first": 16, "bcd4s.mid": 7, "bcd4s.wmid": 10, "bcd4s.loop": 7,
           "bcd4s.exec": 12, "bcd4s_cmp.first": 16, "bcd4s_cmp.exec": 20}
_KEEP114 = {k: v for k, v in _OLD114.items() if k not in WP114}


def _ev114(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with the values
    WP114's forms read pinned (_KEEP114) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**_KEEP114, **over}),
                            s.chain_base)
    return aligned(s), aligned(m)


def _at114(events):
    """(clock, kind) of each event."""
    return [(e[0], e[1]) for e in events]


class MiscellanyWP114(unittest.TestCase):
    """(WP114, F32/F33/F40) INC / DEC r8 runs MOV CL,imm8's EU timing, its (and TEST r,r's)
    ModR/M byte latched with the opcode for the room rule (room_ir_pre=modrm, incdec.nx 0,
    incdec.rwb 0); the long one-byte forms' clocks do not count a fetch's wait clocks
    (long_exec=wait) and, started with the queue full on an idle bus, save a clock of their own
    (one_idle=long); CVTBD / CVTDB with the constant byte the even half of its word hold fetch
    requests from its take to hrel clocks before the end (cvt_hold=word); MUL r16,r16,imm takes
    its immediate igap clocks after its ModR/M byte (mul_imm_reg=gap); the BCD strings hold
    fetch requests from the first read to hrel clocks before the end, the first read a clock
    later on an idle start (bcd_fetch=hold). Each against its old value on its deciding run
    (clocks rel t_fill)."""

    def _exact(self, cid, **over):
        sil, mod = _ev114(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(OPTIONS["room_ir_pre"], ("none", "test", "modrm"))
        self.assertEqual(OPTIONS["one_idle"], ("none", "flags", "reg1", "all1", "long"))
        self.assertEqual(OPTIONS["cvt_hold"], ("none", "word"))
        self.assertEqual(OPTIONS["long_exec"], ("none", "wait"))
        self.assertEqual(OPTIONS["mul_imm_reg"], ("take", "gap"))
        self.assertEqual(OPTIONS["bcd_fetch"], ("free", "hold"))
        for name in ("room_ir_pre", "one_idle", "cvt_hold", "long_exec", "mul_imm_reg",
                     "bcd_fetch"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        # incdec.rwb absent: INC / DEC r8 writes back incdec.wb clocks, as before
        self.assertNotIn("rwb", DEFAULT.cost["incdec"])

    def test_incdec_r8_deciding_runs(self):
        # the second INC AL (FE at an odd address) starts 91 on an idle bus with 6 bytes queued:
        # silicon F91 (old: F94)
        cid = "F33-out-inc_al-k2-pO-w0"
        mod = self._exact(cid, **WP114_R8)
        self.assertIn((91, "fetch"), _at114(mod))
        _, old = _ev114(cid, **_OLD114)
        self.assertIn((94, "fetch"), _at114(old))
        self.assertNotIn((91, "fetch"), _at114(old))
        # INC AL after M0's OUT at 1 wait: the OUT starts on the clock after the take's fetch,
        # its fetch back to back, silicon F92 (old: the write-back holds it, F96)
        cid = "F33-out-inc_al-k1-pE-w1"
        mod = self._exact(cid, **WP114_R8)
        self.assertIn((92, "fetch"), _at114(mod))
        _, old = _ev114(cid, **_OLD114)
        self.assertIn((96, "fetch"), _at114(old))
        # 5 bytes queued under the PUSH frame: silicon F81 F84 (old F84 F87); TEST DL,AL's 6-byte
        # cell; INC AW and MOV CL,imm8's cells exact under both
        self._exact("F33-push-inc_al-k1-pO-w0", **WP114_R8)
        self._exact("F40-out-reg-testdl-k2-pO-w0", **WP114_R8)
        for c in ("F33-out-inc_aw-k2-pO-w0", "F3-out-mov_cl_imm-k2-pO-w0",
                  "F33-out-dec_dh-k1-pE-w0"):
            self._exact(c, **WP114_R8)
            self._exact(c, **_OLD114)

    def test_long_exec_deciding_run(self):
        # CVTWL started on F95's issue at 2 waits: silicon F112 (none: F110)
        cid = "F33-out-cvtwl-a8080-k1-pE-w2"
        mod = self._exact(cid, **WP114_LONG)
        self.assertIn((112, "fetch"), _at114(mod))
        _, old = _ev114(cid, **_OLD114)
        self.assertIn((110, "fetch"), _at114(old))
        self._exact("F33-push-adj4a-k1-pE-w2", **WP114_LONG)
        self._exact("F33-out-cvtwl-a8080-k1-pE-w0", **WP114_LONG)

    def test_one_idle_long_deciding_run(self):
        # the second CLI starts 90 on an idle bus with 6 bytes queued: silicon F99, the OUT's I/O
        # at 106 (flags: F100, 107: the saved clock a write-back)
        cid = "F33-out-cli-k2-pE-w0"
        mod = self._exact(cid, **WP114_IDLE)
        self.assertIn((99, "fetch"), _at114(mod))
        self.assertIn((106, "io_write"), _at114(mod))
        _, old = _ev114(cid, **_OLD114)
        self.assertIn((100, "fetch"), _at114(old))
        self.assertIn((107, "io_write"), _at114(old))
        for c in ("F33-out-adjba-k2-pE-w1", "F33-out-cvtwl-k2-pE-w2", "F33-out-sti-k2-pE-w0"):
            self._exact(c, **WP114_IDLE)
        # ADJ4A's identical cells stay exact (the adjust class is not in long)
        self._exact("F33-out-adj4a-k2-pE-w0", **WP114_IDLE)

    def test_cvt_hold_deciding_runs(self):
        # CVTBD at an odd address on M0's I/O issue (86), its constant byte taken at 89 with the
        # next opcode the word's odd half: silicon F105 F117 I121 (none: F89 F119 I123)
        cid = "F33-out-cvtbd-k1-pO-w1"
        mod = self._exact(cid, **WP114_CVT)
        self.assertIn((105, "fetch"), _at114(mod))
        self.assertNotIn((89, "fetch"), _at114(mod))
        _, old = _ev114(cid, **_OLD114)
        self.assertIn((89, "fetch"), _at114(old))
        # the PUSH twin, same alignment, takes the byte on F81's delivery clock 84: F84 under both
        cid = "F33-push-cvtbd-k1-pE-w0"
        mod = self._exact(cid, **WP114_CVT)
        self.assertIn((84, "fetch"), _at114(mod))
        self._exact(cid, **_OLD114)
        self._exact("F33-out-cvtdb-k1-pO-w2", **WP114_CVT)

    def test_mul_imm_reg_deciding_run(self):
        # the second MUL AW,CW,imm16 starts 128 on an idle bus: silicon F132 F135 (take: F130 F133)
        cid = "F33-out-mul_aw_cw_imm16-k2-pO-w0"
        mod = self._exact(cid, **WP114_MUL)
        self.assertIn((132, "fetch"), _at114(mod))
        _, old = _ev114(cid, **_OLD114)
        self.assertIn((130, "fetch"), _at114(old))
        for c in ("F33-out-mul_aw_cw_imm8-k2-pE-w1", "F33-push-mul_aw_cw_imm16-k1-pE-w0",
                  "F33-out-mul_aw_cw_imm16-k1-pE-w0"):
            self._exact(c, **WP114_MUL)

    def test_bcd_fetch_deciding_run(self):
        # the second ADD4S starts 144 on an idle bus with room for a word: silicon D160 D169 W181
        # F194 (free: D159 D168 W180 F183)
        cid = "F32-out-add4s-n2-k2-pO-w0"
        mod = self._exact(cid, **WP114_BCD)
        self.assertIn((160, "data_read"), _at114(mod))
        self.assertIn((194, "fetch"), _at114(mod))
        _, old = _ev114(cid, **_OLD114)
        self.assertIn((159, "data_read"), _at114(old))
        self.assertIn((183, "fetch"), _at114(old))
        for c in ("F32-out-cmp4s-n4-k2-pO-w1", "F40-push-page-add4s-k2-pE-w0",
                  "F32-out-add4s-n2-k2-pE-w0", "F32-out-pfx_add4s-n4-k1-pO-w2"):
            self._exact(c, **WP114_BCD)

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP114's values
        for fam in ("F3", "F14", "F16", "F21", "F36"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**_KEEP114, **WP114}), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**_OLD114),
                                          s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)


# (WP116, F32/F34/F39/F40) the "lead-keyed" start states of the 0F forms (scratchpad
# wp116/facts.txt): behind MOV AW,1234h the 0F form was ready on the issue clock of a fetch the bus
# unit committed back to back and the model held its start there (start_sync=b2b_modrm) until the
# next fetch's issue, so its start state looked identical to the NOP NOP / k = 2 / MOV CL,imm8
# starts; a 0F register form or bit field starts on that clock (page_start=reg), and started at an
# odd address on a word's delivery clock with a fetch issued there it takes its ModR/M byte only
# after that fetch's word is delivered, the loader keeping the successor's IR load (page_mtake=eu)
WP116 = {"page_start": "reg", "page_mtake": "eu"}
# the pre-WP116 values, pinned for the "old" traces so they hold after an adoption, with the
# tracked values these forms read
_OLD116 = {"page_start": "hold", "page_mtake": "none", "start_sync": "b2b_modrm",
           "page_take": "own", "page_b2b": "reg", "page_b2b_win": "run",
           "bit1.pre": 1, "bit1.nx": 5, "bit1.exec": 2, "bit1.wb": 2, "bit1.cl": 0,
           "bf_ext.pre": 1, "bf_ext.nx": 1, "bf_ext.ftail": 2}
_KEEP116 = {k: v for k, v in _OLD116.items() if k not in WP116}


def _ev116(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with WP114's
    candidate values (the base WP116 scored against), the values WP116's forms read pinned
    (_KEEP116) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(
        **{**_KEEP114, **WP114, **_KEEP116, **over}), s.chain_base)
    return aligned(s), aligned(m)


class PageStartWP116(unittest.TestCase):
    """(WP116) a 0F register form or bit field starts on a back-to-back fetch's issue clock
    (page_start=reg); started at an odd address on a word's delivery clock with a fetch issued
    there, it takes its ModR/M byte on the clock after that fetch's word is delivered, its
    successor's IR load where the take would have put it (page_mtake=eu). Each against its old
    value on its deciding run."""

    def _exact(self, cid, **over):
        sil, mod = _ev116(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(OPTIONS["page_start"], ("hold", "b2b", "reg"))
        self.assertEqual(OPTIONS["page_mtake"], ("none", "deliver", "eu"))
        for name in ("page_start", "page_mtake"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)

    def test_page_start_deciding_run(self):
        # SET1 AW,CL behind MOV AW,1234h: MOV's take sync ends on F91's delivery 94, F94 committed
        # back to back; silicon F97 back to back after F94, the OUT's I/O at 111 (hold: SET1
        # starts 97, F105, I/O 112)
        cid = "F34-out-rbit-set1_rw_cl-d-k1-pE-w0"
        mod = self._exact(cid, page_start="reg")
        self.assertIn((97, "fetch"), _at114(mod))
        self.assertIn((111, "io_write"), _at114(mod))
        _, old = _ev116(cid, **_OLD116)
        self.assertNotIn((97, "fetch"), _at114(old))
        self.assertIn((105, "fetch"), _at114(old))
        self.assertIn((112, "io_write"), _at114(old))
        # the w1 cell and the direct-mode memory form (left out of reg) exact under both
        for c in ("F34-out-rbit-set1_rw_cl-d-k1-pE-w1",
                  "F34-out-mbit-set1_mw_cl_dir-d-k1-pE-w1"):
            self._exact(c, **WP116)
            self._exact(c, **_OLD116)

    def test_page_mtake_deciding_run(self):
        # EXT BL,DH behind NOP NOP at an odd address starts on F94's issue (F90's word delivered
        # there): silicon reads at 106 (none: the ModR/M taken inside F94, D104)
        cid = "F34-out-bf-ext_bl_dh-nop2-k1-pO-w1"
        mod = self._exact(cid, **WP116)
        self.assertIn((106, "data_read"), _at114(mod))
        _, old = _ev116(cid, **_OLD116)
        self.assertIn((104, "data_read"), _at114(old))
        # the same form behind MOV AW,1234h (now started on the back-to-back fetch's issue) and
        # the second EXT at k = 2
        for c in ("F34-out-bf-ext_bl_dh-d-k1-pE-w1", "F32-out-ext_dl_i7-k2-pO-w0"):
            self._exact(c, **WP116)

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP116's values
        base = {**_KEEP114, **WP114, **_KEEP116}
        for fam in ("F3", "F14", "F33", "F36"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(**{**base, **WP116}),
                                          s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**{**base, **_OLD116}),
                                          s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)


# (WP118, F32/F34/F39/F40) after the ModR/M take page_mtake=eu holds (scratchpad wp118/facts.txt): a
# 0F register bit op at an odd address started on a word's delivery clock with a fetch issued there
# takes its ModR/M byte on the clock after that fetch's word is delivered; the byte reaches the EU a
# clock late, so the bit op's ALU clocks start mtx clocks after the take (a take sync waiting longer
# hides it, and a bit field's read, which does not wait for the ModR/M, is not held), its end and
# write-back move with them, the loader keeping its schedule (page_mt_end=exec). The successor sees
# it through the port OUT's write-back sync (every w) and through the EU's next start for PUSH and
# SET1 (w1 and w2; at w0 the loader's IR load is the later of the two)
WP118 = {"page_mt_end": "exec", "bit1.mtx": 1}
# the pre-WP118 values, pinned for the "old" traces so they hold after an adoption, with the
# values these forms read (WP116's candidate pair included)
_OLD118 = {"page_mt_end": "none", "page_mem_from": "start", "page_disp": "go",
           "page_start": "reg", "page_mtake": "eu", "bit1.pre": 1, "bit1.nx": 5, "bit1.exec": 2,
           "bit1.wb": 2, "bit1.cl": 0, "out.wbsync": 1, "out.pre": 3}
_KEEP118 = {k: v for k, v in _OLD118.items() if k not in WP118}


def _ev118(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with WP114's and
    WP116's candidate values (the base WP118 scored against), the values WP118's forms read pinned
    (_KEEP118) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(
        **{**_KEEP114, **WP114, **_KEEP116, **WP116, **_KEEP118, **over}), s.chain_base)
    return aligned(s), aligned(m)


class PageMtEndWP118(unittest.TestCase):
    """(WP118) after the ModR/M take page_mtake=eu holds, the bit op's ALU clocks start mtx clocks
    after the take (page_mt_end=exec), against the old value on its deciding runs; the losing
    alternatives (page_mt_end=take, page_mem_from=post, page_disp=hold) stay at their defaults."""

    def _exact(self, cid, **over):
        sil, mod = _ev118(cid, **over)
# (WP119, F39/F40/F37/F25/F30, 2026-11-01) the non-0F remainder of F39 and F40 re-read under the
# fifty-ninth fit: TEST r,r's ModR/M byte counts as gone only on a word's delivery clock
# (pre_modrm=arrival); LDEA started on a fetch's issue clock writes its result back to lea.fwb
# clocks after that fetch's last clock, which the port OUT waits out (lea_wb=fetch); an
# unprefixed INM's I/O read counts its setup as a memory data request, its last str_in.ufree
# clocks fetch-free (str_in_io=free); a memory-indirect transfer started on a word's delivery
# clock keeps the empty IR as the request rule's seventh slot while two or more operand bytes
# are to take (xfer_mem_room=arrival), and its split displacement (first byte the odd half of a
# word) is taken without waiting for the delivery of a fetch on the bus (late_disp_word=split)
WP119 = {"pre_modrm": "arrival", "lea_wb": "fetch", "str_in_io": "free",
         "xfer_mem_room": "arrival", "late_disp_word": "split", "lea.fwb": 5, "str_in.ufree": 6}
# the pre-WP119 values, pinned for the "old" traces so they hold after an adoption, with the
# tracked values these forms read
_OLD119 = {"pre_modrm": "start", "lea_wb": "none", "str_in_io": "nowait",
           "xfer_mem_room": "hold", "late_disp_word": "any",
           "room_ir_pre": "modrm", "room_ir": "arrival_idle", "word_latch": "byte_d",
           "latch_midtake": True, "lea_io": "recover", "lea_room": "ir", "lea_slot": "ea",
           "lea_disp": "run", "wb_from": "end", "out.wbsync": 1, "str_count": "dw",
           "io_count": "nowait", "str_single_start": "write", "str_single_wb": "index",
           "xfer_mem_ir": "hold", "xfer_mem_disp": "grp", "xfer_mem_head": "lead",
           "ea_ir_room": True, "late_disp": "all", "sync_req": "disp", "str_in.setup": 9,
           "call_mem.grp": 6, "call_mem.dhold": 3, "br_mem.grp": 6, "br_mem.dhold": 3}
_NEW119 = ("pre_modrm", "lea_wb", "str_in_io", "xfer_mem_room", "late_disp_word")
_KEEP119 = {k: v for k, v in _OLD119.items() if k not in _NEW119}


def _ev119(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit, the values WP119's
    forms read pinned (_KEEP119) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**_KEEP119, **over}),
                            s.chain_base)
    return aligned(s), aligned(m)


class RemainderWP119(unittest.TestCase):
    """(WP119) the second instances and successors of F39 and F40 outside the 0F page: each new
    value against its old one on its deciding run, the controls exact under both."""

    def _exact(self, cid, **over):
        sil, mod = _ev119(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(OPTIONS["page_mt_end"], ("none", "exec", "take"))
        self.assertEqual(OPTIONS["page_mem_from"], ("start", "post"))
        self.assertEqual(OPTIONS["page_disp"], ("go", "hold"))
        for name in ("page_mt_end", "page_mem_from", "page_disp"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        self.assertEqual(DEFAULT.cost["bit1"]["mtx"], 1)

    def test_page_mt_end_deciding_run(self):
        # the second SET1 AW,CL starts 96 on F96's issue, its ModR/M taken at 101: silicon the
        # OUT's port fetch F110, I/O 118 (none: the bit op's write-back ends 106, F109 O117)
        cid = "F32-out-set1_rw_cl-k2-pE-w1"
        mod = self._exact(cid, **WP118)
        self.assertIn((110, "fetch"), _at114(mod))
        self.assertIn((118, "io_write"), _at114(mod))
        _, old = _ev118(cid, **_OLD118)
        self.assertIn((109, "fetch"), _at114(old))
        self.assertIn((117, "io_write"), _at114(old))
        self.assertNotIn((110, "fetch"), _at114(old))

    def test_push_and_set1_successors(self):
        # PUSH after SET1 at w1: silicon W133 (none: W132); SET1 after SET1 at w1: F105
        # (none: F104); at w0 the loader's IR load binds and both values are exact
        cid = "F39-push-xfer-be-set1-pE-w1"
        mod = self._exact(cid, **WP118)
        self.assertIn((133, "stack_write"), _at114(mod))
        _, old = _ev118(cid, **_OLD118)
        self.assertIn((132, "stack_write"), _at114(old))
        cid = "F40-out-page-set1-k4-pE-w1"
        mod = self._exact(cid, **WP118)
        self.assertIn((105, "fetch"), _at114(mod))
        _, old = _ev118(cid, **_OLD118)
        self.assertIn((104, "fetch"), _at114(old))
        for c in ("F39-push-xfer-be-set1-pE-w0", "F40-out-page-set1-k4-pE-w0"):
            self._exact(c, **WP118)
            self._exact(c, **_OLD118)

    def test_take_sync_and_bit_fields_hide_it(self):
        # behind MOV AW,1234h the take sync after the ModR/M take outlasts the clock; EXT's and
        # INS's reads do not wait for the ModR/M byte: exact under both values, and with mtx set
        # for the bit field classes too
        for c in ("F34-out-rbit-set1_rw_cl-d-k1-pE-w0", "F34-out-rbit-set1_rw_cl-d-k1-pE-w2",
                  "F34-out-bf-ext_bl_dh-nop2-k1-pO-w1", "F34-out-bf-ins_bl_i7-nop2-k1-pO-w2"):
            self._exact(c, **WP118)
            self._exact(c, **_OLD118)
            self._exact(c, **WP118, **{"bf_ext.mtx": 1, "bf_ins.mtx": 1})

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP118's values
        base = {**_KEEP114, **WP114, **_KEEP116, **WP116, **_KEEP118}
        for fam in ("F3", "F14", "F33", "F36"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(**{**base, **WP118}),
                                          s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**{**base, **_OLD118}),
                                          s.chain_base)
        for name in _NEW119:
            self.assertEqual(OPTIONS[name][0], _OLD119[name], name)
            self.assertEqual(getattr(DEFAULT, name), _OLD119[name], name)

    def test_pre_modrm_deciding_run(self):
        # the third TEST DL,AL (odd) starts 95, the clock after the second's ModR/M take on F91's
        # delivery (its second byte latched), 6 bytes queued: silicon F98 F101 O119 (start: the
        # fetch on the start clock, F95 F99 O117)
        cid = "F40-out-reg-testdl-k4-pO-w0"
        mod = self._exact(cid, **WP119)
        self.assertIn((98, "fetch"), _at114(mod))
        self.assertIn((119, "io_write"), _at114(mod))
        _, old = _ev119(cid, **_OLD119)
        self.assertIn((95, "fetch"), _at114(old))
        self.assertIn((117, "io_write"), _at114(old))
        # started on the delivery clock itself the second instance still fetches there (F91),
        # and WP114's INC AL control
        for c in ("F40-out-reg-testdl-k2-pO-w0", "F33-out-inc_al-k2-pO-w0"):
            self._exact(c, **WP119)
            self._exact(c, **_OLD119)

    def test_lea_wb_deciding_run(self):
        # LDEA AW,[BW] (odd) starts 112 on F112's issue after MOVBK; silicon's OUT: F128 and the
        # I/O at 132, the OUT starting 5 clocks after F112's last clock (none: F126 O130)
        cid = "F39-out-str-movbk-ldea-pE-w1"
        mod = self._exact(cid, **WP119)
        self.assertIn((128, "fetch"), _at114(mod))
        self.assertIn((132, "io_write"), _at114(mod))
        _, old = _ev119(cid, **_OLD119)
        self.assertIn((126, "fetch"), _at114(old))
        self.assertIn((130, "io_write"), _at114(old))
        # the PUSH after the same start and the NOP-led LDEA (its OUT behind the back-to-back
        # fetch) exact under both
        for c in ("F39-push-str-movbk-ldea-pO-w1", "F30-out-lea-bw-nopb-pE-w1"):
            self._exact(c, **WP119)
            self._exact(c, **_OLD119)

    def test_str_in_io_deciding_run(self):
        # INM (odd) under PUSH starts 82 on F82's issue (one wait state): silicon I91, 6 clocks
        # after the fetch's last clock (nowait: I92); MOVBK in the same cell reads at 92
        cid = "F39-push-str-inm-ld-pE-w1"
        mod = self._exact(cid, **WP119)
        self.assertIn((91, "io_read"), _at114(mod))
        _, old = _ev119(cid, **_OLD119)
        self.assertIn((92, "io_read"), _at114(old))
        for c in ("F39-push-str-movbk-ld-pE-w1", "F39-push-str-inm-ld-pO-w1",
                  "F39-push-str-inm-ld-pE-w0"):
            self._exact(c, **WP119)
            self._exact(c, **_OLD119)

    def test_xfer_mem_room_deciding_runs(self):
        # the second CALL [0C00h] (odd) starts 187 on F184's delivery with the word's second
        # byte latched: silicon F187 D195 (hold: F192); the fetch alone (late_disp_word=any)
        # puts the pointer read a clock late (D196)
        cid = "F40-out-ind-callm-k2-pE-w0"
        mod = self._exact(cid, **WP119)
        self.assertIn((187, "fetch"), _at114(mod))
        self.assertIn((195, "data_read"), _at114(mod))
        _, old = _ev119(cid, **_OLD119)
        self.assertIn((192, "fetch"), _at114(old))
        _, half = _ev119(cid, **{**WP119, "late_disp_word": "any"})
        self.assertIn((196, "data_read"), _at114(half))
        # F37's BR [0C00h] behind a NOP: silicon F109 D118 (hold: F114)
        cid = "F37-out-indm-brm-sep-pE-w1"
        mod = self._exact(cid, **WP119)
        self.assertIn((109, "fetch"), _at114(mod))
        self.assertIn((118, "data_read"), _at114(mod))
        _, old = _ev119(cid, **_OLD119)
        self.assertIn((114, "fetch"), _at114(old))
        # the even form (its whole-word displacement waits for the fetch's delivery) and the
        # first instances exact under both
        for c in ("F37-out-indm-callm-n0-pE-w1", "F37-out-indm-callm-n0-pO-w1",
                  "F40-out-ind-callm-k2-pO-w1"):
            self._exact(c, **WP119)
            self._exact(c, **_OLD119)

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP119's values
        for fam in ("F3", "F14", "F21", "F36"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**_KEEP119, **WP119}), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**_KEEP119, **_OLD119}), s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)


# (WP122, F32/F34/F39/F40) the 0F register forms' remaining shapes under the sixtieth fit
# (scratchpad wp122/facts.txt). A: a register bit op whose bit index immediate is the even half of
# its word (an odd address) takes the take sync its ModR/M take set and runs its first ALU clock on
# the immediate's take clock (page_imm_sync=lead). B: a register bit op started with six bytes
# stored, a byte latched and no fetch in flight does not count the empty IR as room until its
# steps end (page_ir_room=end). C: TEST1 [m] takes its ModR/M byte a clock after the second opcode
# byte (bit1_test.pre 1), a fetch committed before its read's post counts toward the setup
# (page_commit=post), and in WP116's waited-take state its ModR/M take waits for the start fetch's
# word and its EA clocks for the byte's late arrival (page_mtest=wait, bit1_test.mtx 1)
WP122_A = {"page_imm_sync": "lead"}
WP122_B = {"page_ir_room": "end"}
WP122_C = {"page_mtest": "wait", "bit1_test.mtx": 1, "bit1_test.pre": 1, "page_commit": "post"}
WP122 = {**WP122_A, **WP122_B, **WP122_C}
# the pre-WP122 values, pinned for the "old" traces so they hold after an adoption, with the
# sixtieth fit's values these forms read
_OLD122 = {"page_imm_sync": "take", "page_ir_room": "ir", "page_mtest": "none",
           "bit1_test.mtx": 0, "bit1_test.pre": 4, "page_commit": "start",
           "page_mt_end": "exec", "page_mtake": "eu", "page_start": "reg", "test1_head": "own",
           "bit1.mtx": 1, "bit1.nx": 4, "bit1.pre": 1, "bit1.exec": 2, "bit1.wb": 2,
           "bit1.cl": 0, "bit1_test.nx": 0, "bit1_test.cl": 3, "bit1_test.fsetup": 3,
           "bit1_test.exec": 2, "out.wbsync": 1, "out.pre": 3}
_KEEP122 = {k: v for k, v in _OLD122.items() if k not in WP122}


def _ev122(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with the earlier
    candidates' values pinned as WP118's tests pin them, the values WP122's forms read pinned
    (_KEEP122) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(
        **{**_KEEP114, **WP114, **_KEEP116, **WP116, **_KEEP118, **WP118, **_KEEP122, **over}),
        s.chain_base)
    return aligned(s), aligned(m)


class PageFormsWP122(unittest.TestCase):
    """(WP122) the three prototypes against their old values on their deciding runs; page_mtest=all
    (a within-class trade) stays at its default."""

    def _exact(self, cid, **over):
        sil, mod = _ev122(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def _miss(self, cid, **over):
        sil, mod = _ev122(cid, **over)
        self.assertNotEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(OPTIONS["page_imm_sync"], ("take", "modrm", "lead"))
        self.assertEqual(OPTIONS["page_ir_room"], ("ir", "end"))
        self.assertEqual(OPTIONS["page_mtest"], ("none", "wait", "all"))
        for name in ("page_imm_sync", "page_ir_room", "page_mtest"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        for cls in ("bit1_test", "bit1_rmw", "bit1_clr"):
            self.assertEqual(DEFAULT.cost[cls]["mtx"], 0, cls)

    def test_page_imm_sync_deciding_run(self):
        # the second SET1 AW,0Fh (an odd address) starts 97 on F97's issue, the ModR/M taken at
        # 102, the immediate at 103 with F103 issued there: silicon F115 O119 (take: the take sync
        # waits out F103, F119 O123; modrm: F116 O120)
        cid = "F32-out-set1_rw_imm-k2-pO-w1"
        mod = self._exact(cid, **WP122_A)
        self.assertIn((115, "fetch"), _at114(mod))
        self.assertIn((119, "io_write"), _at114(mod))
        _, old = _ev122(cid, **_OLD122)
        self.assertIn((119, "fetch"), _at114(old))
        self.assertIn((123, "io_write"), _at114(old))
        _, mid = _ev122(cid, page_imm_sync="modrm")
        self.assertIn((116, "fetch"), _at114(mid))
        self.assertIn((120, "io_write"), _at114(mid))
        # the same form behind SHL AL,imm8 on an idle bus: exact under modrm and lead only
        cid = "F34-out-rbit-set1_rw_imm-sep-k1-pE-w1"
        self._exact(cid, **WP122_A)
        self._exact(cid, page_imm_sync="modrm")
        self._miss(cid, **_OLD122)
        # the even-address form (the immediate the odd half of its word) keeps the old sync
        for c in ("F32-out-set1_rw_imm-k2-pE-w1", "F32-out-set1_rw_imm-k2-pE-w0"):
            self._exact(c, **WP122_A)
            self._exact(c, **_OLD122)

    def test_page_ir_room_deciding_run(self):
        # the second SET1 AW,CL (an even address) starts 97 on an idle bus, six bytes stored and
        # one latched: silicon F102 F114 O118 (ir: F99 on the ModR/M take's IR room, F115 O119)
        cid = "F32-out-set1_rw_cl-k2-pO-w1"
        mod = self._exact(cid, **WP122_B)
        self.assertIn((102, "fetch"), _at114(mod))
        self.assertIn((118, "io_write"), _at114(mod))
        _, old = _ev122(cid, **_OLD122)
        self.assertIn((99, "fetch"), _at114(old))
        self.assertIn((119, "io_write"), _at114(old))
        # a PUSH successor at w0: silicon F95 W104 (ir: F92 W103)
        cid = "F40-push-page-set1-k2-pE-w0"
        mod = self._exact(cid, **WP122_B)
        self.assertIn((104, "stack_write"), _at114(mod))
        _, old = _ev122(cid, **_OLD122)
        self.assertIn((103, "stack_write"), _at114(old))
        # the OUT successor at w0 stays a fact: the fetch right, the OUT a clock early
        # (silicon F99 F111 O114)
        cid = "F32-out-set1_rw_cl-k2-pO-w0"
        sil, mod = _ev122(cid, **WP122_B)
        self.assertIn((99, "fetch"), _at114(mod))
        self.assertIn((113, "io_write"), _at114(mod))
        self.assertIn((114, "io_write"), _at114(sil))

    def test_page_mtest_deciding_run(self):
        # the second TEST1 [BW],0Fh (an odd address) starts 103 on F103's issue: silicon D112,
        # F103's last clock + 6 (none, with pre 1 and post: D109; the old values: D111)
        cid = "F32-out-test1_mw_imm-k2-pO-w1"
        mod = self._exact(cid, **WP122_C)
        self.assertIn((112, "data_read"), _at114(mod))
        _, none = _ev122(cid, **{**WP122_C, "page_mtest": "none"})
        self.assertIn((109, "data_read"), _at114(none))
        _, old = _ev122(cid, **_OLD122)
        self.assertIn((111, "data_read"), _at114(old))
        # w0, exact under the old values by the wait count, stays exact
        self._exact("F32-out-test1_mw_imm-k2-pO-w0", **WP122_C)
        self._exact("F32-out-test1_mw_imm-k2-pO-w0", **_OLD122)

    def test_test1_head_and_commit(self):
        # TEST1 [BW],CL at an even address on F81's issue: silicon F84 back to back, D92 (pre 4:
        # the ModR/M at 86, F86 D94)
        cid = "F32-push-test1_mw_cl-k1-pO-w0"
        mod = self._exact(cid, **WP122_C)
        self.assertIn((84, "fetch"), _at114(mod))
        self.assertIn((92, "data_read"), _at114(mod))
        _, old = _ev122(cid, **_OLD122)
        self.assertIn((86, "fetch"), _at114(old))
        self.assertIn((94, "data_read"), _at114(old))
        # DS1: TEST1 [BW],CL: F90 committed on F87's last clock, before the read's post; silicon
        # D98 (pre 1 with page_commit=start: D95)
        cid = "F32-out-pfx_test1_mw_cl-k1-pE-w0"
        self._exact(cid, **WP122_C)
        self._exact(cid, **_OLD122)
        _, start = _ev122(cid, **{**WP122_C, "page_commit": "start"})
        self.assertIn((95, "data_read"), _at114(start))

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP122's values
        base = {**_KEEP114, **WP114, **_KEEP116, **WP116, **_KEEP118, **WP118, **_KEEP122}
        for fam in ("F3", "F14", "F33", "F36"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(**{**base, **WP122}),
                                          s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**{**base, **_OLD122}),
                                          s.chain_base)
# (WP124) the small refresh-off remainders re-read under the sixty-first fit: a base+index+d16
# displacement taken while an I/O request waits in the slot holds that I/O a clock longer
# (disp_io_wait=bix); a held CVTBD / CVTDB releases its hold counted from its start and writes
# back hx clocks longer (cvt_from=start, cvt_tail=release, convert_d.hrel 2, convert.hx 1,
# convert_d.hx 2); a memory multiply or divide started on an aborted cycle ends with its early
# read's exec (abort_unit_end=early); an unprefixed OUTM's read counts as a memory request's
# (str_out_rd=free, str_out.ufree 7, str_out.usetup 11); a group RMW form's d16 taken on a
# word's delivery clock with the second byte latched posts its read a clock later
# (gdisp_dlv=late)
WP124 = {"disp_io_wait": "bix", "cvt_tail": "release", "cvt_from": "start",
         "convert_d.hrel": 2, "convert.hx": 1, "convert_d.hx": 2,
         "abort_unit_end": "early", "str_out_rd": "free", "str_out.ufree": 7,
         "str_out.usetup": 11, "gdisp_dlv": "late"}
# the pre-WP124 values, pinned for the "old" traces so they hold after an adoption, with the
# tracked values these forms read
_OLD124 = {"disp_io_wait": "none", "cvt_tail": "none", "cvt_from": "take",
           "abort_unit_end": "keep", "str_out_rd": "nowait", "gdisp_dlv": "none",
           "convert.hrel": 1, "convert_d.hrel": 3, "convert.exec": 16, "convert_d.exec": 16,
           "convert.wb": 2, "convert_d.wb": 0, "cvt_hold": "word", "disp_io": "extend",
           "grp_disp": "hold", "grp_io_hold": True, "abort_unit": "loop", "mul_data": "sign",
           "str_count": "dw", "io_count": "nowait", "str_single_start": "write",
           "str_single_wb": "index", "str_out.setup": 10, "wb_from": "end", "out.wbsync": 1}
_NEW124 = ("disp_io_wait", "cvt_tail", "cvt_from", "abort_unit_end", "str_out_rd", "gdisp_dlv")
_KEEP124 = {k: v for k, v in _OLD124.items() if k not in _NEW124 and k != "convert_d.hrel"}


def _ev124(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit, the values WP124's
    forms read pinned (_KEEP124) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(**{**_KEEP124, **over}),
                            s.chain_base)
    return aligned(s), aligned(m)


class RemaindersWP124(unittest.TestCase):
    """(WP124) F22, F24, F25, F29, F30 and F33's small refresh-off remainders: each new value
    against its old one on its deciding run, the controls exact under both."""

    def _exact(self, cid, **over):
        sil, mod = _ev124(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(OPTIONS["disp_io_wait"], ("none", "bix"))
        self.assertEqual(OPTIONS["grp_io_lift"], ("end", "count"))
        self.assertEqual(OPTIONS["grp_io_any"], ("free", "any"))
        self.assertEqual(OPTIONS["cvt_tail"], ("none", "release"))
        self.assertEqual(OPTIONS["cvt_from"], ("take", "start"))
        self.assertEqual(OPTIONS["abort_unit_end"], ("keep", "early"))
        self.assertEqual(OPTIONS["str_out_rd"], ("nowait", "free"))
        self.assertEqual(OPTIONS["gdisp_dlv"], ("none", "late"))
        for name in _NEW124 + ("grp_io_lift", "grp_io_any"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
            self.assertEqual(getattr(Config.fitted(), name), OPTIONS[name][0], name)
        self.assertEqual(DEFAULT.cost["convert"]["hx"], 1)
        self.assertEqual(DEFAULT.cost["convert_d"]["hx"], 2)
        self.assertEqual(DEFAULT.cost["str_out"]["ufree"], 7)
        self.assertEqual(DEFAULT.cost["str_out"]["usetup"], 11)

    def test_disp_io_wait_deciding_run(self):
        # MOV [BW+IX+200h],AL starts 82 behind OUT DW,AL, its d16 taken at 86 with the DW I/O
        # waiting in the slot (issued 92): silicon F96 W99 (none: F95 W98)
        cid = "F29-out-ec-dio-dw-stbixd16-n0-pE-w0"
        mod = self._exact(cid, **WP124)
        self.assertIn((96, "fetch"), _at114(mod))
        self.assertIn((99, "data_write"), _at114(mod))
        _, old = _ev124(cid, **_OLD124)
        self.assertIn((95, "fetch"), _at114(old))
        self.assertIn((98, "data_write"), _at114(old))
        # the load in the same state at pO, one wait: silicon F97 (none: F96)
        self._exact("F29-out-ec-dio-dw-ldbixd16-n0-pO-w1", **WP124)
        # the [BW+200h] twin takes its d16 in the same state and fetches at 95; the
        # base+index+d8 form behind the OUT marker takes its d8 with the marker's I/O waiting,
        # and the d16 form there takes its on the I/O's issue clock (disp_io): exact under both
        for c in ("F29-out-ec-dio-dw-stbwd16-n0-pE-w0", "F21-out-l0-ld-bw_ix_d8-pE-w0",
                  "F21-out-l0-ld-bw_ix_d16-pE-w1"):
            self._exact(c, **WP124)
            self._exact(c, **_OLD124)

    def test_cvt_tail_and_from_deciding_runs(self):
        # CVTBD (odd) starts 85 on M0's I/O issue, released 104: silicon F116 O119, the OUT
        # waiting out the write-back (none: F115 O118)
        cid = "F33-out-cvtbd-k1-pO-w0"
        mod = self._exact(cid, **WP124)
        self.assertIn((116, "fetch"), _at114(mod))
        self.assertIn((119, "io_write"), _at114(mod))
        _, old = _ev124(cid, **_OLD124)
        self.assertIn((115, "fetch"), _at114(old))
        self.assertIn((118, "io_write"), _at114(old))
        # the second CVTDB starts 107 on an idle bus and takes its 0A at 109: silicon F124
        # (take: the release counted from that take, F123)
        cid = "F33-out-cvtdb-k2-pO-w1"
        mod = self._exact(cid, **WP124)
        self.assertIn((124, "fetch"), _at114(mod))
        _, old = _ev124(cid, **_OLD124)
        self.assertIn((123, "fetch"), _at114(old))
        # the PUSH twin takes its byte on a delivery clock (no hold armed) and the w1 / w2 OUT
        # cells end on the fetch: exact under both
        for c in ("F33-push-cvtbd-k1-pE-w0", "F33-out-cvtbd-k1-pO-w1", "F33-out-cvtdb-k1-pO-w2",
                  "F33-out-cvtbd-k1-pE-w0"):
            self._exact(c, **WP124)
            self._exact(c, **_OLD124)

    def test_abort_unit_end_deciding_run(self):
        # the second MUL [BW] starts 157 on an aborted cycle and reads at 164: silicon F224
        # O227 (keep: F225 O228); the pE twin starts on a fetch's issue: exact under both
        cid = "F33-out-mul_m-ld-k2-pO-w0"
        mod = self._exact(cid, **WP124)
        self.assertIn((224, "fetch"), _at114(mod))
        self.assertIn((227, "io_write"), _at114(mod))
        _, old = _ev124(cid, **_OLD124)
        self.assertIn((225, "fetch"), _at114(old))
        self.assertIn((228, "io_write"), _at114(old))
        for c in ("F33-out-mul_m-ld-k2-pE-w0", "F33-out-divu_m-ld-k2-pO-w2"):
            self._exact(c, **WP124)
            self._exact(c, **_OLD124)

    def test_str_out_rd_deciding_runs(self):
        # the second OUTM starts 107 on an idle bus: silicon D117 (nowait: D116); started on
        # F108's issue at one wait: silicon D118 (nowait: D119)
        for cid, new, old_t in (("F24-out-s-outm-w-k2-pO-w0", 117, 116),
                                ("F24-out-s-outm-w-k2-pE-w1", 118, 119)):
            mod = self._exact(cid, **WP124)
            self.assertIn((new, "data_read"), _at114(mod))
            _, old = _ev124(cid, **_OLD124)
            self.assertIn((old_t, "data_read"), _at114(old))
        for c in ("F24-out-s-outm-w-k1-pO-w0", "F24-out-s-outm-w-k2-pE-w0",
                  "F24-out-s-outm-b-k1-pE-w2"):
            self._exact(c, **WP124)
            self._exact(c, **_OLD124)

    def test_gdisp_dlv_deciding_run(self):
        # INC [BW+200h] starts 94 on F94's issue, its d16 taken on the delivery 98 with the
        # word's second byte latched: silicon D103 (none: D102); the pE twin fetches between
        # the take and the read, the ALU RMW form fetches on its take clock: exact under both
        cid = "F29-out-ec-gih-incd16-n2-pO-w1"
        mod = self._exact(cid, **WP124)
        self.assertIn((103, "data_read"), _at114(mod))
        _, old = _ev124(cid, **_OLD124)
        self.assertIn((102, "data_read"), _at114(old))
        for c in ("F29-out-ec-gih-incd16-n2-pE-w1", "F21-out-n2-add-bw_d16-pO-w1"):
            self._exact(c, **WP124)
            self._exact(c, **_OLD124)

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP124's values
        for fam in ("F3", "F14", "F21", "F36"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**_KEEP124, **WP124}), s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(
                    **{**_KEEP124, **_OLD124}), s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)


# (WP125, F34) the 0F memory forms behind NOP NOP and their displacement cells under the
# sixty-second fit (scratchpad wp125/facts.txt). A: page_mtake's waited ModR/M take holds every 0F
# memory form unless the word delivered on its start clock came from a fetch the bus unit committed
# back to back (the commitment held to that word's delivery), and the read's setup counts back no
# further than the clock the EA clocks may start (page_mwait=commit, bit1_rmw.mtx = bit1_clr.mtx
# 1). B: no back-to-back commitment on the last clock of the fetch inside whose flight a 0F memory
# form with a CL index took its two-byte displacement; the request is the take's, held for the
# read's fetch-free clocks (page_dcommit=hold). C / D: a register bit op started in
# page_ir_room=end's state (six stored, a byte latched, nothing in flight) writes back bit1.flwb
# clocks later (page_fl_end=wb) and evaluates the request on the clock after each operand take
# (page_fl_eval=next)
WP125_A = {"page_mwait": "commit", "bit1_rmw.mtx": 1, "bit1_clr.mtx": 1}
WP125_B = {"page_dcommit": "hold"}
WP125_C = {"page_fl_end": "wb", "bit1.flwb": 2}
WP125_D = {"page_fl_eval": "next"}
WP125 = {**WP125_A, **WP125_B, **WP125_C, **WP125_D}
# the pre-WP125 values, pinned for the "old" traces so they hold after an adoption, with the
# sixty-second fit's values these forms read
_OLD125 = {"page_mwait": "none", "page_dcommit": "go", "bit1_rmw.mtx": 0, "bit1_clr.mtx": 0,
           "page_mtake": "eu", "page_mt_end": "exec", "page_mtest": "wait", "page_start": "reg",
           "page_cl": "thru", "page_run": "field", "page_commit": "post", "page_mem": "fixed",
           "page_b2b": "reg", "page_b2b_win": "run", "page_ir": "delivery", "page_disp": "go",
           "page_mem_from": "start", "late_read": True, "bit1_test.mtx": 1, "bit1_test.pre": 1,
           "bit1_rmw.pre": 1, "bit1_clr.pre": 1, "bit1_rmw.fsetup": 3, "bit1_clr.fsetup": 3,
           "bit1_test.fsetup": 3, "bit1_rmw.cl": 3, "bit1_clr.cl": 3, "bit1_test.cl": 3,
           "page_fl_end": "none", "page_fl_eval": "take", "page_ir_room": "end",
           "page_imm_sync": "lead", "request_eval": "on_change", "bit1.wb": 2, "bit1.exec": 2,
           "bit1.pre": 1, "bit1.nx": 4, "bit1.mtx": 1, "out.wbsync": 1, "out.pre": 3}
_KEEP125 = {k: v for k, v in _OLD125.items() if k not in WP125}


def _ev125(cid, **over):
    """(silicon, model) aligned event lists from t_fill under the tracked fit with the earlier
    candidates' values pinned as WP122's tests pin them, WP122's values (the sixty-second fit), the
    values WP125's forms read pinned (_KEEP125) and over."""
    fam = cid.split("-", 1)[0]
    run = next(r for r in _runs(fam) if r["chain"]["id"] == cid)
    s = normalize(run)
    m = simulate_normalized(s.chain, Config.fitted().replace(
        **{**_KEEP114, **WP114, **_KEEP116, **WP116, **_KEEP118, **WP118, **_KEEP122, **WP122,
           **_KEEP125, **over}), s.chain_base)
    return aligned(s), aligned(m)


class PageMemWP125(unittest.TestCase):
    """(WP125) the four prototypes against their old values on their deciding runs;
    page_mwait=all (no commitment test) loses the MOV AW,1234h cells and stays out."""

    def _exact(self, cid, **over):
        sil, mod = _ev125(cid, **over)
        self.assertEqual(mod, sil, cid)
        return mod

    def _miss(self, cid, **over):
        sil, mod = _ev125(cid, **over)
        self.assertNotEqual(mod, sil, cid)
        return mod

    def test_defaults_are_the_old_behaviour(self):
        self.assertEqual(OPTIONS["page_mwait"], ("none", "commit", "all"))
        self.assertEqual(OPTIONS["page_dcommit"], ("go", "hold"))
        self.assertEqual(OPTIONS["page_fl_end"], ("none", "wb"))
        self.assertEqual(OPTIONS["page_fl_eval"], ("take", "next"))
        for name in ("page_mwait", "page_dcommit", "page_fl_end", "page_fl_eval"):
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        self.assertEqual(DEFAULT.cost["bit1"]["flwb"], 2)

    def test_page_mwait_deciding_run(self):
        # SET1 [IX],CL behind NOP NOP starts 94 on F94's issue (F90's word, not committed,
        # delivered there): silicon D106 (none: the ModR/M on F94's delivery 98, 98-100 counted
        # back, D103; commit: the ModR/M at 99, the EA clocks 101-102, D106)
        cid = "F34-out-mbit-set1_mw_cl-nop2-k1-pO-w1"
        mod = self._exact(cid, **WP125_A)
        self.assertIn((106, "data_read"), _at114(mod))
        _, old = _ev125(cid, **_OLD125)
        self.assertIn((103, "data_read"), _at114(old))
        # the immediate form in the same state at w2: silicon D106 (none: D103)
        cid = "F34-out-mbit-set1_mw_imm-nop2-k1-pO-w2"
        mod = self._exact(cid, **WP125_A)
        self.assertIn((106, "data_read"), _at114(mod))
        _, old = _ev125(cid, **_OLD125)
        self.assertIn((103, "data_read"), _at114(old))
        # TEST1 [m],CL behind the PUSH frame's NOP: missing under the old values
        self._exact("F34-push-mbit-test1_mw_cl-nop-k1-pO-w2", **WP125_A)
        self._miss("F34-push-mbit-test1_mw_cl-nop-k1-pO-w2", **_OLD125)

    def test_page_mwait_commitment(self):
        # behind MOV AW,1234h the start clock is F93's delivery, the word of a fetch committed back
        # to back on F89's last clock: no wait, D106 under none and commit; all waits (D109)
        cid = "F34-out-mbit-set1_mw_cl-d-k1-pE-w1"
        self._exact(cid, **WP125_A)
        self._exact(cid, **_OLD125)
        _, all_ = _ev125(cid, **{**WP125_A, "page_mwait": "all"})
        self.assertNotIn((106, "data_read"), _at114(all_))
        for c in ("F34-out-mbit-set1_mw_imm-d-k1-pE-w0", "F34-out-mbit-clr1_mw_cl-d-k1-pE-w2"):
            self._exact(c, **WP125_A)
            self._miss(c, **{**WP125_A, "page_mwait": "all"})
        # TEST1 [m],imm's second instance at k = 2 pO, WP122's waited state, stays exact
        for c in ("F32-out-test1_mw_imm-k2-pO-w0", "F32-out-test1_mw_imm-k2-pO-w1"):
            self._exact(c, **WP125_A)
            self._exact(c, **_OLD125)

    def test_page_dcommit_deciding_run(self):
        # SET1 [BW+d16],CL behind a NOP starts 89 on F89's issue, the d16 taken at 96 on F93's
        # last clock: silicon F100 D104 (go: F97 committed back to back, D103)
        cid = "F34-out-mbit-set1_mw_cl_bw_d16-nop-k1-pE-w1"
        mod = self._exact(cid, **WP125_B)
        self.assertIn((100, "fetch"), _at114(mod))
        self.assertIn((104, "data_read"), _at114(mod))
        _, old = _ev125(cid, **_OLD125)
        self.assertIn((97, "fetch"), _at114(old))
        self.assertIn((103, "data_read"), _at114(old))
        # the w0 twin takes the d16 on F93's delivery, and the pO cell's commitment goes to the
        # marker OUT's I/O: exact under both
        for c in ("F34-out-mbit-set1_mw_cl_bw_d16-nop-k1-pE-w0",
                  "F34-out-mbit-set1_mw_cl_bw_d16-l0-k1-pO-w1"):
            self._exact(c, **WP125_B)
            self._exact(c, **_OLD125)

    def test_page_fl_end_deciding_run(self):
        # the second SET1 AW,CL (an even address) starts 94 on an idle bus, six bytes stored and
        # one latched, its steps end 99 with F99 issued there: silicon F111 O114 (none: the OUT
        # starts 102 behind F99, F110 O113; wb: its wbsync to 103, F111 O114)
        cid = "F32-out-set1_rw_cl-k2-pO-w0"
        mod = self._exact(cid, **WP125_C)
        self.assertIn((99, "fetch"), _at114(mod))
        self.assertIn((111, "fetch"), _at114(mod))
        self.assertIn((114, "io_write"), _at114(mod))
        _, old = _ev125(cid, **_OLD125)
        self.assertIn((110, "fetch"), _at114(old))
        self.assertIn((113, "io_write"), _at114(old))
        # w1: the fetch's flight holds the OUT to the same clock under both; the PUSH successor
        # (no wbsync) is exact under both
        for c in ("F32-out-set1_rw_cl-k2-pO-w1", "F40-push-page-set1-k2-pE-w0"):
            self._exact(c, **WP125_C)
            self._exact(c, **_OLD125)

    def test_page_fl_eval_deciding_run(self):
        # the second SET1 AW,0Fh (an even address) starts 102 in the same state, the immediate
        # taken at 105: silicon F106 F110 O121 (take: F105 on the take's room, the ALU clocks
        # wait for its word, F109 O123)
        cid = "F34-out-rbit-set1_rw_imm-nop-k2-pO-w1"
        mod = self._exact(cid, **WP125_D)
        self.assertIn((106, "fetch"), _at114(mod))
        self.assertIn((121, "io_write"), _at114(mod))
        _, old = _ev125(cid, **_OLD125)
        self.assertIn((105, "fetch"), _at114(old))
        self.assertIn((123, "io_write"), _at114(old))
        # w0 stays a fact: the first fetch right (F102), page_b2b's commitment on its last clock
        # (F105) where silicon commits none (F109 O116)
        sil, mod = _ev125("F34-out-rbit-set1_rw_imm-nop-k2-pO-w0", **WP125_D)
        self.assertIn((102, "fetch"), _at114(mod))
        self.assertIn((105, "fetch"), _at114(mod))
        self.assertIn((116, "io_write"), _at114(sil))

    def test_other_families_untouched(self):
        # no sampled run of these families moves under WP125's values
        base = {**_KEEP114, **WP114, **_KEEP116, **WP116, **_KEEP118, **WP118, **_KEEP122,
                **WP122, **_KEEP125}
        for fam in ("F3", "F14", "F33", "F36"):
            for run in _runs(fam)[::60]:
                s = normalize(run)
                new = simulate_normalized(s.chain, Config.fitted().replace(**{**base, **WP125}),
                                          s.chain_base)
                old = simulate_normalized(s.chain, Config.fitted().replace(**{**base, **_OLD125}),
                                          s.chain_base)
                self.assertEqual(aligned(new), aligned(old), s.run_id)
