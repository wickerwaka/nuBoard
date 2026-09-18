#ifndef NUBOARD_STREAM_H
#define NUBOARD_STREAM_H

#include <stddef.h>
#include <stdint.h>

#include "nub_protocol.h"

#define NUB_STREAM_CAPACITY (NUB_HEADER_SIZE + NUB_MAX_PAYLOAD)

typedef struct {
    uint8_t data[NUB_STREAM_CAPACITY];
    size_t length;
} nub_stream_t;

size_t nub_stream_capacity(const nub_stream_t *stream);
bool nub_stream_append(nub_stream_t *stream, const void *data, size_t length);

// Returns BUSY when a complete frame has not arrived yet. On success, payload
// points into the stream and remains valid until nub_stream_consume().
nub_status_t nub_stream_peek(nub_stream_t *stream, nub_header_t *header,
                             const uint8_t **payload, size_t *frame_length);
void nub_stream_consume(nub_stream_t *stream, size_t frame_length);
void nub_stream_clear(nub_stream_t *stream);

#endif
