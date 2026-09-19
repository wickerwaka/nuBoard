import struct
import unittest
from unittest.mock import patch

from nuboard.debug import DebugClient, HEADER
from nuboard.device import NuBoard, NuBoardError
from nuboard.protocol import EventRecord, EventType, Status


class DebugTests(unittest.TestCase):
    def test_chunking_and_endianness(self):
        commands = []

        def exchange(raw):
            magic, operation, reserved, length, address = HEADER.unpack_from(raw)
            self.assertEqual((magic, reserved), (b"NDB1", 0))
            commands.append((operation, length, address, raw[12:]))
            return bytes(4) + (bytes(length) if operation == 0 else b"")

        client = DebugClient(exchange)
        client.write(0x10000, bytes(514))
        self.assertEqual([row[1:3] for row in commands],
                         [(256, 0x10000), (256, 0x10100), (2, 0x10200)])
        client.write16(4, 0x0302)
        self.assertEqual(commands[-1][-1], b"\x02\x03")
        self.assertEqual(client.read(0x10000, 514), bytes(514))

    def test_wait_is_one_command(self):
        commands = []

        def exchange(raw):
            commands.append(raw)
            return bytes(4) + b"\x06\x00"

        self.assertEqual(DebugClient(exchange).wait16(6, 2, 2, 1000), 6)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][12:], struct.pack("<HHI", 2, 2, 1000))

    def test_rejects_bad_requests_and_responses(self):
        client = DebugClient(lambda _: bytes(4))
        for address, length in ((1, 2), (0, 1), (0, 0), (0x100000, 2)):
            with self.assertRaises(ValueError):
                client.read(address, length)
        with self.assertRaisesRegex(RuntimeError, "length mismatch"):
            client.read16(0)
        with self.assertRaisesRegex(RuntimeError, "status=3"):
            DebugClient(lambda _: b"\x03\x00\x00\x00").read16(0)


class ExchangeTests(unittest.TestCase):
    def make_board(self):
        # No USB thread: deterministic event injection exercises the consumer.
        board = NuBoard(object())
        board._start_events = lambda: None
        return board

    @staticmethod
    def event(kind, lost=0):
        return EventRecord(kind, 0, 1, 0, 0, 0, lost)

    def test_interrupt_driven_tagged_response(self):
        board = self.make_board()
        board._event_queue.put(self.event(EventType.FPGA_IRQ))
        with patch.object(board, "fpga_send") as send, \
             patch.object(board, "fpga_recv", return_value=(0x44, 3, 1, b"reply")), \
             patch.object(board, "state", side_effect=AssertionError("status polling")):
            self.assertEqual(board.fpga_exchange(0x44, b"request"), b"reply")
            send.assert_called_once_with(0x44, b"request", 1)

    def test_mismatch_overflow_and_timeout_fail_closed(self):
        for event, packet, expected in (
            (self.event(EventType.FPGA_IRQ), (0x44, 3, 2, b""), Status.LINK),
            (self.event(EventType.OVERFLOW, 1), None, Status.LINK),
            (None, None, Status.TIMEOUT),
        ):
            board = self.make_board()
            if event:
                board._event_queue.put(event)
            with patch.object(board, "fpga_send"), \
                 patch.object(board, "fpga_recv", return_value=packet):
                with self.assertRaises(NuBoardError) as caught:
                    board.fpga_exchange(0x44, b"", timeout=0.01)
                self.assertEqual(caught.exception.status, expected)


if __name__ == "__main__":
    unittest.main()
