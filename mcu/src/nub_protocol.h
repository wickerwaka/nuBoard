#ifndef NUBOARD_PROTOCOL_H
#define NUBOARD_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define NUB_PROTOCOL_MAJOR 1u
#define NUB_PROTOCOL_MINOR 0u
#define NUB_MAX_PAYLOAD 4096u
#define NUB_HEADER_SIZE 20u
#define NUB_EVENT_SIZE 32u
#define NUB_CONFIG_DATA_MAX (NUB_MAX_PAYLOAD - 4u)
#define NUB_MAX_IMAGE_SIZE (32u * 1024u * 1024u)

typedef enum {
    NUB_KIND_REQUEST = 0,
    NUB_KIND_RESPONSE = 1,
} nub_kind_t;

typedef enum {
    NUB_OP_GET_INFO = 0x0001,
    NUB_OP_GET_STATE = 0x0002,
    NUB_OP_CONFIG_BEGIN = 0x0100,
    NUB_OP_CONFIG_DATA = 0x0101,
    NUB_OP_CONFIG_END = 0x0102,
    NUB_OP_CONFIG_ABORT = 0x0103,
    NUB_OP_FPGA_SEND = 0x0200,
    NUB_OP_FPGA_RECV = 0x0201,
    NUB_OP_LINK_STATUS = 0x0202,
    NUB_OP_VCCB_ENABLE = 0x0300,
    NUB_OP_VCCB_DISABLE = 0x0301,
    NUB_OP_POWER_OFF = 0x0302,
} nub_opcode_t;

typedef enum {
    NUB_STATUS_OK = 0,
    NUB_STATUS_VERSION = 1,
    NUB_STATUS_LENGTH = 2,
    NUB_STATUS_STATE = 3,
    NUB_STATUS_ARGUMENT = 4,
    NUB_STATUS_BUSY = 5,
    NUB_STATUS_TIMEOUT = 6,
    NUB_STATUS_CHECKSUM = 7,
    NUB_STATUS_LINK = 8,
    NUB_STATUS_CONFIGURATION = 9,
    NUB_STATUS_SELECTOR = 10,
    NUB_STATUS_INTERNAL = 11,
} nub_status_t;

typedef enum {
    NUB_EVENT_FPGA_IRQ = 1,
    NUB_EVENT_STATE = 2,
    NUB_EVENT_CONFIG_FAILURE = 3,
    NUB_EVENT_VCCB_SHUTDOWN = 4,
    NUB_EVENT_LINK_FAULT = 5,
    NUB_EVENT_OVERFLOW = 6,
} nub_event_type_t;

typedef struct {
    uint8_t major;
    uint8_t minor;
    uint8_t kind;
    uint8_t flags;
    uint16_t opcode;
    uint16_t status;
    uint32_t sequence;
    uint32_t payload_length;
} nub_header_t;

nub_status_t nub_header_decode(const uint8_t raw[NUB_HEADER_SIZE],
                               nub_header_t *header);
void nub_header_encode(uint8_t raw[NUB_HEADER_SIZE],
                       const nub_header_t *header);
void nub_event_encode(uint8_t raw[NUB_EVENT_SIZE], nub_event_type_t type,
                      uint8_t flags, uint32_t sequence, uint32_t timestamp_us,
                      uint32_t argument0, uint32_t argument1, uint32_t lost);

#endif
