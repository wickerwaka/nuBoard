// Chain-model core bench (HDL plan, C4; C5: refresh): runs v35_chain_core on a chain and checks it against the
// frozen model on every model clock. Vectors: validation/v35s/chains/rtl_vectors.py --core, four
// files of one run: the EU's (V35EU-3: the start state with the register file's presets, the code,
// (D2) the memory's image, the operand record of every instruction start and the register file
// before it (the functional reference's, funcref.py), per clock the EU's state after every phase
// (its functional fields f_ and x_ not compared), its queue ops and the arbiter's touches),
// the queue's (V35QUEUE-1 with JSLOT ops: the image, the preload, per clock the queue's state
// after the delivery, after every op of the chain and at the end), the bus unit's (V35BIU-1:
// per clock the window signals, the delivery and the state bundle) and the arbiter's (V35ARB-2:
// whether the chain runs the refresh controller and its counter at clock 0, per clock the
// arbiter's state after X and at the end and the refresh controller's after R and at the end,
// and (D2) the EU cycles' data in order, the functional reference's).
//
//   Vv35_core_tb EU_VECTORS QUEUE_VECTORS BIU_VECTORS ARB_VECTORS [MUTATE]
//
// The core makes every timing decision and (D1) computes every operand record, the register
// file and the EU's write data: the bench gives it the start state and serves its memory from
// the image (the code window at code_addr, a fetch's word at its address, the delivered word: D2,
// the aligned word of a memory written by the core's own writes, an I/O read's 0000h); per
// model clock it clocks the core's settle iterations until `settled`, checks, then ends the
// clock (`run`). Checks: the EU's state after C, T, L, X, P and the end, its queue ops; the
// queue's state after C, after every op of the chain and at the end, every read, the chain's ops
// (the EU's, the arbiter's, the EU's in P) against the model's; the arbiter's touches on the EU,
// its state after X and at the end; the bus unit's signals and state bundle; the core's and the
// machines' errors; the refresh controller's state after R, at the end and registered; (D1) each
// start's operand record and (D2) the register file before it, and every EU cycle's datum.
// MUTATE (1..7) flips one of the arbiter's decisions (v35_arbiter.sv; 5..7 the refresh's), 8..13
// one of the register file's or the ALU's (v35_eu.sv: an EA mode, a push's SP step, MOV r8,imm8's
// byte; D2: ADD's AC, a write's datum, the BP-based modes' segment).
//
// Output: "FAIL ..." for the first failures, "CYC start length kind addr width data" for each
// cycle the bus unit started, "DCYC t kind addr width" for each data cycle the EU issued, "ITER n
// count" (the settle edges a model clock took: its histogram), "SUMMARY clocks=N ... ". Exit 0
// when nothing failed.
#include "Vv35_core_tb.h"
#include "verilated.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <type_traits>
#include <vector>

namespace {

constexpr int NQ = 16, NXOP = 6, NXQ = 8, JSLOT = 40, STATE_W = 879, QSTATE_W = 180,
              ASTATE_W = 103, RSTATE_W = 24, XOPW = 12;
constexpr int OPW = 33, QVW = 52, OPNDW = 197, RFW = 211;
constexpr int K_FETCH = 1, K_READ = 2, K_WRITE = 3, K_IO_READ = 4;
constexpr int BW_WORD = 0, BW_LO = 1, BW_HI = 2;
constexpr long SFR_PAGE = 0xFFF00;
constexpr int IO_WORD = 0x0000;     // (D2) the board's I/O reads (funcref.IO_WORD)
constexpr int X_ISSUE = 1;
constexpr int MAX_ITER = 256;

struct Field {
    std::string name;
    int width;
    bool func = false;      // (D2) a functional field (f_, x_): not in the state comparison
};

using Vals = std::vector<uint64_t>;

struct Op {
    int code = 0, a = 0, b = 0;
    long val = 0;
    int snap = 0;
    long rd = -1;
    Vals view;
};

struct Clock {
    long t = 0;
    int c_eu = 0, c_read = 0, fetch_done = 0, x_valid = 0, x_kind = 0, x_eu = 0, x_len = 0;
    int counts_t[3] = {0, 0, 0}, counts_p[3] = {0, 0, 0};
    int latch_in = 0, ntl = 0, n_t = 0, nx = 0, np = 0, nxops = 0;
    Vals bus_t, bus_p;
    Vals s_c, s_t, s_l, s_x, s_p, s_e;
    std::vector<Op> tl, p;
    Vals v_tl, v_p;
    std::vector<std::pair<int, int>> xops;
};

struct QClock {
    long t;
    int k[11];
    Vals c_state, e_state;
    std::vector<std::pair<std::vector<long>, Vals>> ops;   // (code a b val snap rd), state after
};

struct AClock {
    long t = 0;
    int ext = 0;
    Vals s_x, s_e;
    Vals r_r, r_e;          // (C5) the refresh controller after R and at the end
};

// (D1) the operand record (v35_opnd_t, MSB first) and the register file (v35_rf_t)
const int OPND_W[] = {16, 48, 20, 16, 16, 16, 9, 1, 16, 31, 8};
const char* const OPND_N[] = {"offset", "code", "ea", "port", "sr", "sw", "count", "taken",
                              "target", "fmt", "tmpl"};
constexpr int NOPND = 11;
const int RF_W[] = {16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 3};
const char* const RF_N[] = {"aw", "cw", "dw", "bw", "sp", "bp", "ix", "iy", "ps", "ss", "ds0",
                            "ds1", "psw", "pfx"};
constexpr int NRF = 14;
constexpr int NBV = 10;

template <typename W>
uint64_t get_bits(const W& w, int lsb, int n) {
    if constexpr (std::is_integral_v<W>) {
        return (uint64_t(w) >> lsb) & (n >= 64 ? ~uint64_t(0) : (uint64_t(1) << n) - 1);
    } else {
        uint64_t v = 0;
        for (int i = 0; i < n; ++i) {
            const int b = lsb + i;
            if ((w[b / 32] >> (b % 32)) & 1u)
                v |= uint64_t(1) << i;
        }
        return v;
    }
}

template <typename W>
void set_bits(W& w, int lsb, int n, uint64_t v) {
    if constexpr (std::is_integral_v<W>) {
        const uint64_t m = (n >= 64 ? ~uint64_t(0) : (uint64_t(1) << n) - 1) << lsb;
        w = W((uint64_t(w) & ~m) | ((v << lsb) & m));
    } else {
        for (int i = 0; i < n; ++i) {
            const int b = lsb + i;
            const uint32_t m = 1u << (b % 32);
            if ((v >> i) & 1)
                w[b / 32] |= m;
            else
                w[b / 32] &= ~m;
        }
    }
}

template <typename W>
void pack(W& w, int lsb, const Vals& v, const std::vector<int>& widths) {
    int total = 0;
    for (int x : widths)
        total += x;
    int off = total;
    for (size_t k = 0; k < widths.size(); ++k) {
        off -= widths[k];
        set_bits(w, lsb + off, widths[k], v[k]);
    }
}

bool read_vals(std::istream& in, const char* tag, size_t n, Vals& v) {
    std::string t;
    in >> t;
    if (t != tag)
        return false;
    v.resize(n);
    for (auto& x : v)
        in >> x;
    return bool(in);
}

std::vector<Field> parse_fields(const std::string& line, int& width) {
    std::istringstream fl(line);
    std::string tag, f;
    fl >> tag;
    std::vector<Field> out;
    width = 0;
    while (fl >> f) {
        const auto c = f.find(':');
        out.push_back({f.substr(0, c), std::stoi(f.substr(c + 1))});
        width += out.back().width;
    }
    return out;
}

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

struct Bench {
    VerilatedContext context;
    Vv35_core_tb dut{&context};
    std::vector<Field> fields, qfields, afields, rfields;
    long state_bad = 0, op_bad = 0, err_bad = 0, dcyc_bad = 0, q_state_bad = 0, q_rd_bad = 0,
         x_bad = 0, a_state_bad = 0, r_state_bad = 0, signal_bad = 0, biu_state_bad = 0,
         settle_bad = 0, opnd_bad = 0, fails = 0;

    void tick(bool run, bool mid) {
        dut.run = run;
        dut.ce_mid = mid;
        dut.clock = 1;
        dut.eval();
        dut.clock = 0;
        dut.eval();
        dut.run = 0;
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
        // (D1) a packed record (MSB first) against the model's values
    template <typename W>
    bool check_packed(long t, const std::string& where, const char* const* names,
                      const int* widths, int n, const Vals& want, const W& w) {
        int total = 0;
        for (int k = 0; k < n; ++k)
            total += widths[k];
        int off = total;
        bool bad = false;
        for (int k = 0; k < n; ++k) {
            off -= widths[k];
            const uint64_t got = get_bits(w, off, widths[k]);
            if (got != want[k]) {
                bad = true;
                if (++fails <= 20)
                    std::printf("FAIL clock %ld %s %s model=%llu rtl=%llu\n", t, where.c_str(),
                                names[k], (unsigned long long)want[k], (unsigned long long)got);
            }
        }
        return bad;
    }
    template <typename W>
    void check_state(long& counter, long t, const std::string& where,
                     const std::vector<Field>& fs, int width, const Vals& s, const W& w, int lsb) {
        int off = 0;
        bool bad = false;
        for (size_t k = 0; k < fs.size(); ++k) {
            off += fs[k].width;
            if (fs[k].func)
                continue;
            const uint64_t got = get_bits(w, lsb + width - off, fs[k].width);
            if (got != s[k]) {
                if (!bad)
                    ++counter;
                bad = true;
                if (++fails <= 20)
                    std::printf("FAIL clock %ld %s %s model=%llu rtl=%llu\n", t, where.c_str(),
                                fs[k].name.c_str(), (unsigned long long)s[k],
                                (unsigned long long)got);
            }
        }
    }
};

}  // namespace

int main(int argc, char** argv) {
    if (argc != 5 && argc != 6) {
        std::fprintf(stderr, "usage: %s EU_VECTORS QUEUE_VECTORS BIU_VECTORS ARB_VECTORS [MUTATE]\n",
                     argv[0]);
        return 2;
    }
    Bench b;
    std::string format, id, line, tag;
    int width = 0;

    // ---- the EU's vectors
    std::ifstream in(argv[1]);
    long nclocks = 0, nq = 0, nxop = 0, nopnd = 0, base = 0, org = 0;
    in >> format >> id >> nclocks >> nq >> nxop >> nopnd >> base >> org;
    if (format != "V35EU-3" || nq != NQ || nxop != NXOP) {
        std::fprintf(stderr, "not a V35EU-3 vector file for %d ops, %d touches\n", NQ, NXOP);
        return 2;
    }
    std::getline(in, line);
    std::getline(in, line);
    b.fields = parse_fields(line, width);
    for (auto& f : b.fields)
        f.func = f.name.rfind("f_", 0) == 0 || f.name.rfind("x_", 0) == 0;
    if (width != STATE_W) {
        std::fprintf(stderr, "bad field line (%d bits)\n", width);
        return 2;
    }
    std::getline(in, line);
    int qvw = 0;
    const auto qview_fields = parse_fields(line, qvw);
    if (qvw != QVW) {
        std::fprintf(stderr, "bad queue view line (%d bits)\n", qvw);
        return 2;
    }
    const size_t nf = b.fields.size(), nqv = qview_fields.size();
    Vals init;
    if (!read_vals(in, "I", nf, init)) {
        std::fprintf(stderr, "no init line\n");
        return 2;
    }
    // (D1) the code at the base: the code window's bytes
    std::string chex;
    in >> tag >> chex;
    if (tag != "C") {
        std::fprintf(stderr, "no code line\n");
        return 2;
    }
    std::vector<int> code(chex.size() / 2);
    for (size_t i = 0; i < code.size(); ++i)
        code[i] = std::stoi(chex.substr(2 * i, 2), nullptr, 16);
    // (D2) the memory: 90h but for the functional reference's image runs; the core's writes
    // go into it, its reads come from it
    std::vector<uint8_t> memory(1 << 20, 0x90);
    {
        long nrun = 0;
        in >> tag >> nrun;
        if (tag != "N") {
            std::fprintf(stderr, "no memory line\n");
            return 2;
        }
        for (long r = 0; r < nrun; ++r) {
            long a;
            std::string mh;
            in >> a >> mh;
            for (size_t i = 0; i < mh.size() / 2; ++i)
                memory[(a + long(i)) & 0xFFFFF] = std::stoi(mh.substr(2 * i, 2), nullptr, 16);
        }
    }
    // the operand records and (D2) the register file before each start (the functional
    // reference's)
    std::vector<Vals> opnds(nopnd), rfs(nopnd);
    for (long i = 0; i < nopnd; ++i) {
        auto& o = opnds[i];
        std::string hex;
        long offset;
        in >> tag >> offset >> hex;
        if (tag != "P") {
            std::fprintf(stderr, "bad operand line\n");
            return 2;
        }
        o.push_back(offset);
        o.push_back(std::stoull(hex, nullptr, 16));
        for (int k = 0; k < NOPND - 2; ++k) {
            uint64_t x;
            in >> x;
            o.push_back(x);
        }
        rfs[i].resize(NRF);
        for (auto& x : rfs[i])
            in >> x;
    }
    std::vector<Clock> clocks(nclocks);
    auto read_op = [&](Op& o) {
        in >> tag >> o.code >> o.a >> o.b >> o.val >> o.snap >> o.rd;
        o.view.resize(nqv);
        for (auto& x : o.view)
            in >> x;
        return tag == "O" && bool(in);
    };
    for (auto& c : clocks) {
        in >> tag >> c.t >> c.c_eu >> c.c_read >> c.fetch_done >> c.x_valid >> c.x_kind >>
            c.x_eu >> c.x_len >> c.counts_t[0] >> c.counts_t[1] >> c.counts_t[2] >>
            c.counts_p[0] >> c.counts_p[1] >> c.counts_p[2] >> c.latch_in >> c.ntl >> c.n_t >>
            c.nx >> c.np >> c.nxops;
        if (tag != "K") {
            std::fprintf(stderr, "bad clock line\n");
            return 2;
        }
        Vals bv;
        if (!read_vals(in, "B", 2 * NBV, bv)) {
            std::fprintf(stderr, "bad bus line\n");
            return 2;
        }
        bool ok = read_vals(in, "S", nf, c.s_c);
        c.tl.resize(c.ntl);
        for (auto& o : c.tl)
            ok = ok && read_op(o);
        ok = ok && read_vals(in, "V", nqv, c.v_tl) && read_vals(in, "S", nf, c.s_t) &&
             read_vals(in, "S", nf, c.s_l);
        for (int i = 0; i < c.nxops; ++i) {
            int code, val;
            in >> tag >> code >> val;
            ok = ok && tag == "X";
            c.xops.push_back({code, val});
        }
        ok = ok && read_vals(in, "S", nf, c.s_x);
        c.p.resize(c.np);
        for (auto& o : c.p)
            ok = ok && read_op(o);
        ok = ok && read_vals(in, "V", nqv, c.v_p) && read_vals(in, "S", nf, c.s_p) &&
             read_vals(in, "S", nf, c.s_e);
        if (!ok) {
            std::fprintf(stderr, "truncated vector file at clock %ld\n", c.t);
            return 2;
        }
    }
    std::map<long, std::vector<long>> dcyc;     // the model's EU cycles: start -> kind addr width
    while (in >> tag) {                         // (D2) data: the functional reference's datum
        if (tag != "D")
            break;
        long s, k, a, w, dd;
        in >> s >> k >> a >> w >> dd;
        dcyc[s] = {k, a, w, dd};
    }

    // ---- the queue's vectors (JSLOT ops)
    std::ifstream qin(argv[2]);
    std::string qformat, qid, hex;
    long qn = 0, qslot = 0, q_init_count = 0, q_init_faddr = 0, mem_base = 0;
    unsigned long long q_init_data = 0;
    qin >> qformat >> qid >> qn >> qslot >> q_init_count >> q_init_data >> q_init_faddr;
    if (qformat != "V35QUEUE-1" || qid != id || qslot != JSLOT || qn != nclocks) {
        std::fprintf(stderr, "not the run's V35QUEUE-1 vector file for %d slots\n", JSLOT);
        return 2;
    }
    qin >> tag >> mem_base >> hex;
    std::vector<int> mem(hex.size() / 2);
    for (size_t i = 0; i < mem.size(); ++i)
        mem[i] = std::stoi(hex.substr(2 * i, 2), nullptr, 16);
    std::getline(qin, line);
    std::getline(qin, line);
    b.qfields = parse_fields(line, width);
    if (width != QSTATE_W) {
        std::fprintf(stderr, "bad queue field line (%d bits)\n", width);
        return 2;
    }
    const size_t nqf = b.qfields.size();
    std::vector<QClock> qclocks(qn);
    for (auto& c : qclocks) {
        long nops = 0;
        qin >> tag >> c.t;
        for (int k = 0; k < 10; ++k)
            qin >> c.k[k];
        qin >> nops;
        if (tag != "K" || !read_vals(qin, "S", nqf, c.c_state)) {
            std::fprintf(stderr, "bad queue clock line\n");
            return 2;
        }
        c.ops.resize(nops);
        for (auto& o : c.ops) {
            o.first.resize(6);
            qin >> tag;
            for (auto& x : o.first)
                qin >> x;
            if (tag != "O" || !read_vals(qin, "S", nqf, o.second)) {
                std::fprintf(stderr, "bad queue op line\n");
                return 2;
            }
        }
        if (!read_vals(qin, "S", nqf, c.e_state)) {
            std::fprintf(stderr, "truncated queue vectors\n");
            return 2;
        }
    }

    // ---- the bus unit's vectors
    std::ifstream bin(argv[3]);
    std::string bformat, bid, bwtc, brfm;
    long bn = 0, bcycles = 0;
    bin >> bformat >> bid >> bwtc >> brfm >> bn >> bcycles;
    if (bformat != "V35BIU-1" || bid != id) {
        std::fprintf(stderr, "not the run's V35BIU-1 vector file\n");
        return 2;
    }
    std::vector<std::vector<long>> brows(bn, std::vector<long>(NBCOL));
    for (auto& r : brows)
        for (auto& x : r)
            bin >> x;
    if (!bin) {
        std::fprintf(stderr, "truncated bus unit vectors\n");
        return 2;
    }

    // ---- the arbiter's vectors
    std::ifstream ain(argv[4]);
    std::string aformat, aid;
    long an = 0, ndata = 0, refresh_on = 0, init_counter = 0;
    ain >> aformat >> aid >> an >> ndata >> refresh_on >> init_counter;
    if (aformat != "V35ARB-2" || aid != id || an != nclocks) {
        std::fprintf(stderr, "not the run's V35ARB-2 vector file\n");
        return 2;
    }
    std::getline(ain, line);
    std::getline(ain, line);
    b.afields = parse_fields(line, width);
    if (width != ASTATE_W) {
        std::fprintf(stderr, "bad arbiter field line (%d bits)\n", width);
        return 2;
    }
    std::getline(ain, line);
    b.rfields = parse_fields(line, width);
    if (width != RSTATE_W) {
        std::fprintf(stderr, "bad refresh field line (%d bits)\n", width);
        return 2;
    }
    const size_t naf = b.afields.size(), nrf = b.rfields.size();
    std::vector<AClock> aclocks(an);
    for (auto& c : aclocks) {
        ain >> tag >> c.t >> c.ext;
        if (tag != "K" || !read_vals(ain, "S", naf, c.s_x) || !read_vals(ain, "S", naf, c.s_e)) {
            std::fprintf(stderr, "bad arbiter clock\n");
            return 2;
        }
        if (refresh_on && (!read_vals(ain, "R", nrf, c.r_r) || !read_vals(ain, "R", nrf, c.r_e))) {
            std::fprintf(stderr, "bad refresh clock\n");
            return 2;
        }
    }
    std::vector<long> edata(ndata);
    ain >> tag;
    if (tag != "W") {
        std::fprintf(stderr, "no write data line\n");
        return 2;
    }
    for (auto& x : edata)
        ain >> x;
    if (!ain) {
        std::fprintf(stderr, "truncated arbiter vectors\n");
        return 2;
    }

    for (size_t i = 0; i < mem.size(); ++i)    // the queue's image (within the memory's)
        memory[(mem_base + long(i)) & 0xFFFFF] = uint8_t(mem[i]);
    auto byte_at = [&](long a) { return int(memory[a & 0xFFFFF]); };
    auto word_at = [&](long a) { return byte_at(a) | (byte_at(a + 1) << 8); };
    // (D2) the word the bus delivers: an EU read's the aligned memory word, the I/O word; a
    // fetch's the queue's (from its address, odd after a transfer to an odd target)
    auto bus_word = [&](long kind, long a) {
        return kind == K_IO_READ ? IO_WORD : kind == K_FETCH ? word_at(a) : word_at(a & ~1L);
    };
    // (D2) a write the core issued, on its lanes (the on-chip SFR page is not memory)
    auto store = [&](long a, long w, long v) {
        if (a >= SFR_PAGE)
            return;
        if (w == BW_WORD) {
            memory[a & 0xFFFFF] = uint8_t(v);
            memory[(a + 1) & 0xFFFFF] = uint8_t(v >> 8);
        } else {
            memory[a & 0xFFFFF] = uint8_t(w == BW_HI ? v >> 8 : v);
        }
    };

    Verilated::commandArgs(argc, argv);
    auto& d = b.dut;
    // (D1) the code window: twelve bytes from the core's code_addr, the first in [95:88]
    auto code_window = [&](long a) {
        for (int i = 0; i < 12; ++i) {
            const long k = a + i - base;
            const int v = (k >= 0 && k < long(code.size())) ? code[k] : 0x90;
            set_bits(d.code_win, 88 - 8 * i, 8, uint64_t(v));
        }
    };
    {
        std::vector<int> fw;
        for (auto& f : b.fields)
            fw.push_back(f.width);
        pack(d.init_state, 0, init, fw);
    }
    d.code_org = org;
    d.init_count = q_init_count;
    d.init_data = q_init_data;
    d.init_fetch_addr = q_init_faddr;
    d.wtc = std::stoul(bwtc, nullptr, 16);
    d.rfm = std::stoul(brfm, nullptr, 16);
    d.refresh_on = refresh_on;
    d.init_counter = init_counter;
    d.mutate = argc == 6 ? std::atoi(argv[5]) : 0;
    d.reset_n = 0;
    for (int i = 0; i < 4; ++i)
        b.tick(false, false);
    d.reset_n = 1;

    long nstarts = 0, nops_total = 0, ndcyc = 0, iter_total = 0, iter_max = 0;
    std::map<int, long> iter_hist;
    for (const auto& c : clocks) {
        const long t = c.t;
        const QClock& qc = qclocks[t];
        const AClock& ac = aclocks[t];
        if (t >= long(brows.size()) || brows[t][bcol("t")] != t || ac.t != t || qc.t != t) {
            std::fprintf(stderr, "vectors out of step at %ld\n", t);
            return 2;
        }
        const auto& r = brows[t];
        const auto col = [&](const char* n) { return r[bcol(n)]; };
        // the memory: (D1) the code window (from the registered pc), the delivered word
        // (latched mid-B3), the fetch's word
        d.eval();
        code_window(d.code_addr);
        d.data_in = d.done ? bus_word(d.done_kind, d.done_addr) : 0;
        b.tick(false, true);
        int iters = 1;
        for (;;) {
            d.fetch_data = word_at(d.fetch_addr);
            code_window(d.code_addr);
            d.eval();
            if (d.settled)
                break;
            if (iters >= MAX_ITER)
                break;
            b.tick(false, false);
            ++iters;
        }
        if (!d.settled)
            b.fail(b.settle_bad, t, "the clock did not settle", 1, 0);
        iter_total += iters;
        iter_max = std::max<long>(iter_max, iters);
        ++iter_hist[iters];
        nops_total += c.ntl + c.np;

        // the bus unit, as C1 (before and after the choice)
        b.check(b.signal_bad, t, "busy", col("busy"), d.b_busy);
        b.check(b.signal_bad, t, "free", col("free"), d.b_free);
        b.check(b.signal_bad, t, "fetch_inflight", col("finf"), d.b_finf);
        b.check(b.signal_bad, t, "done", col("done"), d.done);
        if (col("has_row")) {
            b.check(b.signal_bad, t, "busy_x", col("busy_x"), d.b_busy_x);
            b.check(b.signal_bad, t, "free_x", col("free_x"), d.b_free_x);
            b.check(b.signal_bad, t, "wlatch_busy_x", col("wl_busy_x"), d.b_wl_x);
        }
        b.check(b.signal_bad, t, "start", col("start"), d.req_start);
        if (col("start"))
            b.check(b.signal_bad, t, "disp_io ext", ac.ext, d.req_ext);
        // the EU, as C3
        b.check_state(b.state_bad, t, "after C", b.fields, STATE_W, c.s_c, d.eu_c, 0);
        b.check_state(b.state_bad, t, "after T", b.fields, STATE_W, c.s_t, d.eu_t, 0);
        b.check_state(b.state_bad, t, "after L", b.fields, STATE_W, c.s_l, d.eu_l, 0);
        b.check_state(b.state_bad, t, "after X", b.fields, STATE_W, c.s_x, d.eu_x, 0);
        b.check_state(b.state_bad, t, "after P", b.fields, STATE_W, c.s_p, d.eu_p, 0);
        b.check_state(b.state_bad, t, "end", b.fields, STATE_W, c.s_e, d.eu_e, 0);
        b.check(b.op_bad, t, "T/L ops", c.ntl, d.n_tl);
        b.check(b.op_bad, t, "T ops", c.n_t, d.n_t);
        b.check(b.op_bad, t, "X ops", c.nx, d.n_x);
        b.check(b.op_bad, t, "P ops", c.np, d.n_p);
        // the chain's ops: the model's (code a b val snap) against the core's slots
        for (int i = 0; i < int(qc.ops.size()) && i < JSLOT; ++i) {
            const auto& o = qc.ops[i].first;
            const uint64_t want = (uint64_t(o[0]) << 27) | (uint64_t(o[1]) << 26) |
                                  (uint64_t(o[2]) << 25) | (uint64_t(o[3] & 0xFFFFF) << 5) |
                                  uint64_t(o[4]);
            const uint64_t got = get_bits(d.slots, OPW * i, OPW);
            if (got != want) {
                char where[64];
                std::snprintf(where, sizeof where, "chain op %d (code %ld) word", i, o[0]);
                b.fail(b.op_bad, t, where, long(want), long(got));
            }
        }
        if (int(qc.ops.size()) < JSLOT)
            b.check(b.op_bad, t, "chain op past the model's", 0,
                    long(get_bits(d.slots, OPW * int(qc.ops.size()), OPW)));
        b.check(b.err_bad, t, "core err_code", 0, d.err_code);
        // the arbiter's touches on the EU
        for (int i = 0; i < NXOP; ++i) {
            const uint64_t want = i < c.nxops ? (uint64_t(c.xops[i].first) << 8) |
                                                    uint64_t(c.xops[i].second & 0xFF)
                                              : 0;
            char where[48];
            std::snprintf(where, sizeof where, "touch %d", i);
            b.check(b.x_bad, t, where, long(want), long(get_bits(d.xops, XOPW * i, XOPW)));
        }
        // the arbiter's state after X and at the end
        b.check_state(b.a_state_bad, t, "arbiter after X", b.afields, ASTATE_W, ac.s_x, d.a_x, 0);
        b.check_state(b.a_state_bad, t, "arbiter end", b.afields, ASTATE_W, ac.s_e, d.a_e, 0);
        // the refresh controller after R and at the end
        if (refresh_on) {
            b.check_state(b.r_state_bad, t, "refresh after R", b.rfields, RSTATE_W, ac.r_r, d.r_r, 0);
            b.check_state(b.r_state_bad, t, "refresh end", b.rfields, RSTATE_W, ac.r_e, d.r_e, 0);
        }
        // the EU's data cycle
        if (d.x_cyc) {
            auto it = dcyc.find(t);
            if (it == dcyc.end()) {
                b.fail(b.dcyc_bad, t, "an EU cycle without the model's", 0, 1);
            } else {
                b.check(b.dcyc_bad, t, "data cycle kind", it->second[0], d.x_cyc_kind);
                b.check(b.dcyc_bad, t, "data cycle addr", it->second[1], d.x_cyc_addr);
                b.check(b.dcyc_bad, t, "data cycle width", it->second[2], d.x_cyc_width);
            }
            // (D2) its datum: the EU's, the functional reference's; a write goes to memory
            b.check(b.dcyc_bad, t, "data cycle datum",
                    ndcyc < long(edata.size()) ? edata[ndcyc] : -1, d.x_data);
            if (d.x_cyc_kind == K_WRITE)
                store(d.x_cyc_addr, d.x_cyc_width, d.x_data);
            std::printf("DCYC %ld %d %d %d\n", t, int(d.x_cyc_kind), int(d.x_cyc_addr),
                        int(d.x_cyc_width));
            ++ndcyc;
        } else if (dcyc.count(t)) {
            b.fail(b.dcyc_bad, t, "the model's EU cycle not issued", 1, 0);
        }
        // the queue, as C2: after C, every op of the chain, the end
        b.check_state(b.q_state_bad, t, "queue after C", b.qfields, QSTATE_W, qc.c_state, d.q_c,
                      0);
        for (int i = 0; i < int(qc.ops.size()) && i < JSLOT; ++i) {
            char where[64];
            std::snprintf(where, sizeof where, "queue op %d (code %ld)", i, qc.ops[i].first[0]);
            if (qc.ops[i].first[5] >= 0)
                b.check(b.q_rd_bad, t, std::string(where) + " rd", qc.ops[i].first[5],
                        long(get_bits(d.slot_rd, 8 * i, 8)));
            b.check_state(b.q_state_bad, t, where, b.qfields, QSTATE_W, qc.ops[i].second, d.q_ops,
                          QSTATE_W * i);
        }
        b.check_state(b.q_state_bad, t, "queue end", b.qfields, QSTATE_W, qc.e_state, d.q_e, 0);

        // (D1) the operand record of each start and (D2) the register file before it
        for (int j = 0; j < int(d.n_start) && j < 2; ++j) {
            const long i = nstarts + j;
            char where[64];
            if (i >= long(opnds.size())) {
                b.fail(b.opnd_bad, t, "a start past the model's", long(opnds.size()), i);
                continue;
            }
            std::snprintf(where, sizeof where, "start %ld record", i);
            bool bad = j == 0 ? b.check_packed(t, where, OPND_N, OPND_W, NOPND, opnds[i], d.opr_a)
                              : b.check_packed(t, where, OPND_N, OPND_W, NOPND, opnds[i], d.opr_b);
            std::snprintf(where, sizeof where, "start %ld registers", i);
            bad = (j == 0 ? b.check_packed(t, where, RF_N, RF_W, NRF, rfs[i], d.rfx_a)
                          : b.check_packed(t, where, RF_N, RF_W, NRF, rfs[i], d.rfx_b)) || bad;
            if (bad)
                ++b.opnd_bad;
        }
        // the end of the model clock
        nstarts += d.n_start;
        b.tick(true, false);
        b.check(b.err_bad, t, "core error", 0, d.error);
        b.check_state(b.state_bad, t, "registered", b.fields, STATE_W, c.s_e, d.eu_dump, 0);
        b.check_state(b.q_state_bad, t, "queue registered", b.qfields, QSTATE_W, qc.e_state,
                      d.q_dump, 0);
        b.check_state(b.a_state_bad, t, "arbiter registered", b.afields, ASTATE_W, ac.s_e,
                      d.a_dump, 0);
        if (refresh_on)
            b.check_state(b.r_state_bad, t, "refresh registered", b.rfields, RSTATE_W, ac.r_e,
                          d.r_dump, 0);
        if (col("has_row")) {
            uint64_t s = d.biu_dump;
            auto take = [&](int bits) {
                const long v = long(s & ((uint64_t(1) << bits) - 1));
                s >>= bits;
                return v;
            };
            const long valid = take(1), kind = take(3), pos = take(3), len = take(3);
            const long ext = take(1), internal = take(1), latch = take(1), addr = take(20);
            const long wid = take(2), data = take(16);
            const long gap = take(1), fsince = take(3), io_tail = take(3), wl = take(3),
                       rlen = take(3);
            b.check(b.biu_state_bad, t, "biu.valid", col("valid"), valid);
            if (col("valid") && valid) {
                b.check(b.biu_state_bad, t, "biu.kind", col("skind"), kind);
                b.check(b.biu_state_bad, t, "biu.pos", col("pos"), pos);
                b.check(b.biu_state_bad, t, "biu.len", col("len"), len);
                b.check(b.biu_state_bad, t, "biu.ext", col("sext"), ext);
                b.check(b.biu_state_bad, t, "biu.internal", col("sint"), internal);
                b.check(b.biu_state_bad, t, "biu.latch", col("slatch"), latch);
                b.check(b.biu_state_bad, t, "biu.addr", col("saddr"), addr);
                b.check(b.biu_state_bad, t, "biu.width", col("swidth"), wid);
                b.check(b.biu_state_bad, t, "biu.data", col("sdata"), data);
            }
            b.check(b.biu_state_bad, t, "biu.gap", col("gap"), gap);
            b.check(b.biu_state_bad, t, "biu.fetch_since", col("sfsince"), fsince);
            b.check(b.biu_state_bad, t, "biu.io_tail", col("io_tail"), io_tail);
            b.check(b.biu_state_bad, t, "biu.wlatch", col("wl"), wl);
            b.check(b.biu_state_bad, t, "biu.refresh_len", col("rlen"), rlen);
            if (valid && pos == 0)
                std::printf("CYC %ld %ld %ld %ld %ld %ld\n", t, len, kind, addr, wid, data);
        }
    }
    for (auto& [n, k] : iter_hist)
        std::printf("ITER %d %ld\n", n, k);
    std::printf("SUMMARY clocks=%ld ops=%ld starts=%ld state_bad=%ld op_bad=%ld err_bad=%ld "
                "dcyc_bad=%ld q_state_bad=%ld q_rd_bad=%ld x_bad=%ld a_state_bad=%ld "
                "r_state_bad=%ld signal_bad=%ld biu_state_bad=%ld settle_bad=%ld opnd_bad=%ld "
                "iter_total=%ld iter_max=%ld\n",
                long(clocks.size()), nops_total, nstarts, b.state_bad, b.op_bad, b.err_bad,
                b.dcyc_bad, b.q_state_bad, b.q_rd_bad, b.x_bad, b.a_state_bad, b.r_state_bad,
                b.signal_bad,
                b.biu_state_bad, b.settle_bad, b.opnd_bad, iter_total, iter_max);
    return b.fails ? 1 : 0;
}
