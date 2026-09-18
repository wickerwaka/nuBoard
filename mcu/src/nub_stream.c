#include "nub_stream.h"

#include <string.h>

size_t nub_stream_capacity(const nub_stream_t *stream) {
    return sizeof(stream->data) - stream->length;
}

bool nub_stream_append(nub_stream_t *stream, const void *data,
                       size_t length) {
    if (length > nub_stream_capacity(stream)) {
        return false;
    }

    memcpy(stream->data + stream->length, data, length);
    stream->length += length;
    return true;
}

nub_status_t nub_stream_peek(nub_stream_t *stream, nub_header_t *header,
                             const uint8_t **payload,
                             size_t *frame_length) {
    if (stream->length < NUB_HEADER_SIZE) {
        return NUB_STATUS_BUSY;
    }

    nub_status_t status = nub_header_decode(stream->data, header);
    if (status != NUB_STATUS_OK) {
        return status;
    }

    *frame_length = NUB_HEADER_SIZE + header->payload_length;
    if (stream->length < *frame_length) {
        return NUB_STATUS_BUSY;
    }

    *payload = stream->data + NUB_HEADER_SIZE;
    return NUB_STATUS_OK;
}

void nub_stream_consume(nub_stream_t *stream, size_t frame_length) {
    if (frame_length > stream->length) {
        frame_length = stream->length;
    }

    memmove(stream->data, stream->data + frame_length,
            stream->length - frame_length);
    stream->length -= frame_length;
}

void nub_stream_clear(nub_stream_t *stream) {
    stream->length = 0;
}
