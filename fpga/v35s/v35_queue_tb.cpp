// Queue bench (HDL plan, C2): feeds v35_queue the frozen model's queue ops and checks every
// model clock. Vectors: validation/v35s/chains/rtl_vectors.py (V35QUEUE-1: per model clock
// the delivery, the ops in model order with the state after each, the end of the clock).
//
//   Vv35_queue_tb QUEUE_VECTORS [BIU_VECTORS]
//
// With one file the queue runs alone: its delivery (phase C) and its phase-E inputs are the
// model's. With the bus unit's vectors too (V35BIU-1, C1) the two run together (`joint`):
// the queue's delivery is the bus unit's (its done, address and the data it latched from
// the chain's memory image), phase E's "a fetch ends this clock" is the bus unit's, and the
// bus unit's fetch requests are the queue's own issues, passed only when the queue's last
// wants_fetch this clock said so (a left-out write's slot fetch passes as the model's does),
// at the queue's fetch pointer, with the word read from the image; every other cycle is
// scripted as in C1, and the bus unit's per-clock signals and state are checked as there.
//
// One model clock is three system clocks: the inputs and a first evaluation, the middle of
// the CPU state (ce_mid: the bus unit latches read data), the end of the model clock (ce).
// The queue's chain is compared after the middle (in joint mode its delivered word is the
// bus unit's latched data): the state after phases C and A, each op's read and state, the
// end of the clock; after ce the registered state again.
//
// Output: "FAIL ..." for the first failures, "CYC start length kind addr width data" for
// each cycle the bus unit started (joint), "SUMMARY clocks=N ops=N state_bad=N rd_bad=N
// error_bad=N gate_bad=N signal_bad=N biu_state_bad=N". Exit 0 when nothing failed.
#include "Vv35_queue_tb.h"
#include "verilated.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace {

constexpr int NSLOT = 16;
constexpr int OPW = 33;
constexpr int K_FETCH = 1, K_REFRESH = 6;
constexpr int OP_WANT = 16, OP_ISSUE = 23;

struct Field {
    std::string name;
    int width;
};

struct State {
    std::vector<uint64_t> v;
};

struct Op {
    int code, a, b;
    long val;
    int snap;
    long rd;
    State after;
};

struct Clock {
    long t;
    int c_done, c_fetch, c_refresh, c_odd, c_data, c_snap;
    int e_fetch_end, e_io, e_out, e_snap;
    State c_state;
    std::vector<Op> ops;
    State e_state;
};

// the bus unit's vector columns (rtl_vectors.COLUMNS)
const char* const BCOL[] = {
    "t", "has_row",
    "start", "kind", "addr", "width", "data", "ext", "latch",
    "fill", "rfm_load", "rfm_value", "data_in",
    "busy", "free", "in_wait", "finf", "fprev", "fsince", "io_win", "wl_busy",
    "busy_x", "free_x", "in_wait_x", "finf_x", "fprev_x", "fsince_x", "io_win_x", "wl_busy_x",
    "done", "dkind", "daddr", "dwidth", "ddata",
    "valid", "skind", "pos", "len", "sext", "sint", "slatch", "saddr", "swidth", "sdata",
    "gap", "sfsince", "io_tail", "wl", "rlen",
};
constexpr int NBCOL = sizeof(BCOL) / sizeof(BCOL[0]);
int bcol(const char* name) {
    for (int i = 0; i < NBCOL; ++i)
        if (std::string(BCOL[i]) == name)
            return i;
    std::fprintf(stderr, "no column %s\n", name);
    std::exit(2);
}

template <typename W>
uint64_t get_bits(const W& w, int lsb, int n) {
    uint64_t v = 0;
    for (int i = 0; i < n; ++i) {
        const int b = lsb + i;
        if ((w[b / 32] >> (b % 32)) & 1u)
            v |= uint64_t(1) << i;
    }
    return v;
}

template <typename W>
void set_bits(W& w, int lsb, int n, uint64_t v) {
    for (int i = 0; i < n; ++i) {
        const int b = lsb + i;
        const uint32_t m = 1u << (b % 32);
        if ((v >> i) & 1)
            w[b / 32] |= m;
        else
            w[b / 32] &= ~m;
    }
}

struct Bench {
    VerilatedContext context;
    Vv35_queue_tb dut{&context};
    std::vector<Field> fields;
    int width = 0;
    long state_bad = 0, rd_bad = 0, error_bad = 0, gate_bad = 0, signal_bad = 0,
         biu_state_bad = 0, fails = 0;

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
    void fail(long& counter, long t, const std::string& what, long want, long got) {
        ++counter;
        if (++fails <= 20)
            std::printf("FAIL clock %ld %s model=%ld rtl=%ld\n", t, what.c_str(), want, got);
    }
    void check(long& counter, long t, const std::string& what, long want, long got) {
        if (want != got)
            fail(counter, t, what, want, got);
    }
    // compare a state (the fields MSB first) with `width` bits of w from bit lsb
    template <typename W>
    void check_state(long t, const std::string& where, const State& s, const W& w, int lsb) {
        int off = 0;
        bool bad = false;
        for (size_t k = 0; k < fields.size(); ++k) {
            const int fw = fields[k].width;
            off += fw;
            const uint64_t got = get_bits(w, lsb + width - off, fw);
            const uint64_t want = s.v[k];
            if (got != want) {
                if (!bad)
                    ++state_bad;
                bad = true;
                if (++fails <= 20)
                    std::printf("FAIL clock %ld %s %s model=%llu rtl=%llu\n", t, where.c_str(),
                                fields[k].name.c_str(), (unsigned long long)want,
                                (unsigned long long)got);
            }
        }
    }
};

bool read_state(std::istream& in, size_t n, State& s) {
    std::string tag;
    in >> tag;
    if (tag != "S")
        return false;
    s.v.resize(n);
    for (auto& x : s.v)
        in >> x;
    return bool(in);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s QUEUE_VECTORS [BIU_VECTORS]\n", argv[0]);
        return 2;
    }
    std::ifstream in(argv[1]);
    std::string format, id;
    long nclocks = 0, nslot = 0, init_count = 0, mem_base = 0;
    unsigned long long init_data = 0;
    long init_faddr = 0;
    in >> format >> id >> nclocks >> nslot >> init_count >> init_data >> init_faddr;
    if (format != "V35QUEUE-1" || nslot != NSLOT) {
        std::fprintf(stderr, "not a V35QUEUE-1 vector file for %d slots\n", NSLOT);
        return 2;
    }
    Bench b;
    std::string tag, hex;
    in >> tag >> mem_base >> hex;
    if (tag != "M") {
        std::fprintf(stderr, "no memory line\n");
        return 2;
    }
    std::vector<int> mem(hex.size() / 2);
    for (size_t i = 0; i < mem.size(); ++i)
        mem[i] = std::stoi(hex.substr(2 * i, 2), nullptr, 16);
    auto byte_at = [&](long a) {
        const long k = a - mem_base;
        return (k >= 0 && k < long(mem.size())) ? mem[k] : 0x90;
    };
    auto word_at = [&](long a) { return byte_at(a) | (byte_at(a + 1) << 8); };
    {
        std::string line;
        std::getline(in, line);
        std::getline(in, line);
        std::istringstream fl(line);
        fl >> tag;
        std::string f;
        while (fl >> f) {
            const auto c = f.find(':');
            b.fields.push_back({f.substr(0, c), std::stoi(f.substr(c + 1))});
            b.width += b.fields.back().width;
        }
        if (tag != "F" || b.width != 180) {
            std::fprintf(stderr, "bad field line (%d bits)\n", b.width);
            return 2;
        }
    }
    const size_t nf = b.fields.size();
    std::vector<Clock> clocks(nclocks);
    for (auto& c : clocks) {
        long nops = 0;
        in >> tag >> c.t >> c.c_done >> c.c_fetch >> c.c_refresh >> c.c_odd >> c.c_data >>
            c.c_snap >> c.e_fetch_end >> c.e_io >> c.e_out >> c.e_snap >> nops;
        if (tag != "K" || !read_state(in, nf, c.c_state)) {
            std::fprintf(stderr, "bad clock line\n");
            return 2;
        }
        c.ops.resize(nops);
        for (auto& o : c.ops) {
            in >> tag >> o.code >> o.a >> o.b >> o.val >> o.snap >> o.rd;
            if (tag != "O" || !read_state(in, nf, o.after)) {
                std::fprintf(stderr, "bad op line\n");
                return 2;
            }
        }
        if (!read_state(in, nf, c.e_state)) {
            std::fprintf(stderr, "truncated vector file\n");
            return 2;
        }
    }

    // the bus unit's vectors (joint)
    const bool joint = argc > 2;
    std::vector<std::vector<long>> brows;
    std::string bwtc = "0", brfm = "0";
    if (joint) {
        std::ifstream bin(argv[2]);
        std::string bformat, bid;
        long bn = 0, bcycles = 0;
        bin >> bformat >> bid >> bwtc >> brfm >> bn >> bcycles;
        if (bformat != "V35BIU-1" || bid != id) {
            std::fprintf(stderr, "not the run's V35BIU-1 vector file\n");
            return 2;
        }
        brows.assign(bn, std::vector<long>(NBCOL));
        for (auto& r : brows)
            for (auto& x : r)
                bin >> x;
        if (!bin) {
            std::fprintf(stderr, "truncated bus unit vectors\n");
            return 2;
        }
    }

    Verilated::commandArgs(argc, argv);
    auto& d = b.dut;
    d.joint = joint;
    d.init_count = init_count;
    d.init_data = init_data;
    d.init_fetch_addr = init_faddr;
    d.wtc = std::stoul(bwtc, nullptr, 16);
    d.rfm = std::stoul(brfm, nullptr, 16);
    d.reset_n = 0;
    for (int i = 0; i < 4; ++i)
        b.tick(false, false);
    d.reset_n = 1;

    long nops_total = 0;
    const int C_T = bcol("t"), C_START = bcol("start"), C_KIND = bcol("kind");
    for (const auto& c : clocks) {
        const long t = c.t;
        d.c_done = c.c_done;
        d.c_fetch = c.c_fetch;
        d.c_refresh = c.c_refresh;
        d.c_odd = c.c_odd;
        d.c_data = c.c_data;
        d.c_snap = c.c_snap;
        d.e_fetch_end = c.e_fetch_end;
        d.e_io = c.e_io;
        d.e_out = c.e_out;
        d.e_snap = c.e_snap;
        for (int i = 0; i < NSLOT; ++i) {
            uint64_t w = 0;
            if (i < int(c.ops.size())) {
                const auto& o = c.ops[i];
                w = (uint64_t(o.code) << 27) | (uint64_t(o.a) << 26) | (uint64_t(o.b) << 25) |
                    (uint64_t(o.val & 0xFFFFF) << 5) | uint64_t(o.snap);
            }
            set_bits(d.op, i * OPW, OPW, w);
        }
        nops_total += long(c.ops.size());
        const std::vector<long>* br = nullptr;
        if (joint) {
            if (t >= long(brows.size()) || brows[t][C_T] != t) {
                std::fprintf(stderr, "bus unit vectors out of step at %ld\n", t);
                return 2;
            }
            br = &brows[t];
            const auto& r = *br;
            // the fetches are the queue's
            const bool fetch = r[C_START] && r[C_KIND] == K_FETCH;
            d.req_start = r[C_START] && !fetch;
            d.req_kind = r[C_KIND];
            d.req_addr = r[bcol("addr")];
            d.req_width = r[bcol("width")];
            d.req_data = r[bcol("data")];
            d.req_ext = r[bcol("ext")];
            d.req_latch = r[bcol("latch")];
            d.wlatch_fill = r[bcol("fill")];
            d.rfm_load = r[bcol("rfm_load")];
            d.rfm_value = r[bcol("rfm_value")];
            d.fetch_gate = 0;
            d.eval();
            // the delivered word: a fetch's from the image at the bus unit's address
            d.data_in = (d.done && d.done_kind == K_FETCH) ? word_at(d.done_addr)
                                                           : r[bcol("data_in")];
            // the queue's issue goes on its own request
            int gate = 0;
            for (int i = 0; i < int(c.ops.size()); ++i) {
                if (c.ops[i].code != OP_ISSUE)
                    continue;
                if (c.ops[i].b) {
                    gate = 1;               // the left-out write's slot (grp_read)
                } else {
                    for (int k = i - 1; k >= 0; --k)
                        if (c.ops[k].code == OP_WANT) {
                            gate = int(get_bits(d.rd, 8 * k, 8) & 1);
                            break;
                        }
                    if (!gate)
                        b.fail(b.gate_bad, t, "fetch issued without the queue's request", 1, 0);
                }
            }
            d.fetch_gate = gate;
            d.eval();
            d.fetch_data = word_at(d.fetch_issue_addr);
            d.eval();
            const auto col = [&](const char* n) { return r[bcol(n)]; };
            b.check(b.signal_bad, t, "busy", col("busy"), d.busy);
            b.check(b.signal_bad, t, "free", col("free"), d.free);
            b.check(b.signal_bad, t, "in_wait", col("in_wait"), d.in_wait);
            b.check(b.signal_bad, t, "fetch_inflight", col("finf"), d.fetch_inflight);
            b.check(b.signal_bad, t, "fetch_end_prev", col("fprev"), d.fetch_end_prev);
            b.check(b.signal_bad, t, "fetch_since", col("fsince"), d.fetch_since);
            b.check(b.signal_bad, t, "io_win", col("io_win"), d.io_win);
            b.check(b.signal_bad, t, "wlatch_busy", col("wl_busy"), d.wlatch_busy);
            if (col("has_row")) {
                b.check(b.signal_bad, t, "busy_x", col("busy_x"), d.busy_x);
                b.check(b.signal_bad, t, "free_x", col("free_x"), d.free_x);
                b.check(b.signal_bad, t, "in_wait_x", col("in_wait_x"), d.in_wait_x);
                b.check(b.signal_bad, t, "fetch_inflight_x", col("finf_x"), d.fetch_inflight_x);
                b.check(b.signal_bad, t, "fetch_since_x", col("fsince_x"), d.fetch_since_x);
                b.check(b.signal_bad, t, "io_win_x", col("io_win_x"), d.io_win_x);
                b.check(b.signal_bad, t, "wlatch_busy_x", col("wl_busy_x"), d.wlatch_busy_x);
            }
            b.check(b.signal_bad, t, "done", col("done"), d.done);
            if (d.done && col("done")) {
                b.check(b.signal_bad, t, "done_kind", col("dkind"), d.done_kind);
                b.check(b.signal_bad, t, "done_addr", col("daddr"), d.done_addr);
            }
        } else {
            d.eval();
        }

        // the middle of the CPU state, then the queue's chain
        b.tick(false, true);
        if (joint && (*br)[bcol("done")] && (*br)[bcol("ddata")] >= 0)
            b.check(b.signal_bad, t, "done_data", (*br)[bcol("ddata")], d.done_data);
        b.check_state(t, "after C", c.c_state, d.state_c, 0);
        for (int i = 0; i < int(c.ops.size()); ++i) {
            const auto& o = c.ops[i];
            char where[64];
            std::snprintf(where, sizeof where, "op %d (code %d)", i, o.code);
            if (o.rd >= 0)
                b.check(b.rd_bad, t, std::string(where) + " rd", o.rd,
                        long(get_bits(d.rd, 8 * i, 8)));
            b.check_state(t, where, o.after, d.state_op, i * b.width);
        }
        b.check_state(t, "end", c.e_state, d.state_e, 0);

        // the end of the model clock
        b.tick(true, false);
        b.check(b.error_bad, t, "queue error", 0, d.q_error);
        b.check_state(t, "registered", c.e_state, d.state_dump, 0);
        if (joint) {
            const auto& r = *br;
            b.check(b.signal_bad, t, "bus unit error", 0, d.biu_error);
            if (r[bcol("has_row")]) {
                uint64_t s = d.biu_state;
                auto take = [&](int bits) {
                    const long v = long(s & ((uint64_t(1) << bits) - 1));
                    s >>= bits;
                    return v;
                };
                const long valid = take(1), kind = take(3), pos = take(3), len = take(3);
                const long ext = take(1), internal = take(1), latch = take(1), addr = take(20);
                const long width = take(2), data = take(16);
                const long gap = take(1), fsince = take(3), io_tail = take(3), wl = take(3),
                           rlen = take(3);
                const auto col = [&](const char* n) { return r[bcol(n)]; };
                b.check(b.biu_state_bad, t, "biu.valid", col("valid"), valid);
                if (col("valid") && valid) {
                    b.check(b.biu_state_bad, t, "biu.kind", col("skind"), kind);
                    b.check(b.biu_state_bad, t, "biu.pos", col("pos"), pos);
                    b.check(b.biu_state_bad, t, "biu.len", col("len"), len);
                    b.check(b.biu_state_bad, t, "biu.ext", col("sext"), ext);
                    b.check(b.biu_state_bad, t, "biu.internal", col("sint"), internal);
                    b.check(b.biu_state_bad, t, "biu.latch", col("slatch"), latch);
                    b.check(b.biu_state_bad, t, "biu.addr", col("saddr"), addr);
                    b.check(b.biu_state_bad, t, "biu.width", col("swidth"), width);
                    b.check(b.biu_state_bad, t, "biu.data", col("sdata"), data);
                }
                b.check(b.biu_state_bad, t, "biu.gap", col("gap"), gap);
                b.check(b.biu_state_bad, t, "biu.fetch_since", col("sfsince"), fsince);
                b.check(b.biu_state_bad, t, "biu.io_tail", col("io_tail"), io_tail);
                b.check(b.biu_state_bad, t, "biu.wlatch", col("wl"), wl);
                b.check(b.biu_state_bad, t, "biu.refresh_len", col("rlen"), rlen);
                if (valid && pos == 0)
                    std::printf("CYC %ld %ld %ld %ld %ld %ld\n", t, len, kind, addr, width, data);
            }
        }
    }
    // joint: the bus unit's last clock (the END write's delivery) has no queue clock
    if (joint && long(brows.size()) > nclocks) {
        // nothing starts there (the model's run returns at the END write's delivery)
    }
    std::printf("SUMMARY clocks=%ld ops=%ld state_bad=%ld rd_bad=%ld error_bad=%ld gate_bad=%ld "
                "signal_bad=%ld biu_state_bad=%ld\n",
                long(clocks.size()), nops_total, b.state_bad, b.rd_bad, b.error_bad, b.gate_bad,
                b.signal_bad, b.biu_state_bad);
    return b.fails ? 1 : 0;
}
