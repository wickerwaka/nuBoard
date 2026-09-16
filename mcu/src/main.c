#include <stdio.h>
#include <string.h>

#include "pico/stdlib.h"

#define GPIO_BIT(pin) (1u << (pin))

#define CONTROL_GPIO_MASK                                                   \
    (GPIO_BIT(NUBOARD_FPGA_CRESET_N_PIN) |                                 \
     GPIO_BIT(NUBOARD_LED_1_PIN) | GPIO_BIT(NUBOARD_LED_2_PIN) |           \
     GPIO_BIT(NUBOARD_FPGA_1V2_EN_PIN) |                                   \
     GPIO_BIT(NUBOARD_FPGA_3V3_EN_PIN) |                                   \
     GPIO_BIT(NUBOARD_VCCB_MUX_D0_PIN) |                                   \
     GPIO_BIT(NUBOARD_VCCB_MUX_D1_PIN))

// CRESET_N stays low. LEDs are active low, FPGA enables are active high, and
// VCCB is off at D0=D1=1.
#define CONTROL_OFF_LEVELS                                                  \
    (GPIO_BIT(NUBOARD_LED_1_PIN) | GPIO_BIT(NUBOARD_LED_2_PIN) |           \
     GPIO_BIT(NUBOARD_VCCB_MUX_D0_PIN) |                                   \
     GPIO_BIT(NUBOARD_VCCB_MUX_D1_PIN))

#define VCCB_MUX_MASK                                                       \
    (GPIO_BIT(NUBOARD_VCCB_MUX_D0_PIN) |                                   \
     GPIO_BIT(NUBOARD_VCCB_MUX_D1_PIN))

#define LINE_BUFFER_SIZE 64

typedef enum {
    VCCB_OFF,
    VCCB_3V3,
    VCCB_5V,
    VCCB_INVALID,
} vccb_state_t;

static void init_control_pins(void) {
    gpio_init_mask(CONTROL_GPIO_MASK);
    gpio_put_masked(CONTROL_GPIO_MASK, CONTROL_OFF_LEVELS);
    gpio_set_dir_out_masked(CONTROL_GPIO_MASK);
}

static void set_led(uint pin, bool on) {
    gpio_put(pin, !on);
}

static bool get_led(uint pin) {
    return !gpio_get_out_level(pin);
}

static void set_vccb(vccb_state_t state) {
    uint32_t levels = VCCB_MUX_MASK;

    if (state == VCCB_3V3) {
        levels = GPIO_BIT(NUBOARD_VCCB_MUX_D1_PIN);
    } else if (state == VCCB_5V) {
        levels = 0;
    }

    // Update D0 and D1 in one SIO write so no intermediate rail is selected.
    gpio_put_masked(VCCB_MUX_MASK, levels);
}

static vccb_state_t get_vccb(void) {
    bool d0 = gpio_get_out_level(NUBOARD_VCCB_MUX_D0_PIN);
    bool d1 = gpio_get_out_level(NUBOARD_VCCB_MUX_D1_PIN);

    if (d0 && d1) {
        return VCCB_OFF;
    }
    if (!d0 && d1) {
        return VCCB_3V3;
    }
    if (!d0 && !d1) {
        return VCCB_5V;
    }
    return VCCB_INVALID;
}

static bool parse_on_off(const char *argument, bool *on) {
    if (strcmp(argument, "on") == 0) {
        *on = true;
        return true;
    }
    if (strcmp(argument, "off") == 0) {
        *on = false;
        return true;
    }
    return false;
}

static void handle_on_off_command(const char *name, const char *argument,
                                  uint pin, bool active_low) {
    if (argument == NULL) {
        bool on = active_low ? get_led(pin)
                             : gpio_get_out_level(pin);
        printf("%s %s\n", name, on ? "on" : "off");
        return;
    }

    bool on;
    if (!parse_on_off(argument, &on)) {
        printf("error: usage: %s [on|off]\n", name);
        return;
    }

    if (active_low) {
        set_led(pin, on);
    } else {
        gpio_put(pin, on);
    }
    printf("%s %s\n", name, on ? "on" : "off");
}

static void handle_vccb_command(const char *argument) {
    if (argument != NULL) {
        if (strcmp(argument, "off") == 0) {
            set_vccb(VCCB_OFF);
        } else if (strcmp(argument, "3v3") == 0) {
            set_vccb(VCCB_3V3);
        } else if (strcmp(argument, "5v") == 0) {
            set_vccb(VCCB_5V);
        } else {
            printf("error: usage: vccb [off|3v3|5v]\n");
            return;
        }
    }

    const char *state;
    switch (get_vccb()) {
        case VCCB_OFF:
            state = "off";
            break;
        case VCCB_3V3:
            state = "3v3";
            break;
        case VCCB_5V:
            state = "5v";
            break;
        default:
            state = "invalid";
            break;
    }
    printf("vccb %s\n", state);
}

static void print_help(void) {
    printf("commands:\n"
           "  led1 [on|off]\n"
           "  led2 [on|off]\n"
           "  1v2_fpga [on|off]\n"
           "  3v3_fpga [on|off]\n"
           "  vccb [off|3v3|5v]\n"
           "  help\n");
}

static void handle_command(char *line) {
    const char *command = strtok(line, " \t");
    const char *argument = strtok(NULL, " \t");
    const char *extra = strtok(NULL, " \t");

    if (command == NULL) {
        return;
    }
    if (extra != NULL) {
        printf("error: too many arguments\n");
        return;
    }

    if (strcmp(command, "led1") == 0) {
        handle_on_off_command("led1", argument, NUBOARD_LED_1_PIN, true);
    } else if (strcmp(command, "led2") == 0) {
        handle_on_off_command("led2", argument, NUBOARD_LED_2_PIN, true);
    } else if (strcmp(command, "1v2_fpga") == 0) {
        handle_on_off_command("1v2_fpga", argument,
                              NUBOARD_FPGA_1V2_EN_PIN, false);
    } else if (strcmp(command, "3v3_fpga") == 0) {
        handle_on_off_command("3v3_fpga", argument,
                              NUBOARD_FPGA_3V3_EN_PIN, false);
    } else if (strcmp(command, "vccb") == 0) {
        handle_vccb_command(argument);
    } else if (strcmp(command, "help") == 0 && argument == NULL) {
        print_help();
    } else {
        printf("error: unknown command; enter 'help' for a list\n");
    }
}

int main(void) {
    init_control_pins();
    stdio_init_all();

    char line[LINE_BUFFER_SIZE];
    size_t length = 0;
    bool overflow = false;
    bool previous_was_cr = false;

    printf("nuBoard test console\n");
    print_help();
    printf("> ");

    while (true) {
        int character = stdio_getchar_timeout_us(1000);
        if (character == PICO_ERROR_TIMEOUT) {
            continue;
        }

        if (character == '\r' || character == '\n') {
            if (character == '\n' && previous_was_cr) {
                previous_was_cr = false;
                continue;
            }
            previous_was_cr = character == '\r';
            putchar_raw('\r');
            putchar_raw('\n');

            if (overflow) {
                printf("error: command is too long\n");
            } else {
                line[length] = '\0';
                handle_command(line);
            }

            length = 0;
            overflow = false;
            printf("> ");
            continue;
        }

        previous_was_cr = false;
        if (character == '\b' || character == 0x7f) {
            if (length > 0 && !overflow) {
                --length;
                putchar_raw('\b');
                putchar_raw(' ');
                putchar_raw('\b');
            }
            continue;
        }

        if (character < ' ' || character > '~') {
            continue;
        }

        putchar_raw(character);
        if (length < sizeof(line) - 1) {
            line[length++] = (char)character;
        } else {
            overflow = true;
        }
    }
}
