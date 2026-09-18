#include "runtime_link.h"

#include <string.h>

#include "hardware/gpio.h"
#include "hardware/spi.h"
#include "pico/stdlib.h"

#define LINK_SPI spi0
#define LINK_BAUD_HZ 10000000u
#define LINK_CS NUBOARD_FPGA_CDI1_PIN

static bool healthy;
static bool initialized;
static uint32_t last_status;
static uint8_t transaction_tx[1 + 16 + FPGA_PACKET_MAX];
static uint8_t transaction_rx[sizeof(transaction_tx)];
static uint8_t packet_buffer[16 + FPGA_PACKET_MAX];

static void put16(uint8_t *destination, uint16_t value) {
    destination[0] = (uint8_t)value;
    destination[1] = (uint8_t)(value >> 8);
}

static void put32(uint8_t *destination, uint32_t value) {
    destination[0] = (uint8_t)value;
    destination[1] = (uint8_t)(value >> 8);
    destination[2] = (uint8_t)(value >> 16);
    destination[3] = (uint8_t)(value >> 24);
}

static uint16_t get16(const uint8_t *source) {
    return (uint16_t)source[0] | ((uint16_t)source[1] << 8);
}

static uint32_t get32(const uint8_t *source) {
    return (uint32_t)source[0] | ((uint32_t)source[1] << 8) |
           ((uint32_t)source[2] << 16) | ((uint32_t)source[3] << 24);
}

static bool transaction(uint8_t command, const uint8_t *write_data,
                        uint8_t *read_data, size_t length) {
    if (length > sizeof(transaction_tx) - 1) {
        return false;
    }

    transaction_tx[0] = command;
    if (write_data != NULL) {
        memcpy(transaction_tx + 1, write_data, length);
    } else {
        memset(transaction_tx + 1, 0, length);
    }

    gpio_put(LINK_CS, false);
    int count = spi_write_read_blocking(LINK_SPI, transaction_tx,
                                        transaction_rx, length + 1);
    gpio_put(LINK_CS, true);

    if (count != (int)(length + 1)) {
        return false;
    }
    if (read_data != NULL) {
        memcpy(read_data, transaction_rx + 1, length);
    }
    return true;
}

void runtime_link_init(void) {
    spi_init(LINK_SPI, LINK_BAUD_HZ);
    spi_set_format(LINK_SPI, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(NUBOARD_FPGA_CDI0_PIN, GPIO_FUNC_SPI);
    gpio_set_function(NUBOARD_FPGA_CDI2_PIN, GPIO_FUNC_SPI);
    gpio_set_function(NUBOARD_FPGA_CDI3_PIN, GPIO_FUNC_SPI);
    gpio_set_function(LINK_CS, GPIO_FUNC_SIO);
    gpio_put(LINK_CS, true);
    gpio_set_dir(LINK_CS, GPIO_OUT);
    healthy = false;
    initialized = true;
}

void runtime_link_disable(void) {
    if (initialized) {
        spi_deinit(LINK_SPI);
        initialized = false;
    }
    for (uint pin = NUBOARD_FPGA_CDI0_PIN;
         pin <= NUBOARD_FPGA_CDI3_PIN; ++pin) {
        gpio_set_function(pin, GPIO_FUNC_SIO);
        gpio_set_dir(pin, GPIO_IN);
    }
    healthy = false;
    last_status = 0;
}

bool runtime_link_qualify(fpga_identity_t *identity) {
    uint8_t raw[32];
    if (!transaction(FPGA_CMD_GET_ID, NULL, raw, sizeof(raw))) {
        return false;
    }

    memcpy(identity->uuid, raw, 16);
    identity->version = get32(raw + 16);
    identity->build = get32(raw + 20);
    identity->abi_major = get16(raw + 24);
    identity->abi_minor = get16(raw + 26);
    identity->features = get32(raw + 28);
    healthy = identity->abi_major == FPGA_MAILBOX_ABI_MAJOR;
    return healthy;
}

bool runtime_link_healthy(void) {
    return healthy;
}

uint32_t runtime_link_status(void) {
    uint8_t raw[4];
    if (!healthy) {
        return 0;
    }
    if (!transaction(FPGA_CMD_STATUS, NULL, raw, sizeof(raw))) {
        healthy = false;
        return 0;
    }

    last_status = get32(raw);
    return last_status;
}

bool runtime_link_send(uint8_t channel, uint16_t flags, uint32_t tag,
                       const uint8_t *payload, size_t length) {
    if (!healthy || length > FPGA_PACKET_MAX) {
        return false;
    }

    // STATUS bit 0 advertises that the inbound slot can accept a packet.
    // Checking it here prevents a successful SPI transfer from being mistaken
    // for a successful mailbox enqueue when the FPGA is applying backpressure.
    if ((runtime_link_status() & 1u) == 0) {
        return false;
    }

    packet_buffer[0] = FPGA_MAILBOX_ABI_MAJOR;
    packet_buffer[1] = channel;
    put16(packet_buffer + 2, flags);
    put32(packet_buffer + 4, tag);
    put32(packet_buffer + 8, (uint32_t)length);
    put32(packet_buffer + 12, runtime_crc32c(payload, length, 0));
    memcpy(packet_buffer + 16, payload, length);

    if (!transaction(FPGA_CMD_WRITE_PACKET, packet_buffer, NULL,
                     length + 16)) {
        healthy = false;
        return false;
    }
    return true;
}

bool runtime_link_receive(fpga_packet_header_t *header, uint8_t *payload,
                          size_t capacity, size_t *length) {
    if (!healthy) {
        return false;
    }
    if (!transaction(FPGA_CMD_READ_PACKET, NULL, packet_buffer,
                     sizeof(packet_buffer))) {
        healthy = false;
        return false;
    }

    header->abi_major = packet_buffer[0];
    header->channel = packet_buffer[1];
    header->flags = get16(packet_buffer + 2);
    header->tag = get32(packet_buffer + 4);
    header->payload_length = get32(packet_buffer + 8);
    header->crc32c = get32(packet_buffer + 12);

    if (header->abi_major != FPGA_MAILBOX_ABI_MAJOR ||
        header->payload_length > capacity ||
        header->payload_length > FPGA_PACKET_MAX) {
        healthy = false;
        return false;
    }

    memcpy(payload, packet_buffer + 16, header->payload_length);
    if (runtime_crc32c(payload, header->payload_length, 0) !=
        header->crc32c) {
        healthy = false;
        return false;
    }

    *length = header->payload_length;
    return true;
}

bool runtime_link_ack(uint32_t tag) {
    uint8_t raw[4];
    put32(raw, tag);
    if (!healthy) {
        return false;
    }
    if (!transaction(FPGA_CMD_ACK_PACKET, raw, NULL, sizeof(raw))) {
        healthy = false;
        return false;
    }
    return true;
}
