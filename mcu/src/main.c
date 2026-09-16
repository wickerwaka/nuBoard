#include "pico/stdlib.h"

// Both LEDs are wired from +3.3V_MCU to an RP2040 GPIO through a resistor,
// so driving a pin low turns its LED on.
#define LED_ON false
#define LED_OFF true

int main(void) {
    stdio_init_all();

    gpio_init(NUBOARD_LED_1_PIN);
    gpio_set_dir(NUBOARD_LED_1_PIN, GPIO_OUT);
    gpio_put(NUBOARD_LED_1_PIN, LED_OFF);

    gpio_init(NUBOARD_LED_2_PIN);
    gpio_set_dir(NUBOARD_LED_2_PIN, GPIO_OUT);
    gpio_put(NUBOARD_LED_2_PIN, LED_OFF);

    while (true) {
        gpio_put(NUBOARD_LED_1_PIN, LED_ON);
        gpio_put(NUBOARD_LED_2_PIN, LED_ON);
        sleep_ms(500);

        gpio_put(NUBOARD_LED_1_PIN, LED_OFF);
        gpio_put(NUBOARD_LED_2_PIN, LED_OFF);
        sleep_ms(500);
    }
}
