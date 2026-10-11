# nuBoard communication protocols

All multibyte integer fields are little-endian.

## USB composite device

The firmware uses VID `0x2e8a`, PID `0x000a`, product string `nuBoard`, and the
RP2040 flash unique ID as its USB serial number.

| Interface | Function | Endpoints |
| ---: | --- | --- |
| 0-1 | CDC ACM diagnostics | notify `0x81`, OUT `0x02`, IN `0x82` |
| 2 | Vendor bulk protocol | OUT `0x03`, IN `0x83` |
| 3 | Vendor event stream | interrupt IN `0x84`, 32 bytes, 1 ms |
| 4 | Raspberry Pi reset interface | control transfers |

CDC is read-only apart from `help`, `info`, and `status`. Device control,
bitstream data, and FPGA traffic use interface 2.

### Bulk header

Every request and response begins with this packed 20-byte header:

| Offset | Size | Field |
| ---: | ---: | --- |
| 0 | 4 | ASCII `NUB1` |
| 4 | 1 | protocol major, currently 1 |
| 5 | 1 | protocol minor, currently 0 |
| 6 | 1 | kind: 0 request, 1 response |
| 7 | 1 | flags, currently zero |
| 8 | 2 | opcode |
| 10 | 2 | status |
| 12 | 4 | sequence |
| 16 | 4 | payload length, at most 4096 |

Requests are serialized. A response repeats the opcode and sequence. Status
values are `0 OK`, `1 VERSION`, `2 LENGTH`, `3 STATE`, `4 ARGUMENT`, `5 BUSY`,
`6 TIMEOUT`, `7 CHECKSUM`, `8 LINK`, `9 CONFIGURATION`, `10 SELECTOR`, and
`11 INTERNAL`.

USB transfer boundaries are not message boundaries. Frames may be split or
coalesced, and an exact multiple of the endpoint's 64-byte packet size may be
followed by a zero-length packet. The host ignores that transport terminator
and assembles the next frame under a fixed read deadline; it does not retry the
request or treat the zero-length packet as end-of-stream.

| Opcode | Value | Request payload |
| --- | ---: | --- |
| `GET_INFO` | `0x0001` | empty |
| `GET_STATE` | `0x0002` | empty |
| `CONFIG_BEGIN` | `0x0100` | 64-byte NUL-terminated basename, `u32` size, 32-byte SHA-256 |
| `CONFIG_DATA` | `0x0101` | `u32` offset followed by 1-4092 bytes |
| `CONFIG_END` | `0x0102` | empty |
| `CONFIG_ABORT` | `0x0103` | empty |
| `FPGA_SEND` | `0x0200` | channel, flags, reserved `u16`, tag `u32`, up to 4080 bytes |
| `FPGA_RECV` | `0x0201` | empty |
| `LINK_STATUS` | `0x0202` | empty |
| `VCCB_ENABLE` | `0x0300` | empty |
| `VCCB_DISABLE` | `0x0301` | empty |
| `POWER_OFF` | `0x0302` | empty |

Configuration enforces contiguous offsets, the declared size, a 32 MiB limit,
SHA-256, and a five-second inter-chunk timeout. It does not retry. CCK stops
high between chunks. Success additionally requires CDONE, three valid 80-120
ms heartbeat periods, and a supported mailbox identity.

`GET_STATE` returns JSON containing selector and rail state, configuration
phase and failure code, CDONE and heartbeat state, filename, byte counts,
SHA-256, link health, core UUID/version/build, and mailbox ABI. The host waits
for the asynchronous rail/reset sequence to reach the streaming phase before
sending the first data chunk.

### Event record

Interface 3 emits fixed 32-byte `NUE1` records containing version, event type
and flags, sequence, MCU timestamp, two arguments, lost-event count, and a
zero reserved word. Event types are FPGA IRQ, state transition, configuration
failure, forced VCCB shutdown, link fault, and queue overflow.

## FPGA mailbox

Runtime SPI uses mode 0 at 10 MHz. GPIO0/CDI0 is MISO, GPIO1/CDI1 is chip
select, GPIO2/CDI2 is SCK, and GPIO3/CDI3 is MOSI. GPIO10/NSTATUS is the
active-low level IRQ. GPIO6/CSO remains the 10 Hz qualification heartbeat.

Commands are `STATUS=0x01`, `WRITE_PACKET=0x02`, `READ_PACKET=0x03`,
`ACK_PACKET=0x04`, and `GET_ID=0x05`.

A packet occupies at most 4096 bytes: a 16-byte header followed by at most
4080 payload bytes. The header contains ABI major, channel, FIRST/LAST flags,
tag, payload length, and payload CRC32C. An outbound packet remains readable
and holds IRQ low until a matching ACK. The template applies backpressure
rather than overwriting either 4 KiB slot.

The template presents each packet to its application as byte-wide
valid/ready streams with a `last` marker. `nuboard_stream_echo` demonstrates
the interface and can be replaced without modifying the SPI mailbox.

## Power and recovery

FPGA and VCCB start off. Configuration enables 1.2 V, waits 5 ms, establishes
passive-x4 levels, enables 3.3 V, and only then releases reset. GPIO10 is masked
during configuration and handed to the runtime IRQ after identity succeeds.

GPIO20 (`5V_SELECT`) and GPIO21 (`3V3_SELECT`) are active-low selectors. The
exclusive states `0/1` and `1/0` request 5 V and 3.3 V respectively. `1/1` is
no selection and `0/0` is a conflict. Enabling VCCB requires a stable exclusive
selection and a healthy configured FPGA. Any selector change disables VCCB
atomically and emits an event.

Physical USB unmount/reset, interrupted configuration, or fatal link failure
turns VCCB off, asserts CRESET_N, disables 3.3 V, waits 5 ms, then disables
1.2 V. A host process exit does not imply USB unmount and therefore does not
power the board down.
