// The core v2's function bench (stage S3): v35_rf_tb (fpga/v35s/v35_rf_tb.sv: v35_fn_pkg's
// functions) against the functional reference (validation/v35s/chains/funcref.py) through
// rtl_vectors.py --fn's vectors, one function application per line:
//
//   V35FN-1 <count>
//   <kind> <op> <w> <sgn> <a> <b> <n> <psw> <res> <psw after> <trap>
//
// kind A ALU (res not compared for CMP, op 7), T TEST (the PSW only), I INC / DEC (the ALU with
// CY kept), S shift, M MUL (res the product), D DIV (res {remainder, quotient}; trap the divide
// error, then only the trap compared), J adjust (res AW), C condition (res taken; the condition
// code in op's place, the PSW). The PSW is compared whole.
//
//   Vv35_rf_tb VECTORS
//
// Output: "FAIL ..." for the first failures, "BAD i" for every failing vector, "SUMMARY
// vectors=N bad=N". Exit 0 when nothing failed.
#include "Vv35_rf_tb.h"
#include "verilated.h"

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s VECTORS\n", argv[0]);
        return 2;
    }
    std::ifstream in(argv[1]);
    std::string format;
    long n = 0;
    in >> format >> n;
    if (format != "V35FN-1") {
        std::fprintf(stderr, "not a V35FN-1 vector file\n");
        return 2;
    }
    VerilatedContext context;
    Vv35_rf_tb d{&context};
    long bad = 0, fails = 0;
    for (long i = 0; i < n; ++i) {
        std::string kind;
        uint64_t op, w, sgn, a, b, cnt, psw, res, pswa, trap;
        in >> kind >> op >> w >> sgn >> a >> b >> cnt >> psw >> res >> pswa >> trap;
        if (!in) {
            std::fprintf(stderr, "bad vector %ld\n", i);
            return 2;
        }
        d.op = (kind == "C") ? 0 : op;
        d.cc = (kind == "C") ? op : 0;
        d.w = w;
        d.sgn = sgn;
        d.a = a;
        d.b = b;
        d.n = cnt;
        d.psw = psw;
        d.eval();
        bool wrong = false;
        auto check = [&](const char* what, uint64_t want, uint64_t got) {
            if (want == got)
                return;
            wrong = true;
            if (++fails <= 20)
                std::printf("FAIL vector %ld kind %s op %llu w %llu a %llu b %llu n %llu psw %llu: "
                            "%s want=%llu rtl=%llu\n", i, kind.c_str(), (unsigned long long)op,
                            (unsigned long long)w, (unsigned long long)a, (unsigned long long)b,
                            (unsigned long long)cnt, (unsigned long long)psw, what,
                            (unsigned long long)want, (unsigned long long)got);
        };
        if (kind == "A" || kind == "T") {
            if (kind == "A" && op != 7)
                check("result", res, d.alu_res);
            check("psw", pswa, d.alu_psw);
        } else if (kind == "I") {
            check("result", res, d.inc_res);
            check("psw", pswa, d.inc_psw);
        } else if (kind == "S") {
            check("result", res, d.sh_res);
            check("psw", pswa, d.sh_psw);
        } else if (kind == "M") {
            check("product", res, w ? uint64_t(d.mul_res) : (uint64_t(d.mul_res) & 0xFFFF));
            check("psw", pswa, d.mul_psw);
        } else if (kind == "D") {
            check("trap", trap, d.div_trap);
            if (!trap) {
                check("result", res, w ? uint64_t(d.div_res) : (uint64_t(d.div_res) & 0xFFFF));
                check("psw", pswa, d.div_psw);
            }
        } else if (kind == "J") {
            check("AW", res, d.adj_aw);
            check("psw", pswa, d.adj_psw);
        } else if (kind == "C") {
            check("taken", res, d.cond);
        } else {
            std::fprintf(stderr, "unknown kind %s in vector %ld\n", kind.c_str(), i);
            return 2;
        }
        if (wrong) {
            ++bad;
            std::printf("BAD %ld\n", i);
        }
    }
    std::printf("SUMMARY vectors=%ld bad=%ld\n", n, bad);
    return bad ? 1 : 0;
}
