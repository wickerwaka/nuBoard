"""Source-directed BR phase controls; no changes to the upstream CPU core."""

import struct
import unittest

from nuboard.debug import DebugClient
from .br_probe import EXPECTED_PRODUCT, acquire, image
from .runner import ROOT, Harness, SimulationTransport
from .scope import Scope


@unittest.skipUnless(
    (ROOT / 'build/fpga/m68000/verilator-direct/Vm68000_harness').exists(),
    'build the simulator first',
)
class BrProbeTests(unittest.TestCase):
    def setUp(self):
        self.transport = SimulationTransport()
        self.debug = DebugClient(self.transport.exchange)
        self.harness = Harness(self.debug)
        self.scope = Scope(self.debug)

    def tearDown(self):
        self.transport.close()

    def test_falling_edge_stage_changes_only_late_request(self):
        for delay, expected in ((63, (80, 80)), (67, (80, 90))):
            for stage, grant_tick in enumerate(expected):
                with self.subTest(delay=delay, stage=stage):
                    self.debug.write(
                        0xa0, struct.pack('<6H', 1, delay, 80, 0xc, 1, stage)
                    )
                    self.harness.load(image())
                    run = acquire(self.harness, self.scope, 'model', delay, 80)
                    self.assertEqual(run['product'], EXPECTED_PRODUCT)
                    self.assertTrue(run['timing']['bus_idle_through_handshake'])
                    self.assertEqual(
                        run['timing']['grant_from_anchor_ticks'], grant_tick
                    )

    def test_defaults_and_invalid_configuration(self):
        self.assertEqual(self.debug.read(0xa0, 2), b'\x00\x00')
        self.assertEqual(self.debug.read(0xaa, 2), b'\x00\x00')
        for address, value in (
            (0xa0, 2), (0xa2, 256), (0xa4, 19), (0xa4, 256),
            (0xa6, 1), (0xa8, 256), (0xaa, 2),
        ):
            with self.subTest(address=address, value=value):
                with self.assertRaises(RuntimeError):
                    self.debug.write16(address, value)


if __name__ == '__main__':
    unittest.main()
