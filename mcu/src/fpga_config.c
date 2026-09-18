#include "fpga_config.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "fpga_spi.pio.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "hardware/regs/pio.h"
#include "pico/stdlib.h"
#include "sha256.h"

#define GPIO_BIT(pin) (1u << (pin))

#define RAIL_DELAY_US 5000u
#define RESET_LOW_US 10u
#define RESET_TIMEOUT_US 10000u
#define RESET_RELEASE_US 10u
#define STREAM_TIMEOUT_MS 5000u
#define CDONE_TIMEOUT_US 100000u
#define HEARTBEAT_TIMEOUT_US 500000u
#define HEARTBEAT_MIN_US 80000u
#define HEARTBEAT_MAX_US 120000u
#define TRAILER_BYTES 64u
#define CONFIG_SPI_HZ 25000000u

#define CONFIG_DATA_MASK                                                     \
    (GPIO_BIT(NUBOARD_FPGA_CDI0_PIN) | GPIO_BIT(NUBOARD_FPGA_CDI1_PIN) |   \
     GPIO_BIT(NUBOARD_FPGA_CDI2_PIN) | GPIO_BIT(NUBOARD_FPGA_CDI3_PIN))

#define CONFIG_FIXED_OUTPUT_MASK                                             \
    (GPIO_BIT(NUBOARD_FPGA_CSI_PIN) |                                      \
     GPIO_BIT(NUBOARD_FPGA_CRESET_N_PIN) |                                 \
     GPIO_BIT(NUBOARD_FPGA_SS_N_PIN) |                                     \
     GPIO_BIT(NUBOARD_FPGA_CBUS0_PIN) |                                    \
     GPIO_BIT(NUBOARD_FPGA_CBUS1_PIN) |                                    \
     GPIO_BIT(NUBOARD_FPGA_CBUS2_PIN) | GPIO_BIT(NUBOARD_FPGA_TCK_PIN) |   \
     GPIO_BIT(NUBOARD_FPGA_TDI_PIN) | GPIO_BIT(NUBOARD_FPGA_TMS_PIN))

#define CONFIG_FIXED_LEVELS                                                  \
    (GPIO_BIT(NUBOARD_FPGA_CSI_PIN) | GPIO_BIT(NUBOARD_FPGA_CBUS0_PIN) |   \
     GPIO_BIT(NUBOARD_FPGA_CBUS2_PIN) | GPIO_BIT(NUBOARD_FPGA_TDI_PIN) |   \
     GPIO_BIT(NUBOARD_FPGA_TMS_PIN))

static PIO config_pio = pio0;
static uint config_sm;
static uint config_program_offset;
static int config_dma = -1;

static fpga_state_t state;
static sha256_ctx_t hash;
static uint8_t expected_digest[32];

// Configuration intentionally uses one bounded host chunk. PIO stalls before
// its next OUT instruction when the FIFO is empty, leaving CCK high and making
// an arbitrary USB inter-chunk pause safe.
static uint8_t chunk[NUB_CONFIG_DATA_MAX];
static size_t chunk_length;
static bool chunk_ready;
static bool dma_active;
static bool end_received;
static bool final_stall_armed;
static const uint8_t trailer[TRAILER_BYTES] = {0};

static absolute_time_t deadline;
static absolute_time_t phase_started;
static absolute_time_t heartbeat_last_rise;
static bool heartbeat_level;
static bool heartbeat_fell_since_rise;
static unsigned heartbeat_valid_periods;

static void (*event_callback)(nub_event_type_t type, uint32_t argument0,
                              uint32_t argument1);

static bool deadline_reached(void) {
    return absolute_time_diff_us(get_absolute_time(), deadline) <= 0;
}

static void set_deadline_us(uint32_t delay_us) {
    phase_started = get_absolute_time();
    deadline = delayed_by_us(phase_started, delay_us);
}

static void emit_event(nub_event_type_t type, uint32_t argument0,
                       uint32_t argument1) {
    if (event_callback != NULL) {
        event_callback(type, argument0, argument1);
    }
}

static void park_shared_pins(void) {
    runtime_link_disable();
    gpio_put(NUBOARD_FPGA_CRESET_N_PIN, false);

    for (uint pin = NUBOARD_FPGA_CDI0_PIN;
         pin <= NUBOARD_FPGA_TMS_PIN; ++pin) {
        gpio_set_function(pin, GPIO_FUNC_SIO);
        gpio_set_dir(pin, pin == NUBOARD_FPGA_CRESET_N_PIN ? GPIO_OUT
                                                           : GPIO_IN);
        gpio_disable_pulls(pin);
    }
}

static void establish_config_levels(void) {
    runtime_link_disable();

    // Establish passive-x4 mode and all idle levels before CRESET_N rises.
    // Values are written before directions to avoid output glitches.
    gpio_put_masked(CONFIG_FIXED_OUTPUT_MASK, CONFIG_FIXED_LEVELS);
    gpio_put_masked(CONFIG_DATA_MASK, 0);
    gpio_put(NUBOARD_FPGA_CCK_PIN, true);

    for (uint pin = NUBOARD_FPGA_CDI0_PIN;
         pin <= NUBOARD_FPGA_CDI3_PIN; ++pin) {
        gpio_set_function(pin, GPIO_FUNC_SIO);
        gpio_set_dir(pin, GPIO_OUT);
    }
    gpio_set_function(NUBOARD_FPGA_CCK_PIN, GPIO_FUNC_SIO);
    gpio_set_dir(NUBOARD_FPGA_CCK_PIN, GPIO_OUT);
    gpio_set_dir_out_masked(CONFIG_FIXED_OUTPUT_MASK);

    gpio_set_dir(NUBOARD_FPGA_CSO_PIN, GPIO_IN);
    gpio_set_dir(NUBOARD_FPGA_CDONE_PIN, GPIO_IN);
    gpio_set_dir(NUBOARD_FPGA_NSTATUS_PIN, GPIO_IN);
}

static void stop_dma(void) {
    if (config_dma >= 0) {
        dma_channel_abort((uint)config_dma);
    }
    pio_sm_set_enabled(config_pio, config_sm, false);
    pio_sm_clear_fifos(config_pio, config_sm);
    dma_active = false;
    final_stall_armed = false;
}

static void begin_shutdown(uint32_t failure_code) {
    bool was_powered = state.rail_1v2 || state.rail_3v3;

    stop_dma();
    gpio_set_irq_enabled(NUBOARD_FPGA_NSTATUS_PIN, GPIO_IRQ_EDGE_FALL,
                         false);
    gpio_put(NUBOARD_FPGA_CRESET_N_PIN, false);
    park_shared_pins();

    // Fail closed in the required order: VCCB is handled by the USB/power
    // layer, then reset, 3.3 V, a 5 ms wait, and finally 1.2 V.
    gpio_put(NUBOARD_FPGA_3V3_EN_PIN, false);
    state.rail_3v3 = false;
    state.link_healthy = false;
    state.failure_code = failure_code;

    if (failure_code != 0) {
        emit_event(NUB_EVENT_CONFIG_FAILURE, failure_code,
                   state.received_size);
    }

    if (was_powered) {
        state.phase = FPGA_PHASE_SHUTDOWN_3V3;
        set_deadline_us(RAIL_DELAY_US);
    } else {
        state.phase = FPGA_PHASE_OFF;
    }
}

static uint32_t tx_stall_mask(void) {
    return 1u << (PIO_FDEBUG_TXSTALL_LSB + config_sm);
}

static void prepare_config_pio(void) {
    stop_dma();

    pio_sm_config config =
        fpga_spi_program_get_default_config(config_program_offset);
    sm_config_set_out_pins(&config, NUBOARD_FPGA_CDI0_PIN, 4);
    sm_config_set_sideset_pins(&config, NUBOARD_FPGA_CCK_PIN);
    sm_config_set_out_shift(&config, false, true, 8);
    sm_config_set_fifo_join(&config, PIO_FIFO_JOIN_TX);
    sm_config_set_clkdiv(
        &config,
        (float)clock_get_hz(clk_sys) / (2.0f * (float)CONFIG_SPI_HZ));

    for (uint pin = NUBOARD_FPGA_CDI0_PIN;
         pin <= NUBOARD_FPGA_CDI3_PIN; ++pin) {
        pio_gpio_init(config_pio, pin);
    }
    pio_gpio_init(config_pio, NUBOARD_FPGA_CCK_PIN);
    pio_sm_init(config_pio, config_sm, config_program_offset, &config);
    pio_sm_set_consecutive_pindirs(config_pio, config_sm,
                                   NUBOARD_FPGA_CDI0_PIN, 4, true);
    pio_sm_set_consecutive_pindirs(config_pio, config_sm,
                                   NUBOARD_FPGA_CCK_PIN, 1, true);

    config_pio->fdebug = tx_stall_mask();
    pio_sm_set_enabled(config_pio, config_sm, true);
}

static void start_dma(const uint8_t *data, size_t length) {
    dma_channel_config config =
        dma_channel_get_default_config((uint)config_dma);
    channel_config_set_transfer_data_size(&config, DMA_SIZE_8);
    channel_config_set_read_increment(&config, true);
    channel_config_set_write_increment(&config, false);
    channel_config_set_dreq(
        &config, pio_get_dreq(config_pio, config_sm, true));

    dma_channel_configure((uint)config_dma, &config,
                          &config_pio->txf[config_sm], data, length, true);
    dma_active = true;
    final_stall_armed = false;
}

static bool dma_final_edge_emitted(void) {
    if (!dma_active) {
        return false;
    }

    if (dma_channel_hw_addr((uint)config_dma)->transfer_count != 0) {
        // TXSTALL is sticky. Ignore starvation indications while DMA still
        // owns bytes; they do not prove the current chunk has left the FIFO.
        config_pio->fdebug = tx_stall_mask();
        return false;
    }

    if (!final_stall_armed) {
        config_pio->fdebug = tx_stall_mask();
        final_stall_armed = true;
        return false;
    }
    if ((config_pio->fdebug & tx_stall_mask()) == 0) {
        return false;
    }

    dma_active = false;
    return true;
}

void fpga_init(void) {
    memset(&state, 0, sizeof(state));
    state.phase = FPGA_PHASE_OFF;

    for (uint pin = NUBOARD_FPGA_CDI0_PIN;
         pin <= NUBOARD_FPGA_TMS_PIN; ++pin) {
        gpio_init(pin);
    }

    config_sm = pio_claim_unused_sm(config_pio, true);
    config_program_offset = pio_add_program(config_pio, &fpga_spi_program);
    config_dma = dma_claim_unused_channel(true);
    park_shared_pins();
}

void fpga_set_event_callback(
    void (*callback)(nub_event_type_t, uint32_t, uint32_t)) {
    event_callback = callback;
}

nub_status_t fpga_config_begin(const char *filename, uint32_t size,
                               const uint8_t digest[32]) {
    size_t name_length = strnlen(filename, sizeof(state.filename));
    if (name_length == 0 || name_length >= sizeof(state.filename) ||
        size == 0 || size > NUB_MAX_IMAGE_SIZE) {
        return NUB_STATUS_ARGUMENT;
    }
    if (state.phase != FPGA_PHASE_OFF) {
        return NUB_STATUS_STATE;
    }

    memset(&state, 0, sizeof(state));
    state.phase = FPGA_PHASE_POWER_1V2;
    state.expected_size = size;
    memcpy(state.filename, filename, name_length + 1);
    memcpy(expected_digest, digest, sizeof(expected_digest));
    sha256_init(&hash);

    chunk_ready = false;
    dma_active = false;
    end_received = false;

    gpio_put(NUBOARD_FPGA_CRESET_N_PIN, false);
    park_shared_pins();
    gpio_put(NUBOARD_FPGA_1V2_EN_PIN, true);
    state.rail_1v2 = true;
    set_deadline_us(RAIL_DELAY_US);

    emit_event(NUB_EVENT_STATE, FPGA_PHASE_POWER_1V2, 0);
    return NUB_STATUS_OK;
}

nub_status_t fpga_config_data(uint32_t offset, const uint8_t *data,
                              size_t length) {
    if (state.phase == FPGA_PHASE_OFF || state.phase >= FPGA_PHASE_CDONE) {
        return NUB_STATUS_STATE;
    }
    if (end_received) {
        return NUB_STATUS_STATE;
    }
    if (offset != state.received_size) {
        return NUB_STATUS_ARGUMENT;
    }
    if (length == 0 || length > NUB_CONFIG_DATA_MAX ||
        offset + length > state.expected_size) {
        return NUB_STATUS_LENGTH;
    }
    if (chunk_ready || dma_active) {
        return NUB_STATUS_BUSY;
    }

    memcpy(chunk, data, length);
    chunk_length = length;
    chunk_ready = true;
    sha256_update(&hash, data, length);
    state.received_size += (uint32_t)length;
    deadline = make_timeout_time_ms(STREAM_TIMEOUT_MS);
    return NUB_STATUS_OK;
}

nub_status_t fpga_config_end(void) {
    if (state.received_size != state.expected_size || end_received) {
        return NUB_STATUS_STATE;
    }

    uint8_t actual_digest[32];
    sha256_final(&hash, actual_digest);
    if (memcmp(actual_digest, expected_digest, sizeof(actual_digest)) != 0) {
        begin_shutdown(NUB_STATUS_CHECKSUM);
        return NUB_STATUS_CHECKSUM;
    }

    memcpy(state.sha256, actual_digest, sizeof(actual_digest));
    end_received = true;
    return NUB_STATUS_OK;
}

void fpga_off(void) {
    begin_shutdown(0);
}

bool fpga_is_configured(void) {
    return state.phase == FPGA_PHASE_CONFIGURED && state.link_healthy;
}

void fpga_get_state(fpga_state_t *output) {
    state.cdone = gpio_get(NUBOARD_FPGA_CDONE_PIN);
    *output = state;
}

bool fpga_manual_change_allowed(void) {
    return state.phase == FPGA_PHASE_OFF ||
           state.phase == FPGA_PHASE_CONFIGURED;
}

void fpga_note_manual_rail_change(void) {
    begin_shutdown(NUB_STATUS_STATE);
}

void fpga_print_status(void) {
    printf("fpga phase=%u rails=%u/%u bytes=%" PRIu32 "/%" PRIu32
           " CDONE=%u heartbeat=%" PRIu32 " link=%u failure=%" PRIu32
           "\n",
           state.phase, state.rail_1v2, state.rail_3v3,
           state.received_size, state.expected_size,
           gpio_get(NUBOARD_FPGA_CDONE_PIN), state.heartbeat_period_us,
           state.link_healthy, state.failure_code);
}

static void poll_heartbeat(void) {
    bool level = gpio_get(NUBOARD_FPGA_CSO_PIN);
    if (level != heartbeat_level) {
        heartbeat_level = level;
        if (!level) {
            heartbeat_fell_since_rise = true;
        } else {
            absolute_time_t now = get_absolute_time();
            if (!is_nil_time(heartbeat_last_rise)) {
                int64_t period =
                    absolute_time_diff_us(heartbeat_last_rise, now);
                state.heartbeat_period_us = (uint32_t)period;
                if (!heartbeat_fell_since_rise ||
                    period < HEARTBEAT_MIN_US ||
                    period > HEARTBEAT_MAX_US) {
                    begin_shutdown(NUB_STATUS_LINK);
                    return;
                }
                ++heartbeat_valid_periods;
            }
            heartbeat_last_rise = now;
            heartbeat_fell_since_rise = false;
            if (heartbeat_valid_periods >= 3) {
                state.phase = FPGA_PHASE_IDENTITY;
            }
        }
    }

    if (state.phase == FPGA_PHASE_HEARTBEAT && deadline_reached()) {
        begin_shutdown(NUB_STATUS_TIMEOUT);
    }
}

void fpga_poll(void) {
    switch (state.phase) {
        case FPGA_PHASE_OFF:
        case FPGA_PHASE_CONFIGURED:
            return;

        case FPGA_PHASE_POWER_1V2:
            if (deadline_reached()) {
                establish_config_levels();
                gpio_put(NUBOARD_FPGA_3V3_EN_PIN, true);
                state.rail_3v3 = true;
                state.phase = FPGA_PHASE_POWER_3V3;
                set_deadline_us(RAIL_DELAY_US);
            }
            return;

        case FPGA_PHASE_POWER_3V3:
            if (deadline_reached()) {
                establish_config_levels();
                gpio_put(NUBOARD_FPGA_CRESET_N_PIN, false);
                state.phase = FPGA_PHASE_RESET_ACK;
                set_deadline_us(RESET_TIMEOUT_US);
            }
            return;

        case FPGA_PHASE_RESET_ACK: {
            int64_t held_us =
                absolute_time_diff_us(phase_started, get_absolute_time());
            if (!gpio_get(NUBOARD_FPGA_CDONE_PIN) &&
                held_us >= RESET_LOW_US) {
                gpio_put(NUBOARD_FPGA_CRESET_N_PIN, true);
                state.phase = FPGA_PHASE_RESET_RELEASE;
                set_deadline_us(RESET_RELEASE_US);
            } else if (deadline_reached()) {
                begin_shutdown(NUB_STATUS_TIMEOUT);
            }
            return;
        }

        case FPGA_PHASE_RESET_RELEASE:
            if (deadline_reached()) {
                prepare_config_pio();
                state.phase = FPGA_PHASE_STREAM;
                deadline = make_timeout_time_ms(STREAM_TIMEOUT_MS);
            }
            return;

        case FPGA_PHASE_STREAM:
            if (dma_active && dma_final_edge_emitted()) {
                chunk_ready = false;
            }
            if (!dma_active && chunk_ready) {
                start_dma(chunk, chunk_length);
            } else if (!dma_active && !chunk_ready && end_received) {
                start_dma(trailer, sizeof(trailer));
                state.phase = FPGA_PHASE_TRAILER;
            } else if (!dma_active && !chunk_ready && deadline_reached()) {
                begin_shutdown(NUB_STATUS_TIMEOUT);
            }
            return;

        case FPGA_PHASE_TRAILER:
            if (dma_final_edge_emitted()) {
                stop_dma();
                state.phase = FPGA_PHASE_CDONE;
                set_deadline_us(CDONE_TIMEOUT_US);
            }
            return;

        case FPGA_PHASE_CDONE:
            if (gpio_get(NUBOARD_FPGA_CDONE_PIN)) {
                state.phase = FPGA_PHASE_CDONE_SETTLE;
                set_deadline_us(100);
            } else if (deadline_reached()) {
                begin_shutdown(NUB_STATUS_CONFIGURATION);
            }
            return;

        case FPGA_PHASE_CDONE_SETTLE:
            if (deadline_reached()) {
                heartbeat_level = gpio_get(NUBOARD_FPGA_CSO_PIN);
                heartbeat_last_rise = nil_time;
                heartbeat_valid_periods = 0;
                heartbeat_fell_since_rise = false;
                state.phase = FPGA_PHASE_HEARTBEAT;
                set_deadline_us(HEARTBEAT_TIMEOUT_US);
            }
            return;

        case FPGA_PHASE_HEARTBEAT:
            poll_heartbeat();
            return;

        case FPGA_PHASE_IDENTITY:
            runtime_link_init();
            if (!runtime_link_qualify(&state.identity)) {
                begin_shutdown(NUB_STATUS_LINK);
                return;
            }
            state.link_healthy = true;
            state.failure_code = 0;
            state.phase = FPGA_PHASE_CONFIGURED;
            gpio_set_irq_enabled(NUBOARD_FPGA_NSTATUS_PIN,
                                 GPIO_IRQ_EDGE_FALL, true);
            emit_event(NUB_EVENT_STATE, FPGA_PHASE_CONFIGURED,
                       state.identity.version);
            return;

        case FPGA_PHASE_SHUTDOWN_3V3:
            if (deadline_reached()) {
                gpio_put(NUBOARD_FPGA_1V2_EN_PIN, false);
                state.rail_1v2 = false;
                state.phase = FPGA_PHASE_OFF;
                emit_event(NUB_EVENT_STATE, FPGA_PHASE_OFF,
                           state.failure_code);
            }
            return;
    }
}
