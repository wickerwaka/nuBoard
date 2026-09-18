import unittest

from nuboard.protocol import Kind, Message, Opcode, Status


class ProtocolTests(unittest.TestCase):
    def test_message_round_trip(self):
        original = Message(Opcode.GET_STATE, 0x12345678, b"abc")
        self.assertEqual(Message.unpack(original.pack()), original)

    def test_malformed_headers(self):
        for raw in (b"", b"NUB1", b"BAD!" + b"\0" * 16):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    Message.unpack(raw)

    def test_response_fields_are_preserved(self):
        message = Message(
            Opcode.CONFIG_DATA,
            7,
            b"bad",
            Kind.RESPONSE,
            Status.CHECKSUM,
        )
        self.assertEqual(Message.unpack(message.pack()), message)


if __name__ == "__main__":
    unittest.main()
