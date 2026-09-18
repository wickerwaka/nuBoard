#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "nub_protocol.h"
#include "nub_stream.h"
#include "runtime_link.h"
#include "sha256.h"

static void test_protocol_header(void) {
    nub_header_t original = {
        .major = NUB_PROTOCOL_MAJOR,
        .minor = NUB_PROTOCOL_MINOR,
        .kind = NUB_KIND_REQUEST,
        .flags = 0,
        .opcode = NUB_OP_CONFIG_DATA,
        .status = 0,
        .sequence = 0x12345678,
        .payload_length = NUB_MAX_PAYLOAD,
    };
    nub_header_t decoded = {0};
    uint8_t raw[NUB_HEADER_SIZE];

    nub_header_encode(raw, &original);
    assert(nub_header_decode(raw, &decoded) == NUB_STATUS_OK);
    assert(decoded.sequence == original.sequence);
    assert(decoded.payload_length == NUB_MAX_PAYLOAD);

    // A payload one byte above the protocol maximum must be rejected.
    raw[16] = 1;
    raw[17] = 0x10;
    assert(nub_header_decode(raw, &decoded) == NUB_STATUS_LENGTH);

    memcpy(raw, "BAD!", 4);
    assert(nub_header_decode(raw, &decoded) == NUB_STATUS_ARGUMENT);
}

static void test_sha256_streaming(void) {
    static const uint8_t expected[32] = {
        0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea,
        0x41, 0x41, 0x40, 0xde, 0x5d, 0xae, 0x22, 0x23,
        0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c,
        0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad,
    };
    sha256_ctx_t sha;
    uint8_t digest[32];

    sha256_init(&sha);
    sha256_update(&sha, "a", 1);
    sha256_update(&sha, "bc", 2);
    sha256_final(&sha, digest);

    assert(memcmp(digest, expected, sizeof(expected)) == 0);
}

static void test_split_and_coalesced_frames(void) {
    nub_header_t first = {
        .major = NUB_PROTOCOL_MAJOR,
        .minor = NUB_PROTOCOL_MINOR,
        .kind = NUB_KIND_REQUEST,
        .opcode = NUB_OP_GET_INFO,
        .sequence = 1,
        .payload_length = 3,
    };
    nub_header_t second = first;
    second.opcode = NUB_OP_GET_STATE;
    second.sequence = 2;
    second.payload_length = 0;

    uint8_t frames[NUB_HEADER_SIZE * 2 + 3];
    nub_header_encode(frames, &first);
    memcpy(frames + NUB_HEADER_SIZE, "abc", 3);
    nub_header_encode(frames + NUB_HEADER_SIZE + 3, &second);

    nub_stream_t stream = {0};
    nub_header_t decoded;
    const uint8_t *payload;
    size_t frame_length;

    // A partial header and a partial payload must both remain pending.
    assert(nub_stream_append(&stream, frames, 7));
    assert(nub_stream_peek(&stream, &decoded, &payload, &frame_length) ==
           NUB_STATUS_BUSY);
    assert(nub_stream_append(&stream, frames + 7, NUB_HEADER_SIZE - 5));
    assert(nub_stream_peek(&stream, &decoded, &payload, &frame_length) ==
           NUB_STATUS_BUSY);

    // Complete the first frame and coalesce the complete second frame.
    size_t remaining_offset = NUB_HEADER_SIZE - 5 + 7;
    assert(nub_stream_append(&stream, frames + remaining_offset,
                             sizeof(frames) - remaining_offset));
    assert(nub_stream_peek(&stream, &decoded, &payload, &frame_length) ==
           NUB_STATUS_OK);
    assert(decoded.sequence == 1);
    assert(memcmp(payload, "abc", 3) == 0);
    nub_stream_consume(&stream, frame_length);

    assert(nub_stream_peek(&stream, &decoded, &payload, &frame_length) ==
           NUB_STATUS_OK);
    assert(decoded.sequence == 2);
    nub_stream_consume(&stream, frame_length);
    assert(stream.length == 0);
}

static void test_crc32c(void) {
    assert(runtime_crc32c("123456789", 9, 0) == 0xe3069283u);
}

int main(void) {
    test_protocol_header();
    test_split_and_coalesced_frames();
    test_sha256_streaming();
    test_crc32c();

    puts("PASS: protocol, SHA-256, CRC32C");
    return 0;
}
