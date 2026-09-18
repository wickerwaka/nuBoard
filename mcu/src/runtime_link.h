#ifndef NUBOARD_RUNTIME_LINK_H
#define NUBOARD_RUNTIME_LINK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FPGA_MAILBOX_ABI_MAJOR 1u
#define FPGA_PACKET_MAX 4080u

enum {
    FPGA_CMD_STATUS = 0x01,
    FPGA_CMD_WRITE_PACKET = 0x02,
    FPGA_CMD_READ_PACKET = 0x03,
    FPGA_CMD_ACK_PACKET = 0x04,
    FPGA_CMD_GET_ID = 0x05,
};

typedef struct {
    uint8_t abi_major;
    uint8_t channel;
    uint16_t flags;
    uint32_t tag;
    uint32_t payload_length;
    uint32_t crc32c;
} fpga_packet_header_t;

typedef struct {
    uint8_t uuid[16];
    uint32_t version;
    uint32_t build;
    uint16_t abi_major;
    uint16_t abi_minor;
    uint32_t features;
} fpga_identity_t;

void runtime_link_init(void);
void runtime_link_disable(void);
bool runtime_link_qualify(fpga_identity_t *identity);
bool runtime_link_healthy(void);
uint32_t runtime_link_status(void);
bool runtime_link_send(uint8_t channel, uint16_t flags, uint32_t tag,
                       const uint8_t *payload, size_t length);
bool runtime_link_receive(fpga_packet_header_t *header, uint8_t *payload,
                          size_t capacity, size_t *length);
bool runtime_link_ack(uint32_t tag);
uint32_t runtime_crc32c(const void *data, size_t length, uint32_t crc);

#endif
