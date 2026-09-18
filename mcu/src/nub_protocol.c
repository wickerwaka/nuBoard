#include "nub_protocol.h"

#include <string.h>

static uint16_t get16(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void put16(uint8_t *p, uint16_t value) {
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

static void put32(uint8_t *p, uint32_t value) {
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
    p[2] = (uint8_t)(value >> 16);
    p[3] = (uint8_t)(value >> 24);
}

nub_status_t nub_header_decode(const uint8_t raw[NUB_HEADER_SIZE],
                               nub_header_t *header) {
    if (memcmp(raw, "NUB1", 4) != 0) {
        return NUB_STATUS_ARGUMENT;
    }

    header->major = raw[4];
    header->minor = raw[5];
    header->kind = raw[6];
    header->flags = raw[7];
    header->opcode = get16(raw + 8);
    header->status = get16(raw + 10);
    header->sequence = get32(raw + 12);
    header->payload_length = get32(raw + 16);
    if (header->major != NUB_PROTOCOL_MAJOR ||
        header->minor != NUB_PROTOCOL_MINOR) {
        return NUB_STATUS_VERSION;
    }
    if (header->kind != NUB_KIND_REQUEST || header->status != 0) {
        return NUB_STATUS_ARGUMENT;
    }
    if (header->payload_length > NUB_MAX_PAYLOAD) {
        return NUB_STATUS_LENGTH;
    }
    return NUB_STATUS_OK;
}

void nub_header_encode(uint8_t raw[NUB_HEADER_SIZE],
                       const nub_header_t *header) {
    memcpy(raw, "NUB1", 4);
    raw[4] = header->major;
    raw[5] = header->minor;
    raw[6] = header->kind;
    raw[7] = header->flags;
    put16(raw + 8, header->opcode);
    put16(raw + 10, header->status);
    put32(raw + 12, header->sequence);
    put32(raw + 16, header->payload_length);
}

void nub_event_encode(uint8_t raw[NUB_EVENT_SIZE], nub_event_type_t type,
                      uint8_t flags, uint32_t sequence, uint32_t timestamp_us,
                      uint32_t argument0, uint32_t argument1, uint32_t lost) {
    memset(raw, 0, NUB_EVENT_SIZE);
    memcpy(raw, "NUE1", 4);
    raw[4] = NUB_PROTOCOL_MAJOR;
    raw[5] = NUB_PROTOCOL_MINOR;
    raw[6] = (uint8_t)type;
    raw[7] = flags;
    put32(raw + 8, sequence);
    put32(raw + 12, timestamp_us);
    put32(raw + 16, argument0);
    put32(raw + 20, argument1);
    put32(raw + 24, lost);
}
