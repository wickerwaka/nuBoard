#ifndef NUBOARD_USB_STACK_H
#define NUBOARD_USB_STACK_H

#include <stdbool.h>
#include <stdint.h>

#include "nub_protocol.h"

void usb_stack_init(void);
void usb_stack_task(void);
void usb_queue_event(nub_event_type_t type, uint32_t argument0,
                     uint32_t argument1);
void usb_log(const char *format, ...);
bool usb_stack_mounted(void);

// Immediately remove VCCB after a fatal FPGA-side failure. The caller remains
// responsible for shutting down the FPGA rails.
void usb_force_vccb_off(void);

#endif
