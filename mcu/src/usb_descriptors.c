#include <string.h>

#include "device/usbd_pvt.h"
#include "pico/unique_id.h"
#include "pico/usb_reset.h"
#include "tusb.h"

enum {
    ITF_CDC = 0,
    ITF_CDC_DATA,
    ITF_BULK,
    ITF_EVENT,
    ITF_RESET,
    ITF_COUNT,
};

enum {
    STR_MANUFACTURER = 1,
    STR_PRODUCT,
    STR_SERIAL,
    STR_CDC,
    STR_BULK,
    STR_EVENT,
    STR_RESET,
};

#define EP_CDC_NOTIFY 0x81
#define EP_CDC_OUT 0x02
#define EP_CDC_IN 0x82
#define EP_BULK_OUT 0x03
#define EP_BULK_IN 0x83
#define EP_EVENT_IN 0x84

#define EVENT_DESCRIPTOR_LENGTH 16
#define CONFIG_DESCRIPTOR_LENGTH                                           \
    (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_VENDOR_DESC_LEN +       \
     EVENT_DESCRIPTOR_LENGTH + TUD_RPI_RESET_DESC_LEN)

static tusb_desc_device_t const device_descriptor = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = 64,
    .idVendor = 0x2e8a,
    .idProduct = 0x000a,
    .bcdDevice = 0x0100,
    .iManufacturer = STR_MANUFACTURER,
    .iProduct = STR_PRODUCT,
    .iSerialNumber = STR_SERIAL,
    .bNumConfigurations = 1,
};

static uint8_t const configuration_descriptor[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_COUNT, 0, CONFIG_DESCRIPTOR_LENGTH, 0, 250),

    TUD_CDC_DESCRIPTOR(ITF_CDC, STR_CDC, EP_CDC_NOTIFY, 8, EP_CDC_OUT,
                       EP_CDC_IN, 64),

    TUD_VENDOR_DESCRIPTOR(ITF_BULK, STR_BULK, EP_BULK_OUT, EP_BULK_IN, 64),

    // Interface 3 is a dedicated 32-byte interrupt-IN event stream. It uses
    // a small custom TinyUSB class driver below because the built-in vendor
    // class only describes paired bulk endpoints.
    9, TUSB_DESC_INTERFACE, ITF_EVENT, 0, 1, TUSB_CLASS_VENDOR_SPECIFIC,
    0x4e, 0x01, STR_EVENT,
    7, TUSB_DESC_ENDPOINT, EP_EVENT_IN, TUSB_XFER_INTERRUPT,
    32, 0, 1,

    TUD_RPI_RESET_DESCRIPTOR(ITF_RESET, STR_RESET),
};

TU_VERIFY_STATIC(sizeof(configuration_descriptor) == CONFIG_DESCRIPTOR_LENGTH,
                 "configuration descriptor size");

uint8_t const *tud_descriptor_device_cb(void) {
    return (uint8_t const *)&device_descriptor;
}

uint8_t const *tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    return configuration_descriptor;
}

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid;

    static uint16_t descriptor[40];
    static char serial[PICO_UNIQUE_BOARD_ID_SIZE_BYTES * 2 + 1];
    static char const *const strings[] = {
        NULL,
        "Raspberry Pi",
        "nuBoard",
        serial,
        "nuBoard diagnostics",
        "nuBoard bulk",
        "nuBoard events",
        "Reset",
    };

    if (serial[0] == '\0') {
        pico_get_unique_board_id_string(serial, sizeof(serial));
    }

    if (index == 0) {
        descriptor[1] = 0x0409;
        descriptor[0] = (TUSB_DESC_STRING << 8) | 4;
        return descriptor;
    }
    if (index >= sizeof(strings) / sizeof(strings[0])) {
        return NULL;
    }

    unsigned length = 0;
    while (strings[index][length] != '\0' && length < 39) {
        descriptor[1 + length] = strings[index][length];
        ++length;
    }
    descriptor[0] = (TUSB_DESC_STRING << 8) | (2 * length + 2);
    return descriptor;
}

static bool event_busy;

static void event_init(void) {
    event_busy = false;
}

static void event_reset(uint8_t rhport) {
    (void)rhport;
    event_busy = false;
}

static uint16_t event_open(uint8_t rhport,
                           tusb_desc_interface_t const *interface,
                           uint16_t max_length) {
    if (interface->bInterfaceClass != TUSB_CLASS_VENDOR_SPECIFIC ||
        interface->bInterfaceSubClass != 0x4e ||
        interface->bInterfaceProtocol != 1 ||
        max_length < EVENT_DESCRIPTOR_LENGTH) {
        return 0;
    }

    tusb_desc_endpoint_t const *endpoint =
        (tusb_desc_endpoint_t const *)tu_desc_next(interface);
    if (!usbd_edpt_open(rhport, endpoint)) {
        return 0;
    }
    return EVENT_DESCRIPTOR_LENGTH;
}

static bool event_control(uint8_t rhport, uint8_t stage,
                          tusb_control_request_t const *request) {
    (void)rhport;
    (void)stage;
    (void)request;
    return false;
}

static bool event_xfer(uint8_t rhport, uint8_t endpoint,
                       xfer_result_t result, uint32_t length) {
    (void)rhport;
    (void)length;
    if (endpoint == EP_EVENT_IN) {
        event_busy = false;
    }
    return result == XFER_RESULT_SUCCESS;
}

bool nub_event_endpoint_write(uint8_t const record[32]) {
    static uint8_t transfer[32] __attribute__((aligned(4)));

    if (event_busy || !tud_mounted()) {
        return false;
    }
    memcpy(transfer, record, sizeof(transfer));
    event_busy = usbd_edpt_xfer(0, EP_EVENT_IN, transfer, sizeof(transfer));
    return event_busy;
}

usbd_class_driver_t const *usbd_app_driver_get_cb(uint8_t *count) {
    static usbd_class_driver_t const drivers[] = {
        {
#if CFG_TUSB_DEBUG >= 2
            .name = "NUEVENT",
#endif
            .init = event_init,
            .reset = event_reset,
            .open = event_open,
            .control_xfer_cb = event_control,
            .xfer_cb = event_xfer,
            .sof = NULL,
        },
        {
#if CFG_TUSB_DEBUG >= 2
            .name = "RESET",
#endif
            .init = usb_reset_interface_init,
            .reset = usb_reset_interface_reset,
            .open = usb_reset_interface_open,
            .control_xfer_cb = usb_reset_interface_control_xfer_cb,
            .xfer_cb = usb_reset_interface_xfer_cb,
            .sof = NULL,
        },
    };

    *count = sizeof(drivers) / sizeof(drivers[0]);
    return drivers;
}
