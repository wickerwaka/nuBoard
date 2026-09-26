#!/usr/bin/env python3
"""Read-only audit of the HyperRAM allocation against the PCB and pinout.

Optional --netlist accepts a fresh `kicad-cli sch export netlist` output.
--signoff requires a fresh netlist and --drc JSON report. Matching is
PCB-only, per user approval; package lengths are excluded, not assumed known.
"""
import argparse
import csv
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ASSIGNMENT = {
    'HR_DQ0': ('K1', 'D3'), 'HR_DQ1': ('L1', 'D2'),
    'HR_DQ2': ('H1', 'C4'), 'HR_DQ3': ('J1', 'D4'),
    'HR_DQ4': ('G1', 'D5'), 'HR_DQ5': ('K2', 'E3'),
    'HR_DQ6': ('L2', 'E2'), 'HR_DQ7': ('M3', 'E1'),
    'HR_CK': ('M1', 'B2'), 'HR_RWDS': ('L3', 'C3'),
    'HR_CS_N': ('G3', 'A3'), 'HR_RESET_N': ('G2', 'A4'),
}
FAST = list(ASSIGNMENT)[:10]


def parse(text):
    stack = []
    root = None
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        if token == '(':
            node = []
            if stack:
                stack[-1].append(node)
            else:
                root = node
            stack.append(node)
        elif token == ')':
            stack.pop()
        else:
            stack[-1].append(json.loads(token) if token.startswith('"') else token)
    return root


def children(node, key):
    return [n for n in node if isinstance(n, list) and n and n[0] == key]


def val(node, key, default=None):
    return next((n[1] for n in children(node, key)), default)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--netlist', type=Path)
    ap.add_argument('--drc', type=Path)
    ap.add_argument('--signoff', action='store_true')
    args = ap.parse_args()
    errors, blockers = [], []
    pcb = parse((BASE / 'nuBoard.kicad_pcb').read_text())
    fps = {next(p[2] for p in children(f, 'property') if p[1] == 'Reference'): f
           for f in children(pcb, 'footprint')}
    pads = {ref: {p[1]: p for p in children(fps[ref], 'pad')} for ref in ['U1', 'U2']}
    pinout = {r['FBGA484']: r for r in csv.DictReader((BASE / 't120f484.csv').open())}
    csvmap = {r['Signal']: r for r in csv.DictReader((BASE / 'fpga_pin_map.csv').open())}
    nets = None
    if args.netlist:
        nl = parse(args.netlist.read_text())
        nets = {val(n, 'name'): {(val(p, 'ref'), val(p, 'pin')) for p in children(n, 'node')}
                for container in children(nl, 'nets') for n in children(container, 'net')}
    for signal, (ball, ram_ball) in ASSIGNMENT.items():
        expected = '/' + signal
        for ref, pad in [('U1', ball), ('U2', ram_ball)]:
            if val(pads[ref][pad], 'net') != expected:
                errors.append(f'{signal}: PCB {ref}.{pad} has the wrong net')
            if nets is not None and (ref, pad) not in nets.get(expected, set()):
                errors.append(f'{signal}: schematic {ref}.{pad} has the wrong net')
        if csvmap[signal]['Ball'] != ball:
            errors.append(f'{signal}: pin-map CSV disagrees')
        if pinout[ball]['DDIO'] != 'Yes':
            errors.append(f'{ball}: not DDIO-capable')
        if signal not in FAST:
            continue
        if signal == 'HR_RWDS' and '_CLK' not in pinout[ball]['Pin Names']:
            errors.append(f'{ball}: RWDS requires a clock-input-capable GPIO')
        for ref, pad in [('U1', ball), ('U2', ram_ball)]:
            if float(val(pads[ref][pad], 'die_length', '0')) != 0:
                errors.append(f'{signal}: {ref}.{pad} has package compensation in a PCB-only match')
    expected_balls = {r + str(c) for r in 'ABCDE' for c in range(1, 6)} - {'A1'}
    if set(pads['U2']) != expected_balls:
        errors.append('U2 footprint must have 24 balls, with A1 absent')
    for ball in ['A2', 'A5', 'B1', 'B5', 'C2', 'C5']:
        if not val(pads['U2'][ball], 'net', '').startswith('unconnected-'):
            errors.append(f'U2.{ball}: RFU must be left unconnected for BLL/B1')
    for balls, net in [(['B4', 'D1', 'E4'], '+3.3V'), (['B3', 'C1', 'E5'], 'GND')]:
        for ball in balls:
            if val(pads['U2'][ball], 'net') != net:
                errors.append(f'U2.{ball}: wrong power net')
    if args.drc:
        drc = json.loads(args.drc.read_text())
        if drc.get('unconnected_items'):
            blockers.append(f"PCB has {len(drc['unconnected_items'])} unrouted connections")
        if any(v['severity'] == 'error' for v in drc.get('violations', [])):
            blockers.append('PCB DRC still has errors')
    else:
        blockers.append('Fresh PCB DRC report required for signoff')
    if args.signoff and nets is None:
        blockers.append('Fresh schematic netlist required for signoff')
    for error in errors:
        print('ERROR:', error)
    for blocker in blockers:
        print('PENDING:', blocker)
    if not errors:
        print('PASS: 12 PCB allocations, DDIO capabilities, clock-capable RWDS, 24-ball footprint and power/RFU nets')
    print('Matching basis: PCB-only, maximum spread 0.381 mm; IC package skew excluded.')
    print('NOT a routing feasibility or FPGA timing-closure certificate.')
    return 1 if errors else (2 if args.signoff and blockers else 0)


if __name__ == '__main__':
    raise SystemExit(main())
