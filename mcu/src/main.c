#include <stdbool.h>
#include <stdint.h>

#include "fpga_config.h"
#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "pico/stdlib.h"
#include "runtime_link.h"
#include "usb_stack.h"

#define GPIO_BIT(pin) (1u << (pin))
#define CONTROL_MASK                                                         \
    (GPIO_BIT(NUBOARD_FPGA_CRESET_N_PIN) | GPIO_BIT(NUBOARD_LED_1_PIN) |    \
     GPIO_BIT(NUBOARD_LED_2_PIN) | GPIO_BIT(NUBOARD_FPGA_1V2_EN_PIN) |      \
     GPIO_BIT(NUBOARD_FPGA_3V3_EN_PIN))
#define CONTROL_OFF_LEVELS                                                   \
    (GPIO_BIT(NUBOARD_LED_1_PIN) | GPIO_BIT(NUBOARD_LED_2_PIN))

static volatile bool fpga_irq_latched;

static void gpio_irq(uint gpio, uint32_t events) {
    if (gpio == NUBOARD_FPGA_NSTATUS_PIN &&
        (events & GPIO_IRQ_EDGE_FALL) != 0) {
        // The ISR deliberately does no SPI or USB work. The main loop samples
        // mailbox status and produces the event record.
        fpga_irq_latched = true;
    }
}

int main(void) {
    gpio_init_mask(CONTROL_MASK);
    gpio_put_masked(CONTROL_MASK, CONTROL_OFF_LEVELS);
    gpio_set_dir_out_masked(CONTROL_MASK);

    fpga_init();
    gpio_set_irq_enabled_with_callback(NUBOARD_FPGA_NSTATUS_PIN,
                                       GPIO_IRQ_EDGE_FALL, false, &gpio_irq);
    // Registering a callback while its GPIO is disabled does not enable the
    // bank interrupt in the NVIC. Configuration controls the GPIO10 mask, but
    // the bank itself must remain enabled for the later runtime handoff.
    irq_set_enabled(IO_IRQ_BANK0, true);
    usb_stack_init();

    while (true) {
        usb_stack_task();
        fpga_poll();

        if (fpga_irq_latched) {
            fpga_irq_latched = false;
            uint32_t status = runtime_link_status();
            usb_queue_event(NUB_EVENT_FPGA_IRQ, status, 0);

            if (!runtime_link_healthy()) {
                usb_queue_event(NUB_EVENT_LINK_FAULT, status, 0);
                usb_force_vccb_off();
                fpga_off();
            }
        }

        tight_loop_contents();
    }
}
