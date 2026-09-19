import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nuboard.device import (
    EP_BULK_IN,
    EP_BULK_OUT,
    EP_EVENT_IN,
    NuBoard,
    NuBoardError,
    USBTransport,
)
from nuboard.protocol import EVENT, EventType, Kind, Message, Opcode, Status


class FakeTransport:
    def __init__(self):
        self.responses = bytearray()
        self.requests = []
        self.events = []
        self.closed = False
        self.state_queries = 0

    def write(self, endpoint, data, timeout=None):
        del timeout
        assert endpoint == EP_BULK_OUT
        request = Message.unpack(bytes(data))
        self.requests.append(request)
        payload = b""
        if request.opcode == Opcode.GET_STATE:
            self.state_queries += 1
            phase = 5 if self.state_queries == 1 else 11
            payload = f'{{"phase":{phase}}}'.encode()
        response = Message(
            request.opcode,
            request.sequence,
            payload,
            Kind.RESPONSE,
        )
        self.responses.extend(response.pack())
        return len(data)

    def read(self, endpoint, size, timeout=None):
        del timeout
        if endpoint == EP_EVENT_IN:
            if self.events:
                return self.events.pop(0)
            raise TimeoutError("timed out")
        assert endpoint == EP_BULK_IN
        result = self.responses[:size]
        del self.responses[:size]
        return result

    def close(self):
        self.closed = True


class FakeUSBDevice:
    def __init__(self, configured=True):
        self.configuration = object() if configured else None
        self.set_configuration_calls = 0

    def get_active_configuration(self):
        return self.configuration

    def set_configuration(self):
        self.set_configuration_calls += 1
        self.configuration = object()


class FakeUSBUtil:
    def __init__(self):
        self.claimed = []
        self.released = []
        self.disposed = []

    def claim_interface(self, device, interface):
        self.claimed.append((device, interface))

    def release_interface(self, device, interface):
        self.released.append((device, interface))

    def dispose_resources(self, device):
        self.disposed.append(device)


class DeviceTests(unittest.TestCase):
    def test_zero_length_packet_after_exact_usb_packet_does_not_retry(self):
        transport = FakeTransport()
        packets = []

        def write(endpoint, data, timeout=None):
            self.assertEqual(endpoint, EP_BULK_OUT)
            request = Message.unpack(bytes(data))
            transport.requests.append(request)
            # A 20-byte NUB1 header plus 44 payload bytes is exactly 64.
            packets.append(Message(request.opcode, request.sequence,
                                   bytes(44), Kind.RESPONSE).pack())
            packets.append(b"")

        transport.write = write
        transport.read = lambda endpoint, size, timeout=None: packets.pop(0)
        board = NuBoard(transport)
        self.assertEqual(board.info(), bytes(44))
        self.assertEqual(board.info(), bytes(44))
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual([request.sequence for request in transport.requests], [1, 2])

    def test_zero_length_packets_between_split_frame_bytes(self):
        response = Message(Opcode.GET_INFO, 1, b"payload", Kind.RESPONSE).pack()
        packets = [b"", response[:9], b"", response[9:22], b"", response[22:]]
        transport = FakeTransport()
        transport.write = lambda *args, **kwargs: None
        transport.read = lambda endpoint, size, timeout=None: packets.pop(0)
        self.assertEqual(NuBoard(transport).info(), b"payload")

    def test_empty_usb_transfers_do_not_extend_response_deadline(self):
        transport = FakeTransport()
        transport.read = lambda *args, **kwargs: b""
        board = NuBoard(transport, timeout_ms=100)
        with patch("nuboard.device.time.monotonic", side_effect=[0.0, 0.01, 0.11]):
            with self.assertRaises(NuBoardError) as error:
                board.info()
        self.assertEqual(error.exception.status, Status.TIMEOUT)
        self.assertEqual(len(transport.requests), 1)

    def test_usb_transport_reuses_active_configuration(self):
        device = FakeUSBDevice(configured=True)
        usb_util = FakeUSBUtil()

        transport = USBTransport(device, usb_util)
        transport.close()

        self.assertEqual(device.set_configuration_calls, 0)
        self.assertEqual(
            [interface for _, interface in usb_util.claimed],
            [2, 3],
        )
        self.assertEqual(
            [interface for _, interface in usb_util.released],
            [3, 2],
        )
        self.assertEqual(usb_util.disposed, [device])

    def test_configure_chunks_and_reports_progress(self):
        image = bytes(range(256)) * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.hex.bin"
            path.write_bytes(image)
            transport = FakeTransport()
            progress = []
            board = NuBoard(transport)
            board.configure(path, lambda done, total: progress.append((done, total)))

        self.assertEqual(
            [request.opcode for request in transport.requests],
            [
                Opcode.CONFIG_BEGIN,
                Opcode.GET_STATE,
                Opcode.CONFIG_DATA,
                Opcode.CONFIG_DATA,
                Opcode.CONFIG_DATA,
                Opcode.CONFIG_END,
                Opcode.GET_STATE,
            ],
        )
        name, size, digest = struct.unpack(
            "<64sI32s", transport.requests[0].payload
        )
        self.assertEqual(name.rstrip(b"\0"), b"demo.hex.bin")
        self.assertEqual(size, len(image))
        self.assertEqual(digest, hashlib.sha256(image).digest())
        self.assertEqual(
            [
                struct.unpack_from("<I", request.payload)[0]
                for request in transport.requests[2:5]
            ],
            [0, 4092, 8184],
        )
        self.assertEqual(progress[-1], (len(image), len(image)))

    def test_error_mapping(self):
        transport = FakeTransport()
        board = NuBoard(transport)
        sequence = board._sequence + 1
        transport.responses.extend(
            Message(
                Opcode.GET_INFO,
                sequence,
                b"not ready",
                Kind.RESPONSE,
                Status.STATE,
            ).pack()
        )
        transport.write = lambda *args, **kwargs: None
        with self.assertRaises(NuBoardError) as error:
            board.info()
        self.assertEqual(error.exception.status, Status.STATE)

    def test_blocking_event_reader_and_cleanup(self):
        transport = FakeTransport()
        transport.events.append(
            EVENT.pack(
                b"NUE1",
                1,
                0,
                EventType.FPGA_IRQ,
                0,
                4,
                5,
                6,
                7,
                0,
                0,
            )
        )
        board = NuBoard(transport)
        self.assertEqual(next(board.events()).sequence, 4)
        board.close()
        self.assertTrue(transport.closed)

    def test_send_chunks_large_message(self):
        transport = FakeTransport()
        board = NuBoard(transport)
        board.fpga_send(2, b"x" * 9000, tag=9)
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual(
            [request.payload[1] for request in transport.requests], [1, 0, 2]
        )


if __name__ == "__main__":
    unittest.main()
