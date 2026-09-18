#include <stddef.h>
#include <stdint.h>

uint32_t runtime_crc32c(const void *source, size_t length, uint32_t crc) {
    const uint8_t *data = source;
    crc = ~crc;
    while (length--) {
        crc ^= *data++;
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0x82f63b78u & (uint32_t)-(int32_t)(crc & 1));
        }
    }
    return ~crc;
}
