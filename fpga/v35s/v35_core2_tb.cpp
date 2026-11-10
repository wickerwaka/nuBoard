// The core v2's whole-core function bench (stage S6): v35_top (fpga/v35s/v35_core2_tb.sv) runs
// one instruction per test from a preloaded state, its memory served here, and its state after
// the instruction is compared with the test's expected one. The tests come from
// validation/v35s/chains/sst.py --rtl (SingleStepTests V20) and rtl_vectors.py --regfile, two
// lines each:
//
//   V35SST-1 <count>
//   T <id> <starts> <limit> AW CW DW BW SP BP IX IY DS1 PS SS DS0 PSW IP <clen> <ioword>
//     <n> {addr byte} x n
//   E <trap> AW CW DW BW SP BP IX IY DS1 PS SS DS0 PSW IP <n> {addr byte} x n
//     <m> {port width data} x m
//
// T: the state before (the register file, the PSW, PS:IP the first byte of the test's
// instruction, its prefixes included) and the memory the test lists; every other byte reads
// 90h (a fetch past the instruction: clen, the instruction's bytes from PS:IP; an operand read
// of an unlisted byte is counted apart by the Python side), every I/O read the word ioword.
// starts: the instruction starts the test is (a segment prefix is one); the run ends at the
// start after them (the next instruction's), or fails after limit CPU clocks.
// E: the state after (the next start's PS:IP is IP), the memory bytes after (each must hold its
// value; a listed byte not among them must be unchanged; a write to a byte the test does not
// list fails), the I/O writes in order (width 0 word, 1 low lane, 2 high lane; the data on the
// lanes; m -1: not compared). trap 1: a divide error: only the trap condition (the divider's) is checked, the
// trap sequence is not built; trap 0: no divide error may be raised.
//
//   Vv35_core2_tb TESTS [+trace]
//
// Output: a line for every test that is not a pass ("FAIL <id> <what> ...", "TRAPNOP <id>
// <class>": its instruction decoded as trap_nop (class 0), not compared; "TIMEOUT <id>"), then
// "SUMMARY tests=N pass=N fail=N trapnop=N". Exit 0 when nothing failed.
#include "Vv35_core2_tb.h"
#include "Vv35_core2_tb___024root.h"
#include "verilated.h"
#include "verilated_save.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

enum { K_NONE, K_FETCH, K_READ, K_WRITE, K_IO_READ, K_IO_WRITE, K_REFRESH };
enum { BW_WORD, BW_LO, BW_HI };
const char* REGN[14] = {"AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY",
                        "DS1", "PS", "SS", "DS0", "PSW", "IP"};

struct Test {
    std::string id;
    int starts = 1;
    long limit = 2000;
    uint32_t clen = 0;                  // the instruction's bytes (prefixes included) from PS:IP
    uint32_t ioword = 0xFFFF;           // every I/O read's word
    uint32_t in[14] = {};
    std::vector<std::pair<uint32_t, uint32_t>> ram;
    int trap = 0;
    uint32_t out[14] = {};
    std::vector<std::pair<uint32_t, uint32_t>> fin;
    std::vector<uint32_t> io;           // port, width, data triples
    bool io_check = true;               // (m < 0: the I/O writes are not known)
};

bool read_test(std::ifstream& in, Test& t) {
    std::string tag;
    if (!(in >> tag) || tag != "T")
        return false;
    in >> t.id >> t.starts >> t.limit;
    for (auto& v : t.in)
        in >> v;
    in >> t.clen >> t.ioword;
    size_t n;
    in >> n;
    t.ram.resize(n);
    for (auto& p : t.ram)
        in >> p.first >> p.second;
    if (!(in >> tag) || tag != "E")
        return false;
    in >> t.trap;
    for (auto& v : t.out)
        in >> v;
    in >> n;
    t.fin.resize(n);
    for (auto& p : t.fin)
        in >> p.first >> p.second;
    long m;
    in >> m;
    t.io_check = m >= 0;
    t.io.resize(t.io_check ? 3 * m : 0);
    for (auto& v : t.io)
        in >> v;
    return bool(in);
}

// The model's state after its first reset, kept in memory and restored before every test (built
// --savable): the core's reset does not clear every register (v35_queue's transfer and take
// holds, v35_bus's last-write tracking, v35_ucode's mul_from counters among them: README,
// "Not built"), so a test would inherit the last one's holds; the harness resets once
struct MemSave final : VerilatedSerialize {
    std::vector<uint8_t>& out;
    explicit MemSave(std::vector<uint8_t>& o) : out(o) {
        m_isOpen = true;
        header();
    }
    void flush() override {
        out.insert(out.end(), m_bufp, m_cp);
        m_cp = m_bufp;
    }
    void close() override {
        trailer();
        flush();
        m_isOpen = false;
    }
};
struct MemRestore final : VerilatedDeserialize {
    const std::vector<uint8_t>& in;
    size_t pos = 0;
    explicit MemRestore(const std::vector<uint8_t>& i) : in(i) {
        m_isOpen = true;
        m_cp = m_bufp;
        m_endp = m_bufp;
        header();
    }
    void fill() override {
        uint8_t* rp = m_bufp;
        for (uint8_t* sp = m_cp; sp < m_endp; *rp++ = *sp++) {}
        m_endp = m_bufp + (m_endp - m_cp);
        m_cp = m_bufp;
        size_t room = size_t(m_bufp + bufferSize() - m_endp);
        size_t n = std::min(room, in.size() - pos);
        std::memcpy(m_endp, in.data() + pos, n);
        pos += n;
        m_endp += n;
        while (m_endp < m_bufp + bufferSize())
            *m_endp++ = 0;
    }
    void close() override {
        trailer();
        m_isOpen = false;
    }
};

struct Bench {
    VerilatedContext ctx;
    Vv35_core2_tb d{&ctx};
    Vv35_core2_tb___024root* r = d.rootp;

    void half(int clk) {
        d.clock = clk;
        d.eval();
    }
};

// the word register i of REG16 (AW CW DW BW SP BP IX IY) in bank b: RAM word {b, 15 - i};
// the segment register s (0 DS1, 1 PS, 2 SS, 3 DS0): {b, 7 - s}
inline unsigned rword(unsigned b, unsigned i) { return (b << 4) | (15 - i); }
inline unsigned sword(unsigned b, unsigned s) { return (b << 4) | (7 - s); }

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s TESTS [+trace]\n", argv[0]);
        return 2;
    }
    bool trace = argc > 2 && std::strcmp(argv[2], "+trace") == 0;
    std::ifstream in(argv[1]);
    std::string format;
    long count = 0;
    in >> format >> count;
    if (format != "V35SST-1") {
        std::fprintf(stderr, "not a V35SST-1 test file\n");
        return 2;
    }
    Bench b;
    b.ctx.commandArgs(argc, argv);
    b.half(0);              // the initial blocks run (before any preload)
    b.d.reset_n = 0;
    for (int i = 0; i < 2; ++i) {
        b.half(0);
        b.half(1);
    }
    std::vector<uint8_t> snap;
    const bool bare = std::getenv("V35_C2_BARE") != nullptr;
    {
        MemSave os(snap);
        os << b.d;
        os.close();
    }
    auto& d = b.d;
    auto* r = b.r;
    long pass = 0, fail = 0, trapnop = 0, n = 0;
    Test t;
    std::unordered_map<uint32_t, uint8_t> mem;
    std::unordered_map<uint32_t, uint8_t> listed;
    for (; n < count; ++n) {
        if (!read_test(in, t)) {
            std::fprintf(stderr, "bad test %ld\n", n);
            return 2;
        }
        mem.clear();
        listed.clear();
        for (auto& p : t.ram) {
            mem[p.first] = uint8_t(p.second);
            listed[p.first] = uint8_t(p.second);
        }
        auto byte = [&](uint32_t a) -> uint32_t {
            auto it = mem.find(a & 0xFFFFF);
            return it == mem.end() ? 0x90 : it->second;
        };
        const uint32_t ps0 = t.in[9], ip0 = t.in[13];
        // ---- reset with the test's first fetch address, then the preload
        // ((S7b) V35_C2_BARE=1: no restore, the reset alone: the reset blocks are complete)
        if (!bare) {
            MemRestore is(snap);
            is >> b.d;
            is.close();
        }
        r->v35_core2_tb__DOT__dut__DOT__tb_reset_addr = ((ps0 << 4) + ip0) & 0xFFFFF;
        r->v35_core2_tb__DOT__dut__DOT__tb_reset_ip = ip0 & 0xFFFF;   // (Q1) the queue's pfp
        d.reset_n = 0;
        d.data_in = 0xFFFF;
        for (int i = 0; i < 2; ++i) {
            b.half(0);
            b.half(1);
        }
        d.reset_n = 1;
        b.half(0);
        r->v35_core2_tb__DOT__dut__DOT__core_run = 1;
        r->v35_core2_tb__DOT__dut__DOT__sfr__DOT__prc &= 0xFC;         // PCK 0: X1/2
        r->v35_core2_tb__DOT__dut__DOT__sfr__DOT__wtc = 0;              // no waits
        const uint32_t psw = t.in[12];
        const unsigned bank = (psw >> 12) & 7;
        r->v35_core2_tb__DOT__dut__DOT__eu__DOT__psw = psw;
        r->v35_core2_tb__DOT__dut__DOT__eu__DOT__ds1 = t.in[8];
        r->v35_core2_tb__DOT__dut__DOT__eu__DOT__ps = t.in[9];
        r->v35_core2_tb__DOT__dut__DOT__eu__DOT__ss = t.in[10];
        r->v35_core2_tb__DOT__dut__DOT__eu__DOT__ds0 = t.in[11];
        // ((MX0) CW / IX / IY are RAM words only: preloaded with the others below)
        auto put = [&](unsigned a, uint32_t v) {
            r->v35_core2_tb__DOT__dut__DOT__regram__DOT__ae[a] = v & 0xFF;
            r->v35_core2_tb__DOT__dut__DOT__regram__DOT__be[a] = v & 0xFF;
            r->v35_core2_tb__DOT__dut__DOT__regram__DOT__ao[a] = (v >> 8) & 0xFF;
            r->v35_core2_tb__DOT__dut__DOT__regram__DOT__bo[a] = (v >> 8) & 0xFF;
        };
        for (unsigned i = 0; i < 8; ++i)
            put(rword(bank, i), t.in[i]);
        for (unsigned s = 0; s < 4; ++s)
            put(sword(bank, s), t.in[8 + s]);
        b.half(0);
        // ---- run: the memory served on the current cycle, the writes off the pins
        int starts = 0;
        bool done = false, trapped = false, missed = false, pend = false, dropped = false;
        bool halted = false;
        int cls = -1;
        uint32_t next_addr = 0;
        std::vector<uint32_t> io;
        std::vector<std::string> bad;
        std::map<uint32_t, uint8_t> wrote;
        long clk = 0;
        int pend_w = 0;
        // data_in for the cycle on the bus (sampled mid-B3)
        // (a fetch reads the test's bytes only inside its instruction, clen bytes from PS:IP;
        // any other byte 90h: the instruction after it is a NOP, its start does nothing)
        // (after the test's instruction flushed the queue, every fetch 90h: a transfer to
        // itself starts a NOP)
        bool flushed = false;
        auto fbyte = [&](uint32_t a) -> uint32_t {
            uint32_t off = (a - (ps0 << 4)) & 0xFFFFF;
            if (t.clen && (flushed || off > 0xFFFF || ((off - ip0) & 0xFFFF) >= t.clen))
                return 0x90;
            return byte(a);
        };
        auto serve = [&]() {
            if (d.o_c_valid) {
                uint32_t a = d.o_c_addr;
                if (d.o_c_kind == K_IO_READ)
                    d.data_in = t.ioword;
                else if (d.o_c_kind == K_FETCH)
                    d.data_in = fbyte(a & ~1u) | (fbyte(a | 1u) << 8);
                else
                    d.data_in = byte(a & ~1u) | (byte(a | 1u) << 8);
            }
        };
        // a write cycle's datum off the pins at its last state (true: one taken)
        auto capture = [&]() -> bool {
            if (d.o_ce_mid && d.o_c_valid && d.o_c_pos == d.o_c_len - 1 && !d.o_c_internal
                && (d.o_c_kind == K_WRITE || d.o_c_kind == K_IO_WRITE)) {
                uint32_t a = d.o_c_addr, w = d.o_c_width, v = d.o_data_out;
                if (d.o_c_kind == K_IO_WRITE) {
                    io.push_back(a);
                    io.push_back(w);
                    io.push_back(w == BW_WORD ? v : w == BW_LO ? (v & 0xFF) : (v & 0xFF00));
                } else if (w == BW_WORD) {
                    mem[a & 0xFFFFF] = v & 0xFF;
                    mem[(a + 1) & 0xFFFFF] = v >> 8;
                    wrote[a & 0xFFFFF] = v & 0xFF;
                    wrote[(a + 1) & 0xFFFFF] = v >> 8;
                } else {
                    uint8_t x = w == BW_HI ? v >> 8 : v & 0xFF;
                    mem[a & 0xFFFFF] = x;
                    wrote[a & 0xFFFFF] = x;
                }
                if (trace)
                    std::printf("  %ld %s %05X w%u %04X\n", clk,
                                d.o_c_kind == K_IO_WRITE ? "iow" : "wr", a, w, v);
                return true;
            }
            return false;
        };
        for (long cyc = 0; cyc < 4 * t.limit + 64 && !done; ++cyc) {
            serve();
            b.half(0);
            capture();
            if (d.o_ce) {
                int k = int(d.o_t_start) + int(d.o_p_start);
                for (int j = 0; j < k && !done; ++j) {
                    bool tt = j == 0 && d.o_t_start;
                    ++starts;
                    if (starts == t.starts)
                        cls = tt ? d.o_t_cls : d.o_p_cls;
                    if (starts == t.starts + 1) {
                        next_addr = tt ? d.o_t_addr : d.o_p_addr;
                        done = true;
                    }
                }
                if (trace)
                    std::printf("  %ld start %d/%d T%d P%d @%05X/%05X bus %d:%d/%d@%05X dsel %d"
                                " imm %04X cw %04X psw %04X\n", clk, starts, t.starts, d.o_t_start, d.o_p_start,
                                d.o_t_addr, d.o_p_addr, d.o_c_valid ? d.o_c_kind : 0,
                                d.o_c_pos, d.o_c_len, d.o_c_addr, d.o_dsel, d.o_wd_imm, d.o_cw, d.o_psw);
                if (done) {
                    // the start clock's own update: the last form's writes on it (an IN's AL at
                    // its read's delivery, a bit field's pointer step at its end) land at its
                    // edge; the next instruction is a NOP (fbyte), its start writes nothing
                    pend = d.o_exec_pend;
                    pend_w = d.o_pend_w;
                    trapped |= d.o_div_trap;
                    missed |= d.o_miss;
                    dropped |= d.o_drop;
                    b.half(1);
                    break;
                }
                trapped |= d.o_div_trap;
                missed |= d.o_miss;
                dropped |= d.o_drop;
                flushed |= starts >= t.starts && d.o_flush;
                ++clk;
                if (d.o_halted && starts >= t.starts) {
                    halted = done = true;       // HALT: no next start (its IP not compared)
                    break;
                }
            }
            b.half(1);
        }
        if (cls == 0) {
            ++trapnop;
            std::printf("TRAPNOP %s\n", t.id.c_str());
            continue;
        }
        if (t.trap) {
            if (!trapped) {
                ++fail;
                std::printf("FAIL %s no divide error raised (the suite's trap)\n", t.id.c_str());
            } else {
                ++pass;
            }
            continue;
        }
        if (!done) {
            ++fail;
            std::printf("TIMEOUT %s after %ld clocks (%d starts)\n", t.id.c_str(), clk, starts);
            continue;
        }
        if (trapped)
            bad.push_back("divide error raised");
        if (dropped)
            bad.push_back("a read's exec lost (its operands not on the ports)");
        if (missed)
            bad.push_back("register write lost");
        if (pend)
            bad.push_back("exec pending at the next start");
        // ---- the state after: the register RAM (the pending second write applied), CW / IX /
        // IY and the segment registers from the flops (their RAM copies checked), the PSW
        uint32_t ram_w[16];
        const unsigned bk = (d.o_psw >> 12) & 7;
        for (unsigned a = 0; a < 16; ++a) {
            unsigned w = (bk << 4) | a;
            uint32_t v = r->v35_core2_tb__DOT__dut__DOT__regram__DOT__ae[w]
                         | (r->v35_core2_tb__DOT__dut__DOT__regram__DOT__ao[w] << 8);
            if (d.o_w2_v && d.o_w2_a == w)
                v = ((d.o_w2_be & 2) ? (d.o_w2_d & 0xFF00) : (v & 0xFF00))
                    | ((d.o_w2_be & 1) ? (d.o_w2_d & 0xFF) : (v & 0xFF));
            ram_w[a] = v;
        }
        uint32_t got[14];
        for (unsigned i = 0; i < 8; ++i)
            got[i] = ram_w[15 - i];
        uint32_t flop_cw = d.o_cw, flop_ix = d.o_ix, flop_iy = d.o_iy;
        if (!(d.o_stale & 4) && got[1] != flop_cw)
            bad.push_back("CW's RAM copy " + std::to_string(got[1]));
        if (!(d.o_stale & 2) && got[6] != flop_ix)
            bad.push_back("IX's RAM copy " + std::to_string(got[6]));
        if (!(d.o_stale & 1) && got[7] != flop_iy)
            bad.push_back("IY's RAM copy " + std::to_string(got[7]));
        if (!(d.o_stale & 4))
            got[1] = flop_cw;
        if (!(d.o_stale & 2))
            got[6] = flop_ix;
        if (!(d.o_stale & 1))
            got[7] = flop_iy;
        uint32_t segf[4] = {d.o_ds1, d.o_ps, d.o_ss, d.o_ds0};
        for (unsigned s = 0; s < 4; ++s) {
            if (ram_w[7 - s] != segf[s])
                bad.push_back(std::string(REGN[8 + s]) + "'s RAM copy "
                              + std::to_string(ram_w[7 - s]));
            got[8 + s] = segf[s];
        }
        got[12] = d.o_psw;
        got[13] = halted ? t.out[13] : (next_addr - (t.out[9] << 4)) & 0xFFFF;
        char buf[160];
        for (unsigned i = 0; i < 14; ++i) {
            if (got[i] != t.out[i]) {
                std::snprintf(buf, sizeof buf, "%s %04X (want %04X)", REGN[i], got[i], t.out[i]);
                bad.push_back(buf);
            }
        }
        // ---- the writes posted and not yet run (a detached OUT): the core runs on (the next
        // instruction's own writes are posted behind them) until they are off the pins
        if (pend_w) {
            for (long cyc = 0, caps = 0; cyc < 2000 && caps < pend_w; ++cyc) {
                serve();
                b.half(0);
                caps += capture();
                b.half(1);
            }
        }
        // ---- the memory
        std::unordered_map<uint32_t, uint8_t> want;
        for (auto& p : t.fin)
            want[p.first] = uint8_t(p.second);
        for (auto& p : t.fin) {
            uint32_t g = byte(p.first);
            if (g != p.second) {
                std::snprintf(buf, sizeof buf, "[%05X] %02X (want %02X)", p.first, g, p.second);
                bad.push_back(buf);
            }
        }
        for (auto& p : wrote) {
            if (want.count(p.first))
                continue;
            auto it = listed.find(p.first);
            if (it == listed.end()) {
                std::snprintf(buf, sizeof buf, "[%05X] %02X written (unlisted)", p.first,
                              p.second);
                bad.push_back(buf);
            } else if (it->second != p.second) {
                std::snprintf(buf, sizeof buf, "[%05X] %02X written (want unchanged %02X)",
                              p.first, p.second, it->second);
                bad.push_back(buf);
            }
        }
        if (t.io_check && io != t.io) {
            std::string s = "I/O writes";
            for (size_t i = 0; i < io.size(); i += 3) {
                std::snprintf(buf, sizeof buf, " %X/%u/%X", io[i], io[i + 1], io[i + 2]);
                s += buf;
            }
            s += " (want";
            for (size_t i = 0; i < t.io.size(); i += 3) {
                std::snprintf(buf, sizeof buf, " %X/%u/%X", t.io[i], t.io[i + 1], t.io[i + 2]);
                s += buf;
            }
            bad.push_back(s + ")");
        }
        if (bad.empty()) {
            ++pass;
        } else {
            ++fail;
            std::string s = "FAIL " + t.id;
            for (auto& x : bad)
                s += "; " + x;
            std::printf("%s\n", s.c_str());
        }
    }
    std::printf("SUMMARY tests=%ld pass=%ld fail=%ld trapnop=%ld\n", n, pass, fail, trapnop);
    return fail ? 1 : 0;
}
