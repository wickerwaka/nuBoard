#ifndef NUBOARD_FPGA_CONFIG_H
#define NUBOARD_FPGA_CONFIG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "nub_protocol.h"
#include "runtime_link.h"

typedef enum {
    FPGA_PHASE_OFF = 0,
    FPGA_PHASE_POWER_1V2,
    FPGA_PHASE_POWER_3V3,
    FPGA_PHASE_RESET_ACK,
    FPGA_PHASE_RESET_RELEASE,
    FPGA_PHASE_STREAM,
    FPGA_PHASE_TRAILER,
    FPGA_PHASE_CDONE,
    FPGA_PHASE_CDONE_SETTLE,
    FPGA_PHASE_HEARTBEAT,
    FPGA_PHASE_IDENTITY,
    FPGA_PHASE_CONFIGURED,
    FPGA_PHASE_SHUTDOWN_3V3,
} fpga_phase_t;

typedef struct {
    fpga_phase_t phase;
    uint32_t expected_size;
    uint32_t received_size;
    uint32_t heartbeat_period_us;
    uint32_t failure_code;
    bool rail_1v2;
    bool rail_3v3;
    bool cdone;
    bool link_healthy;
    char filename[64];
    uint8_t sha256[32];
    fpga_identity_t identity;
} fpga_state_t;

void fpga_init(void);
void fpga_poll(void);
void fpga_print_status(void);
nub_status_t fpga_config_begin(const char *filename, uint32_t size,
                               const uint8_t digest[32]);
nub_status_t fpga_config_data(uint32_t offset, const uint8_t *data,
                              size_t length);
nub_status_t fpga_config_end(void);
void fpga_off(void);
void fpga_get_state(fpga_state_t *state);
bool fpga_is_configured(void);
void fpga_set_event_callback(
    void (*callback)(nub_event_type_t, uint32_t, uint32_t));

// Manual rail and VCCB commands call these helpers to prevent a console
// command from changing power while the asynchronous configuration engine is
// active.  A manual FPGA rail change also invalidates a configured image and
// parks every shared configuration pin.
bool fpga_manual_change_allowed(void);
void fpga_note_manual_rail_change(void);

#endif
