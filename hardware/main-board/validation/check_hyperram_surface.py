#!/usr/bin/env python3
"""Audit the matched PCB-only HyperRAM candidate with KiCad's Python.

This is a routing-group check, not full-board or FPGA timing signoff.
Require a fresh KiCad DRC JSON report made with the candidate's project/rules.
The independent length measurement requires each fast net to be one simple,
unbranched, all-front-copper path between the two specified pad centers.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

import pcbnew
from shapely.geometry import LineString

BASE = Path(__file__).resolve().parents[1]
ASSIGNMENT = {
    'HR_DQ0': ('K1', 'D3'), 'HR_DQ1': ('L1', 'D2'),
    'HR_DQ2': ('H1', 'C4'), 'HR_DQ3': ('J1', 'D4'),
    'HR_DQ4': ('G1', 'D5'), 'HR_DQ5': ('K2', 'E3'),
    'HR_DQ6': ('L2', 'E2'), 'HR_DQ7': ('M3', 'E1'),
    'HR_CK': ('M1', 'B2'), 'HR_RWDS': ('L3', 'C3'),
}
RELOCATIONS = {
    'F_LCLK_EN': 'G4', 'F_LCLK': 'G5', 'DUT_ISOLATE': 'E5',
    'F_L11': 'H4', 'F_L10': 'H6', 'F_L14': 'J4', 'F_L13': 'J5',
    'F_L12': 'J7', 'F_L16': 'K4', 'F_L15': 'K5',
    '~{F_L1_OE}': 'L4', 'F_L1_DIR': 'L5', 'F_L17': 'L6',
    'F_L20': 'N4', 'F_L21': 'M4',
}


def xy(point):
    return point.x, point.y


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(board_path, drc_path):
    board = pcbnew.LoadBoard(str(board_path))
    drc = json.loads(drc_path.read_text())
    errors = []
    results = {}
    footprints = {f.GetReference(): f for f in board.GetFootprints()}
    pads = {ref: {p.GetNumber(): p for p in footprints[ref].Pads()}
            for ref in ('U1', 'U2')}
    with (BASE / 't120f484.csv').open() as stream:
        pinout = {r['FBGA484']: r for r in csv.DictReader(stream)}

    if drc.get('source') != board_path.name:
        errors.append('DRC source filename does not match the board')
    for violation in drc.get('violations', []):
        if violation.get('severity') == 'error':
            errors.append('DRC error: ' + violation['description'])
    for violation in drc.get('schematic_parity', []):
        errors.append('Schematic parity: ' + violation['description'])
    checked_nets = set(ASSIGNMENT) | set(RELOCATIONS)
    for violation in drc.get('unconnected_items', []):
        for item in violation.get('items', []):
            if any(f'[/{name}]' in item.get('description', '') for name in checked_nets):
                errors.append('Unconnected checked net: ' + item['description'])

    for signal, ball in RELOCATIONS.items():
        if pads['U1'][ball].GetNetname() != '/' + signal:
            errors.append(f'{signal}: incorrect replacement FPGA ball {ball}')
        if pinout[ball]['DDIO'] != 'Yes':
            errors.append(f'{signal}: replacement ball {ball} is not DDIO-capable')

    for signal, (fpga_ball, ram_ball) in ASSIGNMENT.items():
        name = '/' + signal
        endpoints = [pads['U1'][fpga_ball], pads['U2'][ram_ball]]
        for pad in endpoints:
            if pad.GetNetname() != name or not pad.IsOnLayer(pcbnew.F_Cu):
                errors.append(f'{signal}: wrong endpoint net or layer')
            if pad.GetPadToDieLength() != 0:
                errors.append(f'{signal}: package compensation must be unset')
        if pinout[fpga_ball]['DDIO'] != 'Yes':
            errors.append(f'{signal}: {fpga_ball} is not DDIO-capable')
        if signal == 'HR_RWDS' and '_CLK' not in pinout[fpga_ball]['Pin Names']:
            errors.append('RWDS must use a clock-input-capable GPIO')
        net_pads = [p for f in board.GetFootprints() for p in f.Pads()
                    if p.GetNetname() == name]
        if len(net_pads) != 2:
            errors.append(f'{signal}: expected exactly two endpoint pads')
        if any(z.GetNetname() == name for z in board.Zones()):
            errors.append(f'{signal}: unexpected copper zone on fast net')

        tracks = [t for t in board.GetTracks() if t.GetNetname() == name]
        graph = defaultdict(list)
        length_mm = 0.0
        for i, track in enumerate(tracks):
            if isinstance(track, pcbnew.PCB_VIA):
                errors.append(f'{signal}: via present')
                continue
            if isinstance(track, pcbnew.PCB_ARC):
                errors.append(f'{signal}: this independent checker expects straight segments')
                continue
            if track.GetLayer() != pcbnew.F_Cu:
                errors.append(f'{signal}: non-F.Cu segment present')
            a, b = xy(track.GetStart()), xy(track.GetEnd())
            if a == b:
                errors.append(f'{signal}: zero-length segment')
            graph[a].append((b, i))
            graph[b].append((a, i))
            length_mm += track.GetLength() / 1e6

        start, end = (xy(p.GetPosition()) for p in endpoints)
        if set(p for p, edges in graph.items() if len(edges) == 1) != {start, end}:
            errors.append(f'{signal}: route ends do not equal the specified pad centers')
        if any(len(edges) != (1 if p in (start, end) else 2)
               for p, edges in graph.items()):
            errors.append(f'{signal}: branch, duplicate edge or disconnected endpoint')
        visited = set()
        points = [start]
        current = start
        while True:
            available = [(p, i) for p, i in graph[current] if i not in visited]
            if not available:
                break
            current, i = available[0]
            visited.add(i)
            points.append(current)
        if current != end or len(visited) != len(tracks):
            errors.append(f'{signal}: not one complete unbranched endpoint-to-endpoint route')
        if len(points) >= 2 and not LineString(points).is_simple:
            errors.append(f'{signal}: route crosses or retraces itself')
        results[signal] = {
            'fpga_ball': fpga_ball, 'ram_ball': ram_ball,
            'length_mm': length_mm, 'segments': len(tracks),
            'layers': sorted(set(board.GetLayerName(t.GetLayer()) for t in tracks)),
            'vias': sum(isinstance(t, pcbnew.PCB_VIA) for t in tracks),
        }

    lengths = [r['length_mm'] for r in results.values()]
    signal_tracks = [t for t in board.GetTracks() if t.GetNetname().startswith('/HR_')]
    spread = max(lengths) - min(lengths)
    if spread > 0.381:
        errors.append(f'Fast-group length spread {spread:.9f} mm exceeds 0.381 mm')
    return {
        'status': 'pass' if not errors else 'fail',
        'scope': 'Ten fast nets: complete simple paths, F.Cu only, no vias, PCB-only spread <=0.381 mm; displaced nets checked against DRC',
        'board': str(board_path), 'board_sha256': digest(board_path),
        'drc': str(drc_path), 'drc_sha256': digest(drc_path),
        'signals': results, 'spread_mm': spread,
        'u2_locked': footprints['U2'].IsLocked(),
        'hyperram_signal_segments': len(signal_tracks),
        'hyperram_signal_segments_locked': sum(t.IsLocked() for t in signal_tracks),
        'spread_mils': spread / 0.0254, 'limit_mm': 0.381,
        'drc_violation_counts': dict(Counter(v['type'] for v in drc.get('violations', []))),
        'schematic_parity_issues': len(drc.get('schematic_parity', [])),
        'remaining_board_unconnected_items': len(drc.get('unconnected_items', [])),
        'full_board_signoff': False, 'fpga_timing_verified': False,
        'errors': errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board', type=Path)
    parser.add_argument('--drc', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.board, args.drc)
    print(json.dumps(result, indent=2))
    return int(result['status'] != 'pass')


if __name__ == '__main__':
    raise SystemExit(main())
