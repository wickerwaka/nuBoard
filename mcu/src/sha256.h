#ifndef NUBOARD_SHA256_H
#define NUBOARD_SHA256_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t state[8];
    uint64_t bit_count;
    uint8_t buffer[64];
} sha256_ctx_t;

void sha256_init(sha256_ctx_t *ctx);
void sha256_update(sha256_ctx_t *ctx, const void *data, size_t length);
void sha256_final(sha256_ctx_t *ctx, uint8_t digest[32]);

#endif
