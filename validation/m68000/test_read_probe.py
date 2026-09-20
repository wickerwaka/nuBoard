"""Check diagnostic readback, timing boundaries, and byte-lane selection."""

import struct
import unittest

from nuboard.debug import DebugClient
from .read_probe import acquire, image
from .runner import ROOT, Harness, SimulationTransport
from .scope import Scope


@unittest.skipUnless((ROOT / 'build/fpga/m68000/verilator-direct/Vm68000_harness').exists(),
                     'build the simulator first')
class ReadProbeTests(unittest.TestCase):
    def setUp(self):
        self.transport = SimulationTransport()
        self.debug = DebugClient(self.transport.exchange)
        self.harness = Harness(self.debug)
        self.scope = Scope(self.debug)

    def tearDown(self):
        self.transport.close()

    def run_probe(self, ack, data, width='word', enabled=1):
        self.debug.write(0x90, struct.pack('<5H', enabled, ack, data, 0x5aa5, 0xa55a))
        self.harness.load(image(width))
        return acquire(self.harness, self.scope, 'model')

    def test_data_boundary_and_ack_wait_state(self):
        self.assertEqual(self.run_probe(0, 14)['observed'], 0xa55a)
        self.assertEqual(self.run_probe(0, 15)['observed'], 0x5aa5)
        self.assertEqual(self.run_probe(5, 15)['observed'], 0xa55a)

    def test_byte_lanes_and_disabled_path(self):
        for width, early, late in [('high', 0xa5, 0x5a), ('low', 0x5a, 0xa5)]:
            self.assertEqual(self.run_probe(0, 0, width)['observed'], early)
            self.assertEqual(self.run_probe(0, 63, width)['observed'], late)
        self.assertEqual(self.run_probe(63, 63, enabled=0)['observed'], 0xa55a)

    def test_probe_configuration_limits(self):
        for address, invalid in ((0x92, 65), (0x94, 64)):
            with self.assertRaises(RuntimeError):
                self.debug.write16(address, invalid)

    def test_early_ack_and_instruction_fetch(self):
        self.assertEqual(self.run_probe(64, 0)['observed'], 0xa55a)
        self.assertEqual(self.run_probe(64, 63)['observed'], 0x5aa5)
        for tick, expected in ((0, 0x22), (63, 0x11)):
            self.debug.write(0x90, struct.pack('<5H', 1, 64, tick, 0x7011, 0x7022))
            self.harness.load(image('fetch'))
            run = acquire(self.harness, self.scope, 'model')
            self.assertEqual(run['observed'], expected)


if __name__ == '__main__':
    unittest.main()
