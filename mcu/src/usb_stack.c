#include "usb_stack.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "fpga_config.h"
#include "hardware/gpio.h"
#include "nub_stream.h"
#include "pico/stdlib.h"
#include "runtime_link.h"
#include "tusb.h"

#define GPIO_BIT(pin) (1u << (pin))
#define EVENT_QUEUE_DEPTH 8u

extern bool nub_event_endpoint_write(uint8_t const record[NUB_EVENT_SIZE]);

static uint8_t tx_buffer[NUB_STREAM_CAPACITY];
static uint8_t dispatch_buffer[NUB_MAX_PAYLOAD];
static nub_stream_t receive_stream;
static bool mounted_before;

static uint8_t event_queue[EVENT_QUEUE_DEPTH][NUB_EVENT_SIZE];
static unsigned event_head;
static unsigned event_tail;
static unsigned event_count;
static uint32_t event_sequence;
static uint32_t event_lost;

static bool vccb_enabled;
static uint8_t selector_snapshot;
static uint8_t stable_selector;
static uint8_t observed_selector;
static uint64_t selector_changed_at_us;

static uint32_t read_le32(const uint8_t *source) {
    return (uint32_t)source[0] | ((uint32_t)source[1] << 8) |
           ((uint32_t)source[2] << 16) | ((uint32_t)source[3] << 24);
}

static void write_le32(uint8_t *destination, uint32_t value) {
    destination[0] = (uint8_t)value;
    destination[1] = (uint8_t)(value >> 8);
    destination[2] = (uint8_t)(value >> 16);
    destination[3] = (uint8_t)(value >> 24);
}

static void hex_encode(char *destination, const uint8_t *source,
                       size_t length) {
    static const char digits[] = "0123456789abcdef";

    for (size_t index = 0; index < length; ++index) {
        destination[index * 2] = digits[source[index] >> 4];
        destination[index * 2 + 1] = digits[source[index] & 0x0f];
    }
    destination[length * 2] = '\0';
}

// Selector encoding is active-low and exclusive:
//   D0/D1 = 0/1 selects 5 V, 1/0 selects 3.3 V.
// Equal levels are either no selection or a conflict and are rejected.
static uint8_t read_selectors(void) {
    uint8_t d0 = gpio_get(NUBOARD_5V_SELECT_PIN) ? 1u : 0u;
    uint8_t d1 = gpio_get(NUBOARD_3V3_SELECT_PIN) ? 1u : 0u;
    return (uint8_t)((d0 << 1) | d1);
}

static int selector_voltage_mv(uint8_t raw) {
    if (raw == 1) {
        return 5000;
    }
    if (raw == 2) {
        return 3300;
    }
    return 0;
}

static void vccb_off(bool forced) {
    bool was_enabled = vccb_enabled;
    vccb_enabled = false;

    // D0=D1=1 is the hardware mux's disconnected state. Update both outputs
    // in one SIO write so shutdown never passes through an enabled rail.
    gpio_set_function(NUBOARD_VCCB_MUX_D0_PIN, GPIO_FUNC_SIO);
    gpio_set_function(NUBOARD_VCCB_MUX_D1_PIN, GPIO_FUNC_SIO);
    gpio_put_masked(GPIO_BIT(NUBOARD_VCCB_MUX_D0_PIN) |
                        GPIO_BIT(NUBOARD_VCCB_MUX_D1_PIN),
                    GPIO_BIT(NUBOARD_VCCB_MUX_D0_PIN) |
                        GPIO_BIT(NUBOARD_VCCB_MUX_D1_PIN));
    gpio_set_dir(NUBOARD_VCCB_MUX_D0_PIN, GPIO_OUT);
    gpio_set_dir(NUBOARD_VCCB_MUX_D1_PIN, GPIO_OUT);

    if (forced && was_enabled) {
        usb_queue_event(NUB_EVENT_VCCB_SHUTDOWN, selector_snapshot, 0);
    }
}

void usb_force_vccb_off(void) {
    vccb_off(true);
}

static void update_selector_stability(void) {
    uint8_t current = read_selectors();

    if (current != observed_selector) {
        observed_selector = current;
        selector_changed_at_us = time_us_64();
        stable_selector = 0xff;
        return;
    }

    if (time_us_64() - selector_changed_at_us >= 10000) {
        stable_selector = current;
    }
}

void usb_log(const char *format, ...) {
    if (!tud_cdc_connected()) {
        return;
    }

    char line[256];
    va_list arguments;
    va_start(arguments, format);
    int result = vsnprintf(line, sizeof(line), format, arguments);
    va_end(arguments);

    if (result <= 0) {
        return;
    }

    size_t length = (size_t)result;
    if (length >= sizeof(line)) {
        length = sizeof(line) - 1;
    }
    tud_cdc_write(line, (uint32_t)length);
    tud_cdc_write_flush();
}

void usb_queue_event(nub_event_type_t type, uint32_t argument0,
                     uint32_t argument1) {
    if (event_count == EVENT_QUEUE_DEPTH) {
        // Retain the newest state and make the loss visible to the host.
        event_tail = (event_tail + 1) % EVENT_QUEUE_DEPTH;
        --event_count;
        ++event_lost;
        type = NUB_EVENT_OVERFLOW;
        argument0 = event_lost;
        argument1 = 0;
    }

    nub_event_encode(event_queue[event_head], type, 0, ++event_sequence,
                     time_us_32(), argument0, argument1, event_lost);
    event_head = (event_head + 1) % EVENT_QUEUE_DEPTH;
    ++event_count;
}

static void send_response(const nub_header_t *request, nub_status_t status,
                          const void *payload, size_t length) {
    nub_header_t response = {
        .major = NUB_PROTOCOL_MAJOR,
        .minor = NUB_PROTOCOL_MINOR,
        .kind = NUB_KIND_RESPONSE,
        .flags = 0,
        .opcode = request->opcode,
        .status = status,
        .sequence = request->sequence,
        .payload_length = (uint32_t)length,
    };

    nub_header_encode(tx_buffer, &response);
    if (length != 0) {
        memcpy(tx_buffer + NUB_HEADER_SIZE, payload, length);
    }
    tud_vendor_write(tx_buffer, NUB_HEADER_SIZE + length);
    tud_vendor_write_flush();
}

static nub_status_t dispatch_config(const nub_header_t *header,
                                    const uint8_t *payload) {
    switch (header->opcode) {
        case NUB_OP_CONFIG_BEGIN:
            if (header->payload_length != 100 || payload[63] != 0) {
                return NUB_STATUS_LENGTH;
            }
            vccb_off(false);
            return fpga_config_begin((const char *)payload,
                                     read_le32(payload + 64), payload + 68);

        case NUB_OP_CONFIG_DATA:
            if (header->payload_length < 5) {
                return NUB_STATUS_LENGTH;
            }
            return fpga_config_data(read_le32(payload), payload + 4,
                                    header->payload_length - 4);

        case NUB_OP_CONFIG_END:
            if (header->payload_length != 0) {
                return NUB_STATUS_LENGTH;
            }
            return fpga_config_end();

        case NUB_OP_CONFIG_ABORT:
            if (header->payload_length != 0) {
                return NUB_STATUS_LENGTH;
            }
            vccb_off(false);
            fpga_off();
            return NUB_STATUS_OK;

        default:
            return NUB_STATUS_ARGUMENT;
    }
}

static nub_status_t dispatch_link(const nub_header_t *header,
                                  const uint8_t *payload, uint8_t *output,
                                  size_t *output_length) {
    switch (header->opcode) {
        case NUB_OP_FPGA_SEND:
            if (header->payload_length < 8 ||
                header->payload_length - 8 > FPGA_PACKET_MAX) {
                return NUB_STATUS_LENGTH;
            }
            if (!runtime_link_send(payload[0], payload[1],
                                   read_le32(payload + 4), payload + 8,
                                   header->payload_length - 8)) {
                if (runtime_link_healthy()) {
                    return NUB_STATUS_BUSY;
                }
                vccb_off(true);
                usb_queue_event(NUB_EVENT_LINK_FAULT, 0, 0);
                fpga_off();
                return NUB_STATUS_LINK;
            }
            return NUB_STATUS_OK;

        case NUB_OP_FPGA_RECV: {
            uint32_t status = runtime_link_status();
            if (!runtime_link_healthy()) {
                vccb_off(true);
                usb_queue_event(NUB_EVENT_LINK_FAULT, status, 0);
                fpga_off();
                return NUB_STATUS_LINK;
            }
            if ((status & 2u) == 0) {
                return NUB_STATUS_BUSY;
            }

            fpga_packet_header_t packet;
            size_t length;
            if (!runtime_link_receive(&packet, output + 8,
                                      NUB_MAX_PAYLOAD - 8, &length)) {
                vccb_off(true);
                usb_queue_event(NUB_EVENT_LINK_FAULT, status, 0);
                fpga_off();
                return NUB_STATUS_LINK;
            }

            output[0] = packet.channel;
            output[1] = (uint8_t)packet.flags;
            output[2] = 0;
            output[3] = 0;
            write_le32(output + 4, packet.tag);
            *output_length = length + 8;

            // READ_PACKET is non-destructive. Release the FPGA slot only
            // after the complete packet passed CRC verification.
            if (!runtime_link_ack(packet.tag)) {
                vccb_off(true);
                usb_queue_event(NUB_EVENT_LINK_FAULT, status, 0);
                fpga_off();
                return NUB_STATUS_LINK;
            }
            return NUB_STATUS_OK;
        }

        case NUB_OP_LINK_STATUS:
            write_le32(output, runtime_link_status());
            *output_length = 4;
            if (!runtime_link_healthy()) {
                vccb_off(true);
                usb_queue_event(NUB_EVENT_LINK_FAULT, 0, 0);
                fpga_off();
                return NUB_STATUS_LINK;
            }
            return NUB_STATUS_OK;

        default:
            return NUB_STATUS_ARGUMENT;
    }
}

static nub_status_t dispatch(const nub_header_t *header,
                             const uint8_t *payload, uint8_t *output,
                             size_t *output_length) {
    *output_length = 0;

    switch (header->opcode) {
        case NUB_OP_GET_INFO:
            *output_length = (size_t)snprintf(
                (char *)output, NUB_MAX_PAYLOAD,
                "{\"product\":\"nuBoard\",\"firmware\":\"1.0.0\","
                "\"protocol\":\"1.0\",\"max_payload\":4096,"
                "\"max_image\":33554432}");
            return NUB_STATUS_OK;

        case NUB_OP_GET_STATE: {
            fpga_state_t fpga;
            fpga_get_state(&fpga);
            uint8_t selector_raw = read_selectors();
            char digest[65];
            char core_uuid[33];
            hex_encode(digest, fpga.sha256, sizeof(fpga.sha256));
            hex_encode(core_uuid, fpga.identity.uuid,
                       sizeof(fpga.identity.uuid));
            *output_length = (size_t)snprintf(
                (char *)output, NUB_MAX_PAYLOAD,
                "{\"phase\":%u,\"selector_raw\":%u,\"selector_mv\":%d,"
                "\"vccb\":%s,\"rail_1v2\":%s,\"rail_3v3\":%s,"
                "\"cdone\":%s,\"heartbeat_us\":%lu,\"link\":%s,"
                "\"received\":%lu,\"size\":%lu,\"filename\":\"%s\","
                "\"sha256\":\"%s\",\"failure\":%lu,"
                "\"core_uuid\":\"%s\",\"core_version\":%lu,"
                "\"core_build\":%lu,\"mailbox_abi\":\"%u.%u\"}",
                fpga.phase, selector_raw, selector_voltage_mv(selector_raw),
                vccb_enabled ? "true" : "false",
                fpga.rail_1v2 ? "true" : "false",
                fpga.rail_3v3 ? "true" : "false",
                fpga.cdone ? "true" : "false",
                (unsigned long)fpga.heartbeat_period_us,
                fpga.link_healthy ? "true" : "false",
                (unsigned long)fpga.received_size,
                (unsigned long)fpga.expected_size, fpga.filename,
                digest, (unsigned long)fpga.failure_code, core_uuid,
                (unsigned long)fpga.identity.version,
                (unsigned long)fpga.identity.build,
                fpga.identity.abi_major, fpga.identity.abi_minor);
            return NUB_STATUS_OK;
        }

        case NUB_OP_CONFIG_BEGIN:
        case NUB_OP_CONFIG_DATA:
        case NUB_OP_CONFIG_END:
        case NUB_OP_CONFIG_ABORT:
            return dispatch_config(header, payload);

        case NUB_OP_FPGA_SEND:
        case NUB_OP_FPGA_RECV:
        case NUB_OP_LINK_STATUS:
            return dispatch_link(header, payload, output, output_length);

        case NUB_OP_VCCB_ENABLE: {
            if (!fpga_is_configured()) {
                return NUB_STATUS_STATE;
            }
            if (stable_selector != read_selectors() ||
                selector_voltage_mv(stable_selector) == 0) {
                return NUB_STATUS_SELECTOR;
            }

            selector_snapshot = stable_selector;
            uint32_t mux_mask = GPIO_BIT(NUBOARD_VCCB_MUX_D0_PIN) |
                                GPIO_BIT(NUBOARD_VCCB_MUX_D1_PIN);
            uint32_t mux_levels = 0;
            if (selector_voltage_mv(stable_selector) == 3300) {
                mux_levels = GPIO_BIT(NUBOARD_VCCB_MUX_D1_PIN);
            }
            gpio_put_masked(mux_mask, mux_levels);
            vccb_enabled = true;
            return NUB_STATUS_OK;
        }

        case NUB_OP_VCCB_DISABLE:
            vccb_off(false);
            return NUB_STATUS_OK;

        case NUB_OP_POWER_OFF:
            vccb_off(false);
            fpga_off();
            return NUB_STATUS_OK;

        default:
            return NUB_STATUS_ARGUMENT;
    }
}

static void bulk_task(void) {
    while (tud_vendor_available() &&
           nub_stream_capacity(&receive_stream) != 0) {
        size_t capacity = nub_stream_capacity(&receive_stream);
        uint32_t received = tud_vendor_read(
            receive_stream.data + receive_stream.length,
            (uint32_t)capacity);
        receive_stream.length += received;
    }

    // The buffer supports both split frames and several coalesced frames.
    while (true) {
        nub_header_t header = {0};
        const uint8_t *payload;
        size_t frame_length;
        nub_status_t parsed = nub_stream_peek(
            &receive_stream, &header, &payload, &frame_length);

        if (parsed == NUB_STATUS_BUSY) {
            return;
        }
        if (parsed != NUB_STATUS_OK) {
            if (receive_stream.length >= 4 &&
                memcmp(receive_stream.data, "NUB1", 4) == 0) {
                send_response(&header, parsed, NULL, 0);
            }
            nub_stream_clear(&receive_stream);
            return;
        }

        size_t response_length;
        nub_status_t status = dispatch(&header, payload, dispatch_buffer,
                                       &response_length);
        send_response(&header, status, dispatch_buffer, response_length);
        nub_stream_consume(&receive_stream, frame_length);
    }
}

static void cdc_task(void) {
    static char line[64];
    static size_t length;

    while (tud_cdc_available()) {
        char character;
        if (tud_cdc_read(&character, 1) != 1) {
            break;
        }

        if (character == '\r' || character == '\n') {
            line[length] = '\0';
            if (strcmp(line, "help") == 0) {
                usb_log("commands: help info status (read-only)\r\n");
            } else if (strcmp(line, "info") == 0) {
                usb_log("nuBoard firmware 1.0.0 protocol 1.0\r\n");
            } else if (strcmp(line, "status") == 0) {
                fpga_state_t fpga;
                fpga_get_state(&fpga);
                usb_log("phase=%u bytes=%lu/%lu link=%u vccb=%u\r\n",
                        fpga.phase, (unsigned long)fpga.received_size,
                        (unsigned long)fpga.expected_size,
                        fpga.link_healthy, vccb_enabled);
            } else if (length != 0) {
                usb_log("error: read-only console; use nuboard CLI\r\n");
            }
            length = 0;
        } else if (length < sizeof(line) - 1 && character >= ' ' &&
                   character <= '~') {
            line[length++] = character;
        }
    }
}

void usb_stack_init(void) {
    gpio_init(NUBOARD_5V_SELECT_PIN);
    gpio_init(NUBOARD_3V3_SELECT_PIN);
    gpio_set_dir(NUBOARD_5V_SELECT_PIN, GPIO_IN);
    gpio_set_dir(NUBOARD_3V3_SELECT_PIN, GPIO_IN);
    gpio_pull_up(NUBOARD_5V_SELECT_PIN);
    gpio_pull_up(NUBOARD_3V3_SELECT_PIN);

    observed_selector = read_selectors();
    stable_selector = 0xff;
    selector_changed_at_us = time_us_64();

    gpio_init(NUBOARD_VCCB_MUX_D0_PIN);
    gpio_init(NUBOARD_VCCB_MUX_D1_PIN);
    vccb_off(false);

    fpga_set_event_callback(usb_queue_event);
    tusb_init();
}

bool usb_stack_mounted(void) {
    return tud_mounted();
}

void usb_stack_task(void) {
    tud_task();

    bool mounted = tud_mounted();
    if (mounted_before && !mounted) {
        // Physical USB reset/unmount is a safety boundary. A host process
        // exiting while USB remains mounted intentionally does not reach here.
        vccb_off(true);
        fpga_off();
    }
    mounted_before = mounted;

    update_selector_stability();

    bulk_task();
    cdc_task();

    if (vccb_enabled && read_selectors() != selector_snapshot) {
        vccb_off(true);
    }

    if (event_count != 0 &&
        nub_event_endpoint_write(event_queue[event_tail])) {
        event_tail = (event_tail + 1) % EVENT_QUEUE_DEPTH;
        --event_count;
    }
}
