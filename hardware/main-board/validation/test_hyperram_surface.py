#!/usr/bin/env python3
"""Mutation tests for the PCB-only surface-routing audit. No board writes."""
import unittest
from unittest.mock import patch

import pcbnew
import check_hyperram_surface as checker

DIRECTORY = checker.BASE / 'routing/hyperram-top'
BOARD = DIRECTORY / 'nuBoard.kicad_pcb'
DRC = DIRECTORY / 'drc.json'


class SurfaceAuditTests(unittest.TestCase):
    def setUp(self):
        self.board = pcbnew.LoadBoard(str(BOARD))

    def result(self):
        with patch.object(checker.pcbnew, 'LoadBoard', return_value=self.board):
            return checker.audit(BOARD, DRC)

    def track(self):
        return next(t for t in self.board.GetTracks() if t.GetNetname() == '/HR_DQ0')

    def assert_rejected(self, phrase):
        result = self.result()
        self.assertEqual(result['status'], 'fail')
        self.assertTrue(any(phrase in error for error in result['errors']), result['errors'])

    def test_verified_candidate_passes(self):
        result = self.result()
        self.assertEqual(result['errors'], [])
        self.assertLessEqual(result['spread_mm'], 0.381)
        self.assertEqual(len(result['signals']), 10)

    def test_open_segment_rejected(self):
        self.board.Remove(self.track())
        self.assert_rejected('complete unbranched')

    def test_via_rejected_even_with_previously_clean_drc(self):
        track = self.track()
        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition(track.GetStart())
        via.SetNet(track.GetNet())
        via.SetWidth(450000)
        via.SetDrill(250000)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        self.board.Add(via)
        self.assert_rejected('via present')

    def test_bottom_segment_rejected(self):
        self.track().SetLayer(pcbnew.B_Cu)
        self.assert_rejected('non-F.Cu')

    def test_excessive_length_rejected(self):
        track = self.track()
        a, b = track.GetStart(), track.GetEnd()
        middle = pcbnew.VECTOR2I((a.x+b.x)//2, (a.y+b.y)//2 + 2000000)
        extension = pcbnew.PCB_TRACK(self.board)
        extension.SetStart(middle)
        extension.SetEnd(b)
        extension.SetWidth(track.GetWidth())
        extension.SetLayer(pcbnew.F_Cu)
        extension.SetNet(track.GetNet())
        track.SetEnd(middle)
        self.board.Add(extension)
        self.assert_rejected('exceeds 0.381')

    def test_dangling_branch_rejected(self):
        track = self.track()
        extra = pcbnew.PCB_TRACK(self.board)
        extra.SetStart(track.GetStart())
        extra.SetEnd(track.GetStart()+pcbnew.VECTOR2I(0, 100000))
        extra.SetWidth(track.GetWidth())
        extra.SetLayer(pcbnew.F_Cu)
        extra.SetNet(track.GetNet())
        self.board.Add(extra)
        self.assert_rejected('branch')

    def test_package_compensation_rejected(self):
        fpga = next(f for f in self.board.GetFootprints() if f.GetReference() == 'U1')
        pad = next(p for p in fpga.Pads() if p.GetNumber() == 'K1')
        pad.SetPadToDieLength(100000)
        self.assert_rejected('package compensation')


if __name__ == '__main__':
    unittest.main()
