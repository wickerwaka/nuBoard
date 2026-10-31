// Decoder and EU bench (HDL plan, C3): feeds v35_eu the frozen model's EU vectors and checks
// every model clock. Vectors: validation/v35s/chains/rtl_vectors.py (V35EU-4: the state at
// the end of clock -1 with the register file's presets, the code, (D2) the memory's image, the
// operand record of every instruction start and the register file before it (D1: the EU
// computes both, the bench compares at every start; the code window at code_addr is served from
// the code; D2: the register file is the functional reference's, funcref.py), and per model
// clock the delivery, the bus unit's views, the queue's state before each of the EU's ops and
// their reads, the arbiter's touches, and the state after each phase (its functional fields f_
// and x_ not compared: the register file changes where the RTL applies the data), then the
// EU's cycles with the reference's datum, checked against the EU's at each issue. (D2) The
// bench's memory is the image written by the EU's own writes; a read delivers its aligned word
// (alone: to the EU's c_data; joint: into the bus unit), an I/O read 0000h.
//
//   Vv35_eu_tb EU_VECTORS                         the EU alone (--eu)
//   Vv35_eu_tb EU_VECTORS QUEUE_VECTORS BIU_VECTORS   with the RTL queue and bus unit (--joint3)
//
// Alone, the EU's views of the queue and the bus unit are the model's: the queue's state
// before the EU's i-th op of a phase is the recording's, and so is the i-th op's read; the
// EU's ops are checked against the model's (code, arguments, the decoder's snapshot).
// Joint, the queue (v35_queue.sv with JSLOT stages) runs the clock's ops as the EU emits them
// (T and L, then the arbiter's scripted X ops from the queue vectors, then P), the EU's views
// are the RTL queue's state before each op and its reads, the bus unit (v35_biu.sv) runs the
// queue's fetches (gated by the queue's own wants_fetch, as C2's joint bench) and the EU's data
// cycles (at the clocks the scripted arbiter issues them, the EU's kind, address and width),
// the other cycles scripted; the bench evaluates until the EU's ops settle. The queue is
// checked as in C2 (its state after C, every op and the end), the bus unit as in C1.
//
// Output: "FAIL ..." for the first failures, "CYC start length kind addr width data" for each
// cycle the bus unit started (joint), "DCYC t kind addr width" for each data cycle the EU
// issued, "SUMMARY clocks=N ops=N state_bad=N op_bad=N err_bad=N dcyc_bad=N q_state_bad=N
// q_rd_bad=N gate_bad=N signal_bad=N biu_state_bad=N settle_bad=N". Exit 0 when nothing failed.
#include "Vv35_eu_tb.h"
#include "verilated.h"

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

constexpr int NQ = 16, NXOP = 6, JSLOT = 40, STATE_W = 1021, QSTATE_W = 197;
constexpr int OPW = 33, QVW = 52, BVW = 20, NBV = 11, OPNDW = 212, RFW = 211;
constexpr int K_FETCH = 1, K_READ = 2, K_WRITE = 3, K_IO_READ = 4, K_REFRESH = 6;
constexpr int BW_WORD = 0, BW_HI = 2;
constexpr long SFR_PAGE = 0xFFF00;
constexpr int IO_WORD = 0x0000;     // (D2) the board's I/O reads (funcref.IO_WORD)
constexpr int OP_WANT = 16, OP_ISSUE = 23;
constexpr int X_ISSUE = 1, X_NOWRITE = 2;

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
    Vals view;              // the queue's state before it (QVIEW)
};

struct Clock {
    long t = 0;
    int c_eu = 0, c_read = 0, fetch_done = 0, x_valid = 0, x_kind = 0, x_eu = 0, x_len = 0;
    int counts_t[3] = {0, 0, 0}, counts_p[3] = {0, 0, 0};
    int latch_in = 0, ntl = 0, n_t = 0, nx = 0, np = 0, nxops = 0;
    Vals bus_t, bus_p;
    Vals s_c, s_t, s_l, s_x, s_p, s_e;
    std::vector<Op> tl, p;
    Vals v_tl, v_p;         // the queue's state after the phase's last op
    std::vector<std::pair<int, int>> xops;
};

struct OpRec {
    Vals v;                 // offset, code (48 bits), ea, port, sr, sw, count, taken, target, fmt, tmpl
    Vals rf;                // (D2) the register file before the start (v35_rf_t)
    Vals str;               // (E3) a string form: 1, its elements, cond (the walk's)
};

// (D1) the operand record (v35_opnd_t, MSB first) and the register file (v35_rf_t)
// (WP79) fmt 33 bits, tmpl 9, and a bit field's cost (bfc)
const int OPND_W[] = {16, 48, 20, 16, 16, 16, 9, 1, 16, 33, 9, 12};
const char* const OPND_N[] = {"offset", "code", "ea", "port", "sr", "sw", "count", "taken",
                              "target", "fmt", "tmpl", "bfc"};
constexpr int NOPND = 12;
const int RF_W[] = {16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 3};
const char* const RF_N[] = {"aw", "cw", "dw", "bw", "sp", "bp", "ix", "iy", "ps", "ss", "ds0",
                            "ds1", "psw", "pfx"};
constexpr int NRF = 14;
const int BV_W[] = {3, 3, 3, 1, 1, 1, 1, 1, 4, 1, 1};   // (WP77) run

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

// pack values (MSB first, widths) into w at lsb
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

struct Bench {
    VerilatedContext context;
    Vv35_eu_tb dut{&context};
    std::vector<Field> fields, qfields, qview_fields;
    std::vector<int> qview_widths;
    std::map<std::string, int> qfield_at;   // the queue's state: field -> lsb
    long state_bad = 0, op_bad = 0, err_bad = 0, dcyc_bad = 0, q_state_bad = 0, q_rd_bad = 0,
         gate_bad = 0, signal_bad = 0, biu_state_bad = 0, settle_bad = 0, opnd_bad = 0,
         fails = 0;

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
    // the queue's state (its v35_qstate_t, from the RTL queue) as the EU's view
    template <typename W>
    Vals qview_of(const W& w, int lsb) {
        Vals v;
        for (auto& f : qview_fields)
            v.push_back(get_bits(w, lsb + qfield_at[f.name], f.width));
        return v;
    }
};

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

// the queue vectors (V35QUEUE-1), for the joint bench
struct QClock {
    long t;
    int k[11];
    Vals c_state, e_state;
    std::vector<std::pair<std::vector<long>, Vals>> ops;   // (code a b val snap rd), state after
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

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2 && argc != 4) {
        std::fprintf(stderr, "usage: %s EU_VECTORS [QUEUE_VECTORS BIU_VECTORS]\n", argv[0]);
        return 2;
    }
    const bool joint = argc == 4;
    Bench b;
    std::ifstream in(argv[1]);
    std::string format, id, line;
    long nclocks = 0, nq = 0, nxop = 0, nopnd = 0, base = 0, org = 0;
    in >> format >> id >> nclocks >> nq >> nxop >> nopnd >> base >> org;
    if (format != "V35EU-4" || nq != NQ || nxop != NXOP) {
        std::fprintf(stderr, "not a V35EU-4 vector file for %d ops, %d touches\n", NQ, NXOP);
        return 2;
    }
    std::getline(in, line);
    std::getline(in, line);
    int width = 0;
    b.fields = parse_fields(line, width);
    for (auto& f : b.fields)
        f.func = f.name.rfind("f_", 0) == 0 || f.name.rfind("x_", 0) == 0;
    if (width != STATE_W) {
        std::fprintf(stderr, "bad field line (%d bits)\n", width);
        return 2;
    }
    std::getline(in, line);
    b.qview_fields = parse_fields(line, width);
    if (width != QVW) {
        std::fprintf(stderr, "bad queue view line (%d bits)\n", width);
        return 2;
    }
    for (auto& f : b.qview_fields)
        b.qview_widths.push_back(f.width);
    const size_t nf = b.fields.size(), nqv = b.qview_fields.size();
    int x_sn_lsb = -1, x_sc_lsb = -1;           // (E3) the string form's elements and cond
    {
        int off = STATE_W;
        for (const auto& f : b.fields) {
            off -= f.width;
            if (f.name == "x_sn")
                x_sn_lsb = off;
            if (f.name == "x_sc")
                x_sc_lsb = off;
        }
        if (x_sn_lsb < 0 || x_sc_lsb < 0) {
            std::fprintf(stderr, "no x_sn / x_sc field\n");
            return 2;
        }
    }
    Vals init;
    if (!read_vals(in, "I", nf, init)) {
        std::fprintf(stderr, "no init line\n");
        return 2;
    }
    // (D1) the code at the base: the code window's bytes
    std::vector<int> code;
    {
        std::string tag, chex;
        in >> tag >> chex;
        if (tag != "C") {
            std::fprintf(stderr, "no code line\n");
            return 2;
        }
        code.resize(chex.size() / 2);
        for (size_t i = 0; i < code.size(); ++i)
            code[i] = std::stoi(chex.substr(2 * i, 2), nullptr, 16);
    }
    // (D2) the memory: 90h but for the functional reference's image runs; the EU's writes go
    // into it, its reads come from it
    std::vector<uint8_t> memory(1 << 20, 0x90);
    {
        std::string tag, mh;
        long nrun = 0, a = 0;
        in >> tag >> nrun;
        if (tag != "N") {
            std::fprintf(stderr, "no memory line\n");
            return 2;
        }
        for (long r = 0; r < nrun; ++r) {
            in >> a >> mh;
            for (size_t i = 0; i < mh.size() / 2; ++i)
                memory[(a + long(i)) & 0xFFFFF] = std::stoi(mh.substr(2 * i, 2), nullptr, 16);
        }
    }
    std::vector<OpRec> opnds(nopnd);
    for (auto& o : opnds) {
        std::string tag, hex;
        long offset;
        in >> tag >> offset >> hex;
        if (tag != "P") {
            std::fprintf(stderr, "bad operand line\n");
            return 2;
        }
        o.v.push_back(offset);
        o.v.push_back(std::stoull(hex, nullptr, 16));
        for (int k = 0; k < NOPND - 2; ++k) {
            uint64_t x;
            in >> x;
            o.v.push_back(x);
        }
        o.rf.resize(NRF);
        for (auto& x : o.rf)
            in >> x;
        o.str.resize(3);                        // (E3) a string form: 1, its elements, cond
        for (auto& x : o.str)
            in >> x;
    }
    std::vector<Clock> clocks(nclocks);
    auto read_op = [&](Op& o) {
        std::string tag;
        in >> tag >> o.code >> o.a >> o.b >> o.val >> o.snap >> o.rd;
        o.view.resize(nqv);
        for (auto& x : o.view)
            in >> x;
        return tag == "O" && bool(in);
    };
    for (auto& c : clocks) {
        std::string tag;
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
        c.bus_t.assign(bv.begin(), bv.begin() + NBV);
        c.bus_p.assign(bv.begin() + NBV, bv.end());
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
    // the model's EU cycles: start -> (kind, addr, width, (D2) the functional reference's datum)
    std::map<long, std::vector<long>> dcyc;
    {
        std::string tag;
        while (in >> tag) {
            if (tag != "D")
                break;
            long s, k, a, w, dd;
            in >> s >> k >> a >> w >> dd;
            dcyc[s] = {k, a, w, dd};
        }
    }

    // the joint bench's queue and bus-unit vectors
    std::vector<QClock> qclocks;
    std::vector<std::vector<long>> brows;
    std::vector<int> mem;
    long mem_base = 0, q_init_count = 0, q_init_faddr = 0;
    unsigned long long q_init_data = 0;
    std::string bwtc = "0", brfm = "0";
    if (joint) {
        std::ifstream qin(argv[2]);
        std::string qformat, qid, tag, hex;
        long qn = 0, qslot = 0;
        qin >> qformat >> qid >> qn >> qslot >> q_init_count >> q_init_data >> q_init_faddr;
        if (qformat != "V35QUEUE-1" || qid != id || qslot != JSLOT || qn != nclocks) {
            std::fprintf(stderr, "not the run's V35QUEUE-1 vector file for %d slots\n", JSLOT);
            return 2;
        }
        qin >> tag >> mem_base >> hex;
        mem.resize(hex.size() / 2);
        for (size_t i = 0; i < mem.size(); ++i)
            mem[i] = std::stoi(hex.substr(2 * i, 2), nullptr, 16);
        std::getline(qin, line);
        std::getline(qin, line);
        b.qfields = parse_fields(line, width);
        if (width != QSTATE_W) {
            std::fprintf(stderr, "bad queue field line (%d bits)\n", width);
            return 2;
        }
        int off = QSTATE_W;
        for (auto& f : b.qfields) {
            off -= f.width;
            b.qfield_at[f.name] = off;
        }
        const size_t nqf = b.qfields.size();
        qclocks.resize(qn);
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
        std::ifstream bin(argv[3]);
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
    for (size_t i = 0; i < mem.size(); ++i)    // the queue's image (within the memory's)
        memory[(mem_base + long(i)) & 0xFFFFF] = uint8_t(mem[i]);
    auto byte_at = [&](long a) { return int(memory[a & 0xFFFFF]); };
    auto word_at = [&](long a) { return byte_at(a) | (byte_at(a + 1) << 8); };
    // (D2) the word the bus delivers: an EU read's the aligned memory word, the I/O word; a
    // fetch's the queue's (from its address, odd after a transfer to an odd target)
    auto bus_word = [&](long kind, long a) {
        return kind == K_IO_READ ? IO_WORD : kind == K_FETCH ? word_at(a) : word_at(a & ~1L);
    };
    // (D2) a write the EU issued, on its lanes (the on-chip SFR page is not memory)
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
    std::vector<std::pair<long, long>> eu_cycles;   // (D2) alone: the EU's cycles on the bus
    size_t eu_next = 0;

    Verilated::commandArgs(argc, argv);
    auto& d = b.dut;
    {
        std::vector<int> fw;
        for (auto& f : b.fields)
            fw.push_back(f.width);
        pack(d.init_state, 0, init, fw);
    }
    // (D1) the code window: twelve bytes from the EU's code_addr, the first in [95:88]
    auto code_window = [&](long a) {
        for (int i = 0; i < 12; ++i) {
            const long k = a + i - base;
            const int v = (k >= 0 && k < long(code.size())) ? code[k] : 0x90;
            set_bits(d.code_win, 88 - 8 * i, 8, uint64_t(v));
        }
    };
    d.mutate = 0;
    d.q_joint = joint;
    d.code_org = org;
    d.init_count = q_init_count;
    d.init_data = q_init_data;
    d.init_fetch_addr = q_init_faddr;
    d.wtc = std::stoul(bwtc, nullptr, 16);
    d.rfm = std::stoul(brfm, nullptr, 16);
    d.reset_n = 0;
    for (int i = 0; i < 4; ++i)
        b.tick(false, false);
    d.reset_n = 1;

    long nstarts = 0, nops_total = 0;
    bool eu_cycle_on = false;             // joint: the cycle on the bus is the EU's
    long eu_cycle_end = -1;
    for (const auto& c : clocks) {
        const long t = c.t;
        // (D1) the code window at the registered pc
        d.eval();
        code_window(d.code_addr);
        for (int i = 0; i < NXOP; ++i) {
            const uint64_t w = i < c.nxops ? (uint64_t(c.xops[i].first) << 8) |
                                                 uint64_t(c.xops[i].second & 0xFF)
                                           : 0;
            set_bits(d.xop, 12 * i, 12, w);
        }
        for (int i = 0; i < 3; ++i) {
            set_bits(d.counts_t, 7 * i, 7, c.counts_t[i]);
            set_bits(d.counts_p, 7 * i, 7, c.counts_p[i]);
        }
        d.x_valid = c.x_valid;
        d.x_kind = c.x_kind;
        d.x_eu = c.x_eu;
        d.q_latch_in = c.latch_in;
        const std::vector<long>* br = nullptr;
        const QClock* qc = joint ? &qclocks[t] : nullptr;
        int eu_ntl = 0, eu_np = 0;
        if (!joint) {
            d.c_eu = c.c_eu;
            d.c_read = c.c_read;
            d.c_data_in = 0;
            if (c.c_eu && eu_next < eu_cycles.size()) {   // (D2) the delivered word
                const auto& ec = eu_cycles[eu_next++];
                if (c.c_read)
                    d.c_data_in = bus_word(ec.first, ec.second);
            }
            d.fetch_done = c.fetch_done;
            {
                Vals v(c.bus_t.begin(), c.bus_t.end());
                d.bus_t = 0;
                d.bus_p = 0;
                uint64_t w = 0;
                int off = BVW;
                for (int k = 0; k < NBV; ++k) {
                    off -= BV_W[k];
                    w |= uint64_t(c.bus_t[k]) << off;
                }
                d.bus_t = w;
                w = 0;
                off = BVW;
                for (int k = 0; k < NBV; ++k) {
                    off -= BV_W[k];
                    w |= uint64_t(c.bus_p[k]) << off;
                }
                d.bus_p = w;
            }
            for (int i = 0; i <= NQ; ++i) {
                const Vals& v = i < c.ntl ? c.tl[i].view : c.v_tl;
                pack(d.qv_tl, QVW * i, v, b.qview_widths);
                const Vals& u = i < c.np ? c.p[i].view : c.v_p;
                pack(d.qv_p, QVW * i, u, b.qview_widths);
            }
            for (int i = 0; i < NQ; ++i) {
                set_bits(d.rd_tl, 8 * i, 8, i < c.ntl && c.tl[i].rd >= 0 ? c.tl[i].rd : 0);
                set_bits(d.rd_p, 8 * i, 8, i < c.np && c.p[i].rd >= 0 ? c.p[i].rd : 0);
            }
            d.eval();
            eu_ntl = d.n_tl;
            eu_np = d.n_p;
        } else {
            if (t >= long(brows.size()) || brows[t][bcol("t")] != t) {
                std::fprintf(stderr, "bus unit vectors out of step at %ld\n", t);
                return 2;
            }
            br = &brows[t];
            const auto& r = *br;
            const auto col = [&](const char* n) { return r[bcol(n)]; };
            // the scripted cycles: neither the queue's fetches nor the EU's data cycles
            const bool fetch = col("start") && col("kind") == K_FETCH;
            bool eu_issue = false;
            for (auto& x : c.xops)
                eu_issue = eu_issue || x.first == X_ISSUE;
            d.req_start = col("start") && !fetch && !eu_issue;
            d.req_kind = col("kind");
            d.req_addr = col("addr");
            d.req_width = col("width");
            d.req_data = col("data");
            d.req_ext = col("ext");
            d.req_latch = col("latch");
            d.rfm_load = col("rfm_load");
            d.rfm_value = col("rfm_value");
            d.data_gate = eu_issue;             // (D2) its datum the EU's (x_data)
            d.fetch_gate = 0;
            // the EU's read deliveries: the bus unit's delivery of the EU's own cycle
            d.eval();
            const bool deliver = d.done != 0;
            d.c_eu = deliver && eu_cycle_on && eu_cycle_end == t - 1;
            d.c_read = d.c_eu && (d.done_kind == K_READ || d.done_kind == K_IO_READ);
            // (D2) a fetch's and the EU's read's word from the memory, the rest scripted
            d.data_in = (d.done && (d.done_kind == K_FETCH || d.c_read)) ?
                        bus_word(d.done_kind, d.done_addr) : col("data_in");
            // settle: the EU's ops into the queue's chain, the queue's states back
            uint64_t last_sig = ~uint64_t(0);
            bool settled = false;
            bool ungated = false;
            for (int it = 0; it < 64; ++it) {
                ungated = false;
                d.fetch_done = d.q_fetch_done;
                uint64_t bt = 0, bp = 0;
                {
                    const uint64_t f3 = d.fetch_len == 3;
                    const uint64_t vt[NBV] = {d.cur_kind, d.cur_pos, d.cur_len, d.free,
                                              d.fetch_inflight, d.in_wait, d.fetch_end_prev,
                                              d.wlatch_busy, d.fetch_since, f3,
                                              uint64_t(c.bus_t[10])};   // (WP77) run: scripted
                    const uint64_t vp[NBV] = {d.cur_kind_x, d.cur_pos_x, d.cur_len_x, d.free_x,
                                              d.fetch_inflight_x, d.in_wait_x, d.fetch_end_prev_x,
                                              d.wlatch_busy_x, d.fetch_since_x, f3,
                                              uint64_t(c.bus_p[10])};
                    int off = BVW;
                    for (int k = 0; k < NBV; ++k) {
                        off -= BV_W[k];
                        bt |= vt[k] << off;
                        bp |= vp[k] << off;
                    }
                }
                d.bus_t = bt;
                d.bus_p = bp;
                eu_ntl = d.n_tl;
                eu_np = d.n_p;
                // the chain: T/L ops, the scripted X ops, P ops
                int slot = 0;
                std::vector<int> x_at;
                for (int i = 0; i < eu_ntl && slot < JSLOT; ++i, ++slot)
                    set_bits(d.qops, OPW * slot, OPW, get_bits(d.op_tl, OPW * i, OPW));
                for (int i = 0; i < c.nx && slot < JSLOT; ++i, ++slot) {
                    const auto& o = qc->ops[c.ntl + i].first;
                    const uint64_t w = (uint64_t(o[0]) << 27) | (uint64_t(o[1]) << 26) |
                                       (uint64_t(o[2]) << 25) | (uint64_t(o[3] & 0xFFFFF) << 5) |
                                       uint64_t(o[4]);
                    set_bits(d.qops, OPW * slot, OPW, w);
                    x_at.push_back(slot);
                }
                const int p0 = slot;
                for (int i = 0; i < eu_np && slot < JSLOT; ++i, ++slot)
                    set_bits(d.qops, OPW * slot, OPW, get_bits(d.op_p, OPW * i, OPW));
                for (; slot < JSLOT; ++slot)
                    set_bits(d.qops, OPW * slot, OPW, 0);
                d.eval();
                // the fetch's gate: the queue's last wants_fetch before its issue (C2)
                int gate = 0;
                for (int i = 0; i < c.nx; ++i) {
                    const auto& o = qc->ops[c.ntl + i].first;
                    if (o[0] != OP_ISSUE)
                        continue;
                    if (o[2]) {
                        gate = 1;
                    } else {
                        for (int k = i - 1; k >= 0; --k)
                            if (qc->ops[c.ntl + k].first[0] == OP_WANT) {
                                gate = int(get_bits(d.q_rd, 8 * x_at[k], 8) & 1);
                                break;
                            }
                        ungated = ungated || !gate;
                    }
                }
                d.fetch_gate = gate;
                d.eval();
                d.fetch_data = word_at(d.fetch_issue_addr);
                d.wlatch_fill = d.wl_fill_t || d.wl_fill_x || d.wl_fill_p;
                d.eval();
                // the queue's states before each op as the EU's views
                for (int i = 0; i <= NQ; ++i) {
                    const int s = i < eu_ntl ? i : eu_ntl;
                    Vals v = s == 0 ? b.qview_of(d.q_state_c, 0)
                                    : b.qview_of(d.q_state_op, QSTATE_W * (s - 1));
                    pack(d.qv_tl, QVW * i, v, b.qview_widths);
                    const int u = p0 + (i < eu_np ? i : eu_np);
                    Vals w = u == 0 ? b.qview_of(d.q_state_c, 0)
                                    : b.qview_of(d.q_state_op, QSTATE_W * (u - 1));
                    pack(d.qv_p, QVW * i, w, b.qview_widths);
                }
                for (int i = 0; i < NQ; ++i) {
                    set_bits(d.rd_tl, 8 * i, 8, i < eu_ntl ? get_bits(d.q_rd, 8 * i, 8) : 0);
                    set_bits(d.rd_p, 8 * i, 8,
                             i < eu_np && p0 + i < JSLOT ? get_bits(d.q_rd, 8 * (p0 + i), 8) : 0);
                }
                d.eval();
                // the signature of what the EU did
                uint64_t sig = uint64_t(d.n_tl) | (uint64_t(d.n_p) << 8) |
                               (uint64_t(d.x_cyc) << 16) | (uint64_t(d.wl_fill_t) << 17) |
                               (uint64_t(gate) << 18);
                for (int i = 0; i < NQ; ++i)
                    sig = sig * 1000003u ^ get_bits(d.op_tl, OPW * i, OPW) ^
                          (get_bits(d.op_p, OPW * i, OPW) << 1);
                for (int k = 0; k < STATE_W; k += 64)
                    sig = sig * 1000003u ^ get_bits(d.state_e, k, std::min(64, STATE_W - k));
                if (sig == last_sig && d.n_tl == eu_ntl && d.n_p == eu_np) {
                    settled = true;
                    break;
                }
                last_sig = sig;
            }
            if (!settled)
                b.fail(b.settle_bad, t, "the clock did not settle", 1, 0);
            if (ungated)
                b.fail(b.gate_bad, t, "fetch issued without the queue's request", 1, 0);
            if (eu_ntl + c.nx + eu_np > JSLOT)
                b.fail(b.settle_bad, t, "more queue ops than the chain holds", JSLOT,
                       eu_ntl + c.nx + eu_np);
            // the bus unit, as C1
            b.check(b.signal_bad, t, "busy", col("busy"), d.busy);
            b.check(b.signal_bad, t, "free", col("free"), d.free);
            b.check(b.signal_bad, t, "fetch_inflight", col("finf"), d.fetch_inflight);
            b.check(b.signal_bad, t, "done", col("done"), d.done);
            if (col("has_row")) {
                b.check(b.signal_bad, t, "busy_x", col("busy_x"), d.busy_x);
                b.check(b.signal_bad, t, "free_x", col("free_x"), d.free_x);
                b.check(b.signal_bad, t, "wlatch_busy_x", col("wl_busy_x"), d.wlatch_busy_x);
            }
            if (d.x_cyc && d.data_gate) {
                eu_cycle_on = true;
                eu_cycle_end = t + int(d.cur_len_x) - 1;
            }
        }
        nops_total += c.ntl + c.np;

        // the middle of the CPU state (the bus unit latches read data), then the checks
        b.tick(false, true);
        b.check_state(b.state_bad, t, "after C", b.fields, STATE_W, c.s_c, d.state_c, 0);
        b.check_state(b.state_bad, t, "after T", b.fields, STATE_W, c.s_t, d.state_t, 0);
        b.check_state(b.state_bad, t, "after L", b.fields, STATE_W, c.s_l, d.state_l, 0);
        b.check_state(b.state_bad, t, "after X", b.fields, STATE_W, c.s_x, d.state_x, 0);
        b.check_state(b.state_bad, t, "after P", b.fields, STATE_W, c.s_p, d.state_p, 0);
        b.check_state(b.state_bad, t, "end", b.fields, STATE_W, c.s_e, d.state_e, 0);
        b.check(b.op_bad, t, "T/L ops", c.ntl, d.n_tl);
        b.check(b.op_bad, t, "T ops", c.n_t, d.n_t);
        b.check(b.op_bad, t, "P ops", c.np, d.n_p);
        auto check_ops = [&](const std::vector<Op>& ops, int n, const char* ph, const auto& arr) {
            for (int i = 0; i < int(ops.size()) && i < n; ++i) {
                const uint64_t w = get_bits(arr, OPW * i, OPW);
                const auto& o = ops[i];
                const uint64_t want = (uint64_t(o.code) << 27) | (uint64_t(o.a) << 26) |
                                      (uint64_t(o.b) << 25) | (uint64_t(o.val & 0xFFFFF) << 5) |
                                      uint64_t(o.snap);
                if (w != want) {
                    char where[64];
                    std::snprintf(where, sizeof where, "%s op %d (code %d) word", ph, i, o.code);
                    b.fail(b.op_bad, t, where, long(want), long(w));
                }
            }
        };
        check_ops(c.tl, d.n_tl, "T/L", d.op_tl);
        check_ops(c.p, d.n_p, "P", d.op_p);
        b.check(b.err_bad, t, "EU err_code", 0, d.err_code);
        // the EU's data cycle on the arbiter's issue
        for (auto& x : c.xops) {
            if (x.first != X_ISSUE)
                continue;
            auto it = dcyc.find(t);
            if (it == dcyc.end()) {
                b.fail(b.dcyc_bad, t, "an EU issue without the model's cycle", 0, 1);
            } else {
                b.check(b.dcyc_bad, t, "data cycle kind", it->second[0], d.x_cyc_kind);
                b.check(b.dcyc_bad, t, "data cycle addr", it->second[1], d.x_cyc_addr);
                b.check(b.dcyc_bad, t, "data cycle width", it->second[2], d.x_cyc_width);
            }
            // (D2) its datum: the EU's, the functional reference's; a write goes to memory
            if (it != dcyc.end())
                b.check(b.dcyc_bad, t, "data cycle datum", it->second[3], d.x_data);
            if (d.x_cyc_kind == K_WRITE)
                store(d.x_cyc_addr, d.x_cyc_width, d.x_data);
            eu_cycles.push_back({d.x_cyc_kind, d.x_cyc_addr});
            std::printf("DCYC %ld %d %d %d\n", t, int(d.x_cyc_kind), int(d.x_cyc_addr),
                        int(d.x_cyc_width));
            break;
        }
        if (joint) {
            // the queue, as C2: after C, each op, the end
            b.check_state(b.q_state_bad, t, "queue after C", b.qfields, QSTATE_W, qc->c_state,
                          d.q_state_c, 0);
            for (int i = 0; i < int(qc->ops.size()) && i < JSLOT; ++i) {
                char where[64];
                std::snprintf(where, sizeof where, "queue op %d (code %ld)", i, qc->ops[i].first[0]);
                if (qc->ops[i].first[5] >= 0)
                    b.check(b.q_rd_bad, t, std::string(where) + " rd", qc->ops[i].first[5],
                            long(get_bits(d.q_rd, 8 * i, 8)));
                b.check_state(b.q_state_bad, t, where, b.qfields, QSTATE_W, qc->ops[i].second,
                              d.q_state_op, QSTATE_W * i);
            }
            b.check_state(b.q_state_bad, t, "queue end", b.qfields, QSTATE_W, qc->e_state,
                          d.q_state_e, 0);
        }
        // (D1) the operand record of each start and (D2) the register file before it
        for (int j = 0; j < int(d.n_start) && j < 2; ++j) {
            const long i = nstarts + j;
            char where[64];
            if (i >= long(opnds.size())) {
                b.fail(b.opnd_bad, t, "a start past the model's", long(opnds.size()), i);
                continue;
            }
            std::snprintf(where, sizeof where, "start %ld record", i);
            bool bad = j == 0 ? b.check_packed(t, where, OPND_N, OPND_W, NOPND, opnds[i].v, d.opr_a)
                              : b.check_packed(t, where, OPND_N, OPND_W, NOPND, opnds[i].v, d.opr_b);
            std::snprintf(where, sizeof where, "start %ld registers", i);
            bad = (j == 0 ? b.check_packed(t, where, RF_N, RF_W, NRF, opnds[i].rf, d.rfx_a)
                          : b.check_packed(t, where, RF_N, RF_W, NRF, opnds[i].rf, d.rfx_b)) || bad;
            // (E3) the string form before it: its elements and cond against the walk's
            if (j == 0 && i >= 1 && opnds[i - 1].str[0]) {
                std::snprintf(where, sizeof where, "start %ld string", i - 1);
                b.check(b.opnd_bad, t, std::string(where) + " elements",
                        long(opnds[i - 1].str[1]), long(get_bits(d.state_c, x_sn_lsb, 16)));
                b.check(b.opnd_bad, t, std::string(where) + " cond", long(opnds[i - 1].str[2]),
                        long(get_bits(d.state_c, x_sc_lsb, 1)));
            }
            if (bad)
                ++b.opnd_bad;
        }
        // the end of the model clock
        nstarts += d.n_start;
        b.tick(true, false);
        b.check(b.err_bad, t, "EU error", 0, d.eu_error);
        b.check_state(b.state_bad, t, "registered", b.fields, STATE_W, c.s_e, d.state_dump, 0);
        if (joint) {
            const auto& r = *br;
            const auto col = [&](const char* n) { return r[bcol(n)]; };
            b.check(b.signal_bad, t, "queue error", 0, d.q_error);
            b.check(b.signal_bad, t, "bus unit error", 0, d.biu_error);
            if (col("has_row")) {
                const auto& sw_ = d.biu_state;        // (WP75) 65 bits: fetch_since is 4
                int s_at = 0;
                auto take = [&](int bits) {
                    long v = 0;
                    for (int i = 0; i < bits; ++i, ++s_at)
                        v |= long((sw_[s_at / 32] >> (s_at % 32)) & 1u) << i;
                    return v;
                };
                const long valid = take(1), kind = take(3), pos = take(3), len = take(3);
                const long ext = take(1), internal = take(1), latch = take(1), addr = take(20);
                const long width = take(2), data = take(16);
                const long gap = take(1), fsince = take(4), io_tail = take(3), wl = take(3),
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
    std::printf("SUMMARY clocks=%ld ops=%ld state_bad=%ld op_bad=%ld err_bad=%ld dcyc_bad=%ld "
                "q_state_bad=%ld q_rd_bad=%ld gate_bad=%ld signal_bad=%ld biu_state_bad=%ld "
                "settle_bad=%ld opnd_bad=%ld\n",
                long(clocks.size()), nops_total, b.state_bad, b.op_bad, b.err_bad, b.dcyc_bad,
                b.q_state_bad, b.q_rd_bad, b.gate_bad, b.signal_bad, b.biu_state_bad,
                b.settle_bad, b.opnd_bad);
    return b.fails ? 1 : 0;
}
