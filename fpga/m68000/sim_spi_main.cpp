#include "Vnuboard_m68000.h"
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
    Vnuboard_m68000 dut{&context};
    uint32_t tag = 0;

    static uint32_t checksum(const std::vector<uint8_t>& data, size_t start) {
        uint32_t crc = ~uint32_t(0);
        for (size_t i = start; i < data.size(); ++i) {
            crc ^= data[i];
            for (unsigned bit = 0; bit < 8; ++bit)
                crc = (crc >> 1) ^ ((crc & 1) ? 0x82f63b78 : 0);
        }
        return ~crc;
    }

    static void put32(std::vector<uint8_t>& data, size_t offset, uint32_t value) {
        for (unsigned i = 0; i < 4; ++i)
            data.at(offset + i) = value >> (8 * i);
    }

    void tick(unsigned count = 1) {
        for (unsigned i = 0; i < count; ++i) {
            for (unsigned phase = 0; phase < 8; ++phase) {
                dut.clk_50mhz = phase >= 4;
                dut.eval();
                const auto next_edge = context.time() + 2500;
                while (dut.eventsPending() && dut.nextTimeSlot() < next_edge) {
                    context.timeInc(dut.nextTimeSlot() - context.time());
                    dut.eval();
                }
                context.timeInc(next_edge - context.time());
            }
            if (!dut.dut_isolate || dut.dut_crowbar || dut.xy_oe_n ||
                !dut.t0_oe_n || !dut.t1_oe_n || !dut.t2_oe_n ||
                !dut.b0_oe_n || !dut.b1_oe_n || !dut.b2_oe_n ||
                !dut.l0_oe_n || !dut.l1_oe_n || !dut.l2_oe_n ||
                !dut.r0_oe_n || !dut.r1_oe_n || !dut.r2_oe_n ||
                dut.tclk_en || dut.bclk_en || dut.lclk_en || dut.rclk_en)
                throw std::runtime_error("socket safety output active in model mode");
        }
    }

    uint8_t byte(uint8_t value) {
        uint8_t reply = 0;
        for (int bit = 7; bit >= 0; --bit) {
            dut.spi_sck = 0;
            dut.spi_mosi = (value >> bit) & 1;
            tick(3);
            reply = (reply << 1) | dut.spi_miso;
            dut.spi_sck = 1;
            tick(3);
        }
        dut.spi_sck = 0;
        tick(3);
        return reply;
    }

    void begin(uint8_t opcode) {
        dut.spi_cs_n = 0;
        tick(5);
        byte(opcode);
    }

    void end() {
        dut.spi_cs_n = 1;
        tick(10);
    }

public:
    Simulation() {
        dut.spi_cs_n = 1;
        dut.spi_sck = 0;
        dut.spi_mosi = 0;
        tick(20);
        begin(5);
        std::vector<uint8_t> identity;
        for (unsigned i = 0; i < 32; ++i)
            identity.push_back(byte(0));
        end();
        const char expected[] = "nuBoard-68000-v1";
        for (unsigned i = 0; i < 16; ++i) {
            if (identity[i] != uint8_t(expected[i]))
                throw std::runtime_error("mailbox core UUID mismatch");
        }
        if (get16(identity, 24) != 1 || get32(identity, 16) != 1)
            throw std::runtime_error("mailbox core version/ABI mismatch");
    }

    std::vector<uint8_t> command(const std::vector<uint8_t>& request) {
        std::vector<uint8_t> packet(16, 0);
        packet[0] = 1;
        packet[1] = 0x44;
        packet[2] = 3;
        put32(packet, 4, ++tag);
        put32(packet, 8, request.size());
        packet.insert(packet.end(), request.begin(), request.end());
        put32(packet, 12, checksum(packet, 16));

        begin(2);
        for (auto value : packet)
            byte(value);
        end();

        // Wait directly on IRQ, not a mailbox status polling loop.
        unsigned budget = 60'000'000;
        while (dut.fpga_irq_n) {
            tick();
            if (!--budget)
                throw std::runtime_error("mailbox IRQ timeout");
        }
        // Synchronize the output ownership toggle into the SPI domain.
        begin(1);
        byte(0);
        byte(0);
        end();
        begin(3);
        std::vector<uint8_t> response;
        for (unsigned i = 0; i < 16; ++i)
            response.push_back(byte(0));
        const auto length = get32(response, 8);
        if (length > 4072)
            throw std::runtime_error("invalid mailbox response length");
        for (unsigned i = 0; i < length; ++i)
            response.push_back(byte(0));
        end();
        if (response[0] != 1 || response[1] != 0x44 || response[2] != 3 ||
            get32(response, 4) != tag || get32(response, 12) != checksum(response, 16))
            throw std::runtime_error("mailbox response framing/tag/CRC mismatch");
        begin(4);
        for (unsigned i = 0; i < 4; ++i)
            byte(tag >> (i * 8));
        end();
        if (!dut.fpga_irq_n)
            throw std::runtime_error("acknowledged IRQ remained active");
        return {response.begin() + 16, response.end()};
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
