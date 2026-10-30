// Bus-unit bench (HDL plan, C1): feeds v35_biu the frozen model's request stream and
// checks every model clock. Vectors: validation/v35s/chains/rtl_vectors.py (one line per
// model clock, then the model's cycle list). Usage: Vv35_biu_tb VECTOR_FILE
//
// One model clock is one CPU clock: three system clocks, the second with ce_mid (the
// middle of the CPU state, where the strobes move) and the third with ce (the end of the
// model clock, where the bus unit's registers take the clock's state). Before the
// first, the inputs are the clock's request and the combinational outputs are compared
// with the model's values for that clock; after the ce, the state bundle with the state at
// the end of the clock. The pins are checked against the edge placement v35_biu.sv ports
// from v35s_model.sv: B1 of a cycle started on clock s is the CPU state after s's ce.
//
// Output: "CYC start length kind addr width data" for each cycle the RTL started,
// "DEL clock kind" for each delivery, "FAIL ..." for the first failures, and
// "SUMMARY clocks=N signal_bad=N state_bad=N pin_bad=N". Exit 0 when nothing failed.
#include "Vv35_biu_tb.h"
#include "verilated.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace {

enum Kind { K_NONE, K_FETCH, K_READ, K_WRITE, K_IO_READ, K_IO_WRITE, K_REFRESH };
enum Width { BW_WORD, BW_LO, BW_HI };

const char* const COLUMNS[] = {
    "t", "has_row",
    "start", "kind", "addr", "width", "data", "ext", "latch",
    "fill", "rfm_load", "rfm_value", "data_in",
    "busy", "free", "in_wait", "finf", "fprev", "fsince", "io_win", "wl_busy",
    "busy_x", "free_x", "in_wait_x", "finf_x", "fprev_x", "fsince_x", "io_win_x", "wl_busy_x",
    "done", "dkind", "daddr", "dwidth", "ddata",
    "valid", "skind", "pos", "len", "sext", "sint", "slatch", "saddr", "swidth", "sdata",
    "gap", "sfsince", "io_tail", "wl", "rlen",
};
constexpr int NCOL = sizeof(COLUMNS) / sizeof(COLUMNS[0]);

struct Row {
    long v[NCOL];
    long operator[](const char* name) const {
        for (int i = 0; i < NCOL; ++i)
            if (std::string(COLUMNS[i]) == name)
                return v[i];
        std::fprintf(stderr, "no column %s\n", name);
        std::exit(2);
    }
};

struct Cyc {
    long start, end, kind, addr, width, data, internal;
};

struct Bench {
    VerilatedContext context;
    Vv35_biu_tb dut{&context};
    long signal_bad = 0, state_bad = 0, pin_bad = 0, fails = 0;

    void tick(bool ce, bool mid) {
        dut.ce = ce;
        dut.ce_mid = mid;
        dut.clock = 1;
        dut.eval();
        dut.clock = 0;
        dut.eval();
        dut.ce = 0;
        dut.ce_mid = 0;
    }

    void fail(long& counter, long t, const char* what, long want, long got) {
        ++counter;
        if (++fails <= 20)
            std::printf("FAIL clock %ld %s model=%ld rtl=%ld\n", t, what, want, got);
    }
    void check(long& counter, long t, const char* what, long want, long got) {
        if (want != got)
            fail(counter, t, what, want, got);
    }
};

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s VECTOR_FILE\n", argv[0]);
        return 2;
    }
    std::ifstream in(argv[1]);
    std::string format, id, wtc_s, rfm_s;
    long nclocks = 0, ncycles = 0;
    in >> format >> id >> wtc_s >> rfm_s >> nclocks >> ncycles;
    if (format != "V35BIU-1") {
        std::fprintf(stderr, "not a V35BIU-1 vector file\n");
        return 2;
    }
    std::vector<Row> rows(nclocks);
    for (auto& r : rows)
        for (auto& x : r.v)
            in >> x;
    std::vector<Cyc> cycles;
    std::map<long, size_t> by_start;
    for (long i = 0; i < ncycles; ++i) {
        std::string tag;
        Cyc c{};
        in >> tag >> c.start >> c.end >> c.kind >> c.addr >> c.width >> c.data >> c.internal;
        if (tag != "C") {
            std::fprintf(stderr, "bad cycle line\n");
            return 2;
        }
        by_start[c.start] = cycles.size();
        cycles.push_back(c);
    }
    if (!in) {
        std::fprintf(stderr, "truncated vector file\n");
        return 2;
    }

    Verilated::commandArgs(argc, argv);
    Bench b;
    auto& d = b.dut;
    d.wtc = std::stoul(wtc_s, nullptr, 16);
    d.rfm = std::stoul(rfm_s, nullptr, 16);
    d.reset_n = 0;
    for (int i = 0; i < 4; ++i)
        b.tick(false, false);
    d.reset_n = 1;

    // the strobes after the middle of CPU state p (the state of model clock p's period)
    auto strobes = [&](long p, int& mreq, int& mstb, int& iostb, int& refrq) {
        mreq = mstb = iostb = refrq = 1;
        for (const auto& c : cycles) {
            if (c.internal || p < c.start + 1 || p > c.end)
                continue;
            if (c.kind == K_REFRESH) {
                refrq = 0;
                continue;
            }
            mreq = 0;
            if (c.kind == K_IO_READ || c.kind == K_IO_WRITE) {
                if (p >= c.start + 2)
                    iostb = 0;
            } else if (c.kind == K_WRITE) {
                if (p == c.end)
                    mstb = 0;
            } else if (p >= c.start + 2) {
                mstb = 0;
            }
        }
    };
    auto check_strobes = [&](long t, long p, const char* when) {
        int mreq, mstb, iostb, refrq;
        strobes(p, mreq, mstb, iostb, refrq);
        std::string w(when);
        b.check(b.pin_bad, t, (w + " mreq_n").c_str(), mreq, d.mreq_n);
        b.check(b.pin_bad, t, (w + " mstb_n").c_str(), mstb, d.mstb_n);
        b.check(b.pin_bad, t, (w + " iostb_n").c_str(), iostb, d.iostb_n);
        b.check(b.pin_bad, t, (w + " refrq_n").c_str(), refrq, d.refrq_n);
    };

    long refresh_row = 0;
    for (const auto& r : rows) {
        const long t = r["t"];
        const bool has_row = r["has_row"];
        d.req_start = r["start"];
        d.req_kind = r["kind"];
        d.req_addr = r["addr"];
        d.req_width = r["width"];
        d.req_data = r["data"];
        d.req_ext = r["ext"];
        d.req_latch = r["latch"];
        d.wlatch_fill = r["fill"];
        d.rfm_load = r["rfm_load"];
        d.rfm_value = r["rfm_value"];
        d.data_in = r["data_in"];
        d.eval();

        // this clock, before and after the choice
        b.check(b.signal_bad, t, "busy", r["busy"], d.busy);
        b.check(b.signal_bad, t, "free", r["free"], d.free);
        b.check(b.signal_bad, t, "in_wait", r["in_wait"], d.in_wait);
        b.check(b.signal_bad, t, "fetch_inflight", r["finf"], d.fetch_inflight);
        b.check(b.signal_bad, t, "fetch_end_prev", r["fprev"], d.fetch_end_prev);
        b.check(b.signal_bad, t, "fetch_since", r["fsince"], d.fetch_since);
        b.check(b.signal_bad, t, "io_win", r["io_win"], d.io_win);
        b.check(b.signal_bad, t, "wlatch_busy", r["wl_busy"], d.wlatch_busy);
        if (has_row) {
            b.check(b.signal_bad, t, "busy_x", r["busy_x"], d.busy_x);
            b.check(b.signal_bad, t, "free_x", r["free_x"], d.free_x);
            b.check(b.signal_bad, t, "in_wait_x", r["in_wait_x"], d.in_wait_x);
            b.check(b.signal_bad, t, "fetch_inflight_x", r["finf_x"], d.fetch_inflight_x);
            b.check(b.signal_bad, t, "fetch_end_prev_x", r["fprev_x"], d.fetch_end_prev_x);
            b.check(b.signal_bad, t, "fetch_since_x", r["fsince_x"], d.fetch_since_x);
            b.check(b.signal_bad, t, "io_win_x", r["io_win_x"], d.io_win_x);
            b.check(b.signal_bad, t, "wlatch_busy_x", r["wl_busy_x"], d.wlatch_busy_x);
        }
        if (r["start"]) {
            const auto it = by_start.find(t);
            if (it != by_start.end()) {
                const auto& c = cycles[it->second];
                b.check(b.signal_bad, t, "start_len", c.end - c.start + 1, d.start_len);
            }
        }
        b.check(b.signal_bad, t, "done", r["done"], d.done);
        if (d.done) {
            std::printf("DEL %ld %d\n", t, int(d.done_kind));
            if (r["done"]) {
                b.check(b.signal_bad, t, "done_kind", r["dkind"], d.done_kind);
                b.check(b.signal_bad, t, "done_addr", r["daddr"], d.done_addr);
                b.check(b.signal_bad, t, "done_width", r["dwidth"], d.done_width);
            }
        }

        // the middle of the CPU state: the strobes, the read data
        b.tick(false, true);
        check_strobes(t, t, "mid");
        if (r["done"] && r["ddata"] >= 0)
            b.check(b.signal_bad, t, "done_data", r["ddata"], d.done_data);

        // the end of the model clock
        b.tick(true, false);
        b.check(b.signal_bad, t, "error", 0, d.error);
        check_strobes(t, t, "ce");
        // the pins of the CPU state that starts now (t + 1)
        const auto b1 = by_start.find(t);
        const auto b2 = by_start.find(t - 1);
        if (b1 != by_start.end() && !cycles[b1->second].internal) {
            const auto& c = cycles[b1->second];
            const bool write = c.kind == K_WRITE || c.kind == K_IO_WRITE;
            b.check(b.pin_bad, t, "B1 read_write", !write, d.read_write);
            if (c.kind == K_REFRESH) {
                b.check(b.pin_bad, t, "B1 refresh row", refresh_row & 511, d.mux_address);
                ++refresh_row;
            } else {
                b.check(b.pin_bad, t, "B1 mux_address", (c.addr >> 9) & 511, d.mux_address);
                b.check(b.pin_bad, t, "B1 a0", c.addr & 1, d.a0);
                b.check(b.pin_bad, t, "B1 a19", (c.addr >> 19) & 1, d.a19);
                b.check(b.pin_bad, t, "B1 a18", (c.addr >> 18) & 1, d.a18_ube);
            }
        } else if (b2 != by_start.end() && !cycles[b2->second].internal &&
                   cycles[b2->second].kind != K_REFRESH) {
            const auto& c = cycles[b2->second];
            const bool write = c.kind == K_WRITE || c.kind == K_IO_WRITE;
            b.check(b.pin_bad, t, "B2 mux_address",
                    (((c.addr >> 9) & 1) << 8) | ((c.addr >> 1) & 255), d.mux_address);
            b.check(b.pin_bad, t, "B2 ube_n", c.width == BW_LO, d.a18_ube);
            if (write)
                b.check(b.pin_bad, t, "B2 data_out", c.data, d.data_out);
        } else if (has_row && !r["valid"]) {
            b.check(b.pin_bad, t, "idle read_write", 1, d.read_write);
        }

        if (!has_row)
            continue;
        // the state bundle: the end of clock t
        const auto& sw_ = d.state_dump;        // (WP75) 65 bits: fetch_since is 4
        int s_at = 0;
        auto take = [&](int bits) {
            long v = 0;
            for (int i = 0; i < bits; ++i, ++s_at)
                v |= long((sw_[s_at / 32] >> (s_at % 32)) & 1u) << i;
            return v;
        };
        const long valid = take(1), kind = take(3), pos = take(3), len = take(3), ext = take(1),
                   internal = take(1), latch = take(1), addr = take(20), width = take(2),
                   data = take(16), gap = take(1), fsince = take(4), io_tail = take(3),
                   wl = take(3), rlen = take(3);
        b.check(b.state_bad, t, "state.valid", r["valid"], valid);
        if (r["valid"] && valid) {
            b.check(b.state_bad, t, "state.kind", r["skind"], kind);
            b.check(b.state_bad, t, "state.pos", r["pos"], pos);
            b.check(b.state_bad, t, "state.len", r["len"], len);
            b.check(b.state_bad, t, "state.ext", r["sext"], ext);
            b.check(b.state_bad, t, "state.internal", r["sint"], internal);
            b.check(b.state_bad, t, "state.latch", r["slatch"], latch);
            b.check(b.state_bad, t, "state.addr", r["saddr"], addr);
            b.check(b.state_bad, t, "state.width", r["swidth"], width);
            b.check(b.state_bad, t, "state.data", r["sdata"], data);
        }
        b.check(b.state_bad, t, "state.gap", r["gap"], gap);
        b.check(b.state_bad, t, "state.fetch_since", r["sfsince"], fsince);
        b.check(b.state_bad, t, "state.io_tail", r["io_tail"], io_tail);
        b.check(b.state_bad, t, "state.wlatch", r["wl"], wl);
        b.check(b.state_bad, t, "state.refresh_len", r["rlen"], rlen);
        if (valid && pos == 0)
            std::printf("CYC %ld %ld %ld %ld %ld %ld\n", t, len, kind, addr, width, data);
    }
    std::printf("SUMMARY clocks=%ld signal_bad=%ld state_bad=%ld pin_bad=%ld\n",
                long(rows.size()), b.signal_bad, b.state_bad, b.pin_bad);
    return b.fails ? 1 : 0;
}
