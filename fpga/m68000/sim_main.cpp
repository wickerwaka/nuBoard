#ifdef NUBOARD_DUAL_SIM
#include "Vm68000_dual_sim.h"
using Model = Vm68000_dual_sim;
#else
#include "Vm68000_harness.h"
using Model = Vm68000_harness;
#endif
#include "verilated.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <vector>

static uint16_t get16(const std::vector<uint8_t>& data, size_t offset) {
    return uint16_t(data.at(offset)) | (uint16_t(data.at(offset + 1)) << 8);
}

static uint32_t get32(const std::vector<uint8_t>& data, size_t offset) {
    return uint32_t(get16(data, offset)) | (uint32_t(get16(data, offset + 2)) << 16);
}

class Simulation {
    VerilatedContext context;
    Model dut{&context};

public:
    Simulation() {
#ifndef NUBOARD_DUAL_SIM
        dut.socket_as_n = 1;
        dut.socket_uds_n = 1;
        dut.socket_lds_n = 1;
        dut.socket_read = 1;
        dut.socket_reset_n = 1;
        dut.socket_halt_n = 1;
        dut.socket_bg_n = 1;
        dut.socket_br_sense_n = 1;
#endif
        for (unsigned i = 0; i < 20; ++i)
            tick();
    }

    void tick() {
        // Timing-enabled Verilator advances in the design's 1 ps precision.
        for (unsigned phase = 0; phase < 8; ++phase) {
            dut.clock = phase >= 4;
            dut.eval();
            const auto next_edge = context.time() + 2500;
            while (dut.eventsPending() && dut.nextTimeSlot() < next_edge) {
                context.timeInc(dut.nextTimeSlot() - context.time());
                dut.eval();
            }
            context.timeInc(next_edge - context.time());
        }
    }

    uint16_t access(bool write, uint32_t address, uint16_t value = 0) {
        dut.debug_valid = 1;
        dut.debug_write = write;
        dut.debug_address = address;
        dut.debug_write_data = value;
        unsigned timeout = 10000; // A PSRAM cache miss is a complete burst.
        do {
            tick();
            if (!--timeout)
                throw std::runtime_error("debug bus did not acknowledge");
        } while (!dut.debug_ready);
        const auto result = dut.debug_read_data;
        const bool error = dut.debug_error;
        dut.debug_valid = 0;
        tick();
        if (error)
            throw std::runtime_error("debug bus rejected access");
        return result;
    }

    std::vector<uint8_t> command(const std::vector<uint8_t>& request) {
        std::vector<uint8_t> reply(4, 0);
        try {
            if (request.size() < 12 || get32(request, 0) != 0x3142444e ||
                request[5] != 0)
                throw std::runtime_error("invalid debug header");
            const unsigned op = request[4];
            const unsigned length = get16(request, 6);
            const uint32_t address = get32(request, 8);
            if (length == 0 || (op != 3 && length > 4068) || (length & 1) || (address & 1) ||
                address >= 0x100000 || address + length > 0x100000 || op > 3)
                throw std::runtime_error("invalid debug range");
            if (request.size() != 12 + (op == 1 ? length : op == 2 ? 8 : op == 3 ? 2 : 0))
                throw std::runtime_error("invalid debug length");

            if (op == 2) {
                if (length != 2)
                    throw std::runtime_error("wait requires a single register");
                const uint16_t mask = get16(request, 12);
                const uint16_t expected = get16(request, 14);
                uint32_t budget = get32(request, 16);
                if (budget == 0 || budget > 100'000'000)
                    throw std::runtime_error("invalid wait budget");
                uint16_t value = 0;
                bool matched = false;
                while (budget >= 5) {
                    value = access(false, address);
                    budget -= 5;
                    if ((value & mask) == expected) {
                        matched = true;
                        break;
                    }
                }
                if (!matched) {
                    reply[0] = 3;
                    return reply;
                }
                reply.push_back(value & 255);
                reply.push_back(value >> 8);
            } else {
                for (unsigned i = 0; i < length; i += 2) {
                    const uint16_t write_value = op == 1 ? get16(request, 12 + i) :
                                                 op == 3 ? get16(request, 12) : 0;
                    const auto value = access(op == 1 || op == 3, address + i, write_value);
                    if (op == 0) {
                        reply.push_back(value & 255);
                        reply.push_back(value >> 8);
                    }
                }
            }
        } catch (const std::exception& error) {
            std::fprintf(stderr, "simulation command: %s\n", error.what());
            reply.assign(4, 0);
            reply[0] = 1;
        }
        return reply;
    }
};

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Simulation simulation;
    uint8_t header[4];
    while (std::fread(header, 1, 4, stdin) == 4) {
        const uint32_t length = uint32_t(header[0]) | (uint32_t(header[1]) << 8) |
                                (uint32_t(header[2]) << 16) | (uint32_t(header[3]) << 24);
        if (length > 4096)
            return 2;
        std::vector<uint8_t> request(length);
        if (std::fread(request.data(), 1, length, stdin) != length)
            return 2;
        const auto reply = simulation.command(request);
        const uint32_t size = reply.size();
        for (unsigned i = 0; i < 4; ++i)
            header[i] = uint8_t(size >> (i * 8));
        std::fwrite(header, 1, 4, stdout);
        std::fwrite(reply.data(), 1, reply.size(), stdout);
        std::fflush(stdout);
    }
    return 0;
}
