// Register file and EA adder bench (HDL plan, Phase D, D1): v35_rf_tb (v35_eu_pkg's eu_decode,
// v35_operands, v35_execute) against the frozen model's templates.decode and templates.execute.
// Vectors: validation/v35s/chains/rtl_vectors.py regfile_vectors (V35RF-1), one line per case:
//
//   V <register file before: 15 values, v35_rf_t's fields> <code: 12 hex digits> <pc> <mutate>
//     <the model's: ea port sr sw count taken target bad> <the register file after: 15 values>
//
// bad: the model cannot give the record (BE/BNE with Z unknown, RET without its return
// address); the RTL must say so too (obad) and the rest is not compared.
//
//   Vv35_rf_tb VECTORS
//
// Output: "FAIL ..." for the first failures, "SUMMARY vectors=N bad=N". Exit 0 when nothing failed.
#include "Vv35_rf_tb.h"
#include "verilated.h"

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <type_traits>
#include <vector>

namespace {

const int RF_W[] = {16, 16, 16, 16, 16, 16, 16, 16, 16, 1, 1, 1, 16, 16, 1};
const char* const RF_N[] = {"aw", "cw", "dw", "bw", "sp", "bp", "ix", "iy", "ds1", "z_v", "z",
                            "ret_v", "ret_sp", "ret_pc", "pfx"};
constexpr int NRF = 15, RFW = 180;
// v35_opnd_t, MSB first: offset code ea port sr sw count taken target fmt tmpl
const int OPND_W[] = {16, 48, 20, 16, 16, 16, 9, 1, 16, 31, 8};
const char* const OPND_N[] = {"offset", "code", "ea", "port", "sr", "sw", "count", "taken",
                              "target", "fmt", "tmpl"};
constexpr int NOPND = 11, OPNDW = 197;

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
    if (format != "V35RF-1") {
        std::fprintf(stderr, "not a V35RF-1 vector file\n");
        return 2;
    }
    VerilatedContext context;
    Vv35_rf_tb d{&context};
    long bad = 0, fails = 0;
    for (long i = 0; i < n; ++i) {
        std::vector<uint64_t> before(NRF), after(NRF), want(8);
        std::string hex;
        uint64_t pc = 0, mut = 0;
        in >> tag;
        for (auto& x : before)
            in >> x;
        in >> hex >> pc >> mut;
        for (auto& x : want)
            in >> x;
        for (auto& x : after)
            in >> x;
        if (tag != "V" || !in) {
            std::fprintf(stderr, "bad vector %ld\n", i);
            return 2;
        }
        int off = RFW;
        for (int k = 0; k < NRF; ++k) {
            off -= RF_W[k];
            set_bits(d.rf_in, off, RF_W[k], before[k]);
        }
        const uint64_t code = std::stoull(hex, nullptr, 16);
        d.code = code;
        d.pc = pc;
        d.mutate = mut;
        d.eval();
        bool wrong = !d.ok;
        auto report = [&](const char* what, uint64_t m, uint64_t r) {
            wrong = true;
            if (++fails <= 20)
                std::printf("FAIL vector %ld code %s %s model=%llu rtl=%llu\n", i, hex.c_str(),
                            what, (unsigned long long)m, (unsigned long long)r);
        };
        if (!d.ok)
            report("decode", 1, 0);
        // the record: offset, code, then ea port sr sw count taken target
        int at = OPNDW;
        for (int k = 0; k < 9; ++k) {
            at -= OPND_W[k];
            const uint64_t got = get_bits(d.opr, at, OPND_W[k]);
            const uint64_t m = k == 0 ? pc : k == 1 ? code : want[k - 2];
            if (got != m && !(want[7] && k >= 7))
                report(OPND_N[k], m, got);
        }
        if (uint64_t(d.obad) != want[7])
            report("record bad", want[7], d.obad);
        if (!want[7]) {
            if (d.xbad)
                report("execute bad", 0, 1);
            off = RFW;
            for (int k = 0; k < NRF; ++k) {
                off -= RF_W[k];
                const uint64_t got = get_bits(d.rf_out, off, RF_W[k]);
                if (got != after[k])
                    report(RF_N[k], after[k], got);
            }
        }
        if (wrong)
            ++bad;
    }
    std::printf("SUMMARY vectors=%ld bad=%ld\n", n, bad);
    return bad ? 1 : 0;
}
