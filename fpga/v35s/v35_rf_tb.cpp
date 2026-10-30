// Register file, EA adder and ALU bench (HDL plan, Phase D: D1, D2): v35_rf_tb (v35_eu_pkg's
// eu_decode, v35_operands, v35_execute, v35_deliver, v35_wdata) against the functional reference
// (validation/v35s/chains/funcref.py) or SingleStepTests (sst.py). Vectors: rtl_vectors.py
// (V35RF-2), one line per instruction start:
//
//   V <register file before: 14 values, v35_rf_t's fields> <code: 12 hex digits> <pc>
//     <code_org> <mutate> <the record: ea port sr sw count taken target> <bad> <next> <ncyc>
//     {<kind> <w2> <odd> <first> <last> <data>} x ncyc
//     <the register file after: 14 values> <trap>
//
// bad: the RTL does not build the form's function (obad, V35_EE_FUNC); nothing else is
// compared. A cycle's kind is V35_RK_* (1 read, 2 write, 3 I/O read, 4 I/O write); a read's data
// is the word the bus delivers, a write's the datum it must drive. next: the code offset after
// the instruction (a taken transfer's target; RET's, the stack read's). trap: a divide error
// (then only the trap is compared after the record).
//
//   Vv35_rf_tb VECTORS
//
// Output: "FAIL ..." for the first failures, "BAD i" for every failing vector, "SUMMARY
// vectors=N bad=N". Exit 0 when nothing failed.
#include "Vv35_rf_tb.h"
#include "verilated.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <type_traits>
#include <vector>

namespace {

const int RF_W[] = {16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 3};
const char* const RF_N[] = {"aw", "cw", "dw", "bw", "sp", "bp", "ix", "iy", "ps", "ss", "ds0",
                            "ds1", "psw", "pfx"};
constexpr int NRF = 14, RFW = 211, XW = 86;
// v35_opnd_t, MSB first: offset code ea port sr sw count taken target fmt tmpl
const int OPND_W[] = {16, 48, 20, 16, 16, 16, 9, 1, 16, 31, 8};
const char* const OPND_N[] = {"offset", "code", "ea", "port", "sr", "sw", "count", "taken",
                              "target", "fmt", "tmpl"};
constexpr int OPNDW = 197;
constexpr int RK_READ = 1, RK_WRITE = 2, RK_IO_READ = 3, RK_IO_WRITE = 4;

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
    for (int i = 0; i < n; ++i) {
        const int b = lsb + i;
        const uint32_t m = 1u << (b % 32);
        if ((v >> i) & 1)
            w[b / 32] |= m;
        else
            w[b / 32] &= ~m;
    }
}

template <typename A, typename B>
void copy_bits(A& dst, const B& src, int n) {
    for (int i = 0; i < n; i += 32)
        set_bits(dst, i, std::min(32, n - i), get_bits(src, i, std::min(32, n - i)));
}

struct Cyc {
    int kind = 0, w2 = 0, odd = 0, first = 0, last = 0;
    uint64_t data = 0;
};

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s VECTORS\n", argv[0]);
        return 2;
    }
    std::ifstream in(argv[1]);
    std::string format, tag;
    long n = 0;
    in >> format >> n;
    if (format != "V35RF-2") {
        std::fprintf(stderr, "not a V35RF-2 vector file\n");
        return 2;
    }
    VerilatedContext context;
    Vv35_rf_tb d{&context};
    long bad = 0, fails = 0;
    for (long i = 0; i < n; ++i) {
        std::vector<uint64_t> before(NRF), after(NRF), rec(7);
        std::string hex;
        uint64_t pc = 0, org = 0, mut = 0, xbad = 0, next = 0, trap = 0;
        long ncyc = 0;
        in >> tag;
        for (auto& x : before)
            in >> x;
        in >> hex >> pc >> org >> mut;
        for (auto& x : rec)
            in >> x;
        in >> xbad >> next >> ncyc;
        std::vector<Cyc> cyc(ncyc);
        for (auto& c : cyc)
            in >> c.kind >> c.w2 >> c.odd >> c.first >> c.last >> c.data;
        for (auto& x : after)
            in >> x;
        in >> trap;
        if (tag != "V" || !in) {
            std::fprintf(stderr, "bad vector %ld\n", i);
            return 2;
        }
        bool wrong = false;
        auto report = [&](const char* what, uint64_t m, uint64_t r) {
            wrong = true;
            if (++fails <= 20)
                std::printf("FAIL vector %ld code %s %s want=%llu rtl=%llu\n", i, hex.c_str(), what,
                            (unsigned long long)m, (unsigned long long)r);
        };
        int off = RFW;
        for (int k = 0; k < NRF; ++k) {
            off -= RF_W[k];
            set_bits(d.rf_in, off, RF_W[k], before[k]);
        }
        const uint64_t code = std::stoull(hex, nullptr, 16);
        d.code = code;
        d.pc = pc;
        d.code_org = org;
        d.mutate = mut;
        d.d_w2 = d.d_odd = d.d_io = d.d_last = 0;
        d.d_data = 0;
        d.w_kind = d.w_w2 = d.w_odd = d.w_first = d.w_last = 0;
        for (int k = 0; k < XW; k += 32)
            set_bits(d.x_in, k, std::min(32, XW - k), 0);
        d.eval();
        if (!d.ok)
            report("decode", 1, 0);
        if (uint64_t(d.obad) != xbad)
            report("function not built", xbad, d.obad);
        if (!xbad && d.ok) {
            // the record: ea port sr sw count taken target
            int at = OPNDW - OPND_W[0] - OPND_W[1];
            for (int k = 0; k < 7; ++k) {
                at -= OPND_W[k + 2];
                const uint64_t got = get_bits(d.opr, at, OPND_W[k + 2]);
                if (got != rec[k])
                    report(OPND_N[k + 2], rec[k], got);
            }
            const uint64_t taken = get_bits(d.opr, OPND_W[10] + OPND_W[9] + OPND_W[8], 1);
            const uint64_t target = get_bits(d.opr, OPND_W[10] + OPND_W[9], 16);
            const uint64_t count = get_bits(d.opr, OPND_W[10] + OPND_W[9] + 17, 9);
            const int len = d.len;
            const bool ret = (code >> 40) == 0xC3;
            // the start
            bool tr = d.s_trap;
            VlWide<7> rf;
            VlWide<3> x;
            copy_bits(rf, d.s_rf, RFW);
            copy_bits(x, d.s_x, XW);
            bool tgt_v = false;
            uint64_t tgt = 0;
            for (const auto& c : cyc) {
                copy_bits(d.rf_in, rf, RFW);
                copy_bits(d.x_in, x, XW);
                if (c.kind == RK_READ || c.kind == RK_IO_READ) {
                    d.d_w2 = c.w2;
                    d.d_odd = c.odd;
                    d.d_io = c.kind == RK_IO_READ;
                    d.d_last = c.last;
                    d.d_data = c.data;
                    d.d_count = count;
                    d.eval();
                    copy_bits(rf, d.d_rf, RFW);
                    copy_bits(x, d.d_x, XW);
                    tr = tr || d.d_trap;
                    if (d.d_tgt_v) {
                        tgt_v = true;
                        tgt = d.d_tgt;
                    }
                } else {
                    d.w_kind = c.kind;
                    d.w_w2 = c.w2;
                    d.w_odd = c.odd;
                    d.w_first = c.first;
                    d.w_last = c.last;
                    d.eval();
                    if (uint64_t(d.w_data) != c.data)
                        report("write datum", c.data, d.w_data);
                    copy_bits(x, d.w_x, XW);
                    d.w_kind = 0;
                }
            }
            if (uint64_t(tr) != trap)
                report("trap", trap, tr);
            if (!trap && !tr) {
                off = RFW;
                for (int k = 0; k < NRF; ++k) {
                    off -= RF_W[k];
                    const uint64_t got = get_bits(rf, off, RF_W[k]);
                    if (got != after[k])
                        report(RF_N[k], after[k], got);
                }
                if (ret && !tgt_v)
                    report("RET's target", 1, 0);
                const uint64_t got = ret ? tgt : taken ? target : (pc + len) & 0xFFFF;
                if (got != next)
                    report("next", next, got);
            }
        }
        if (wrong) {
            ++bad;
            std::printf("BAD %ld\n", i);
        }
    }
    std::printf("SUMMARY vectors=%ld bad=%ld\n", n, bad);
    return bad ? 1 : 0;
}
