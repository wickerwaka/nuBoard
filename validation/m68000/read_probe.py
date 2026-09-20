"""Sweep one ordinary read's DTACK and data transition independently.

The CPU stores its observed value at $220. The responder's transaction data
is deliberately not used as the read verdict: it describes backing RAM, not
the diagnostic override. Raw pin captures are retained for each experiment.
"""

import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

from nuboard.debug import CHANNEL, DebugClient
from nuboard.device import NuBoard
from .campaign import write_json
from .phase import from_report
from .runner import CORE_BUILD, ROOT, Harness, SimulationTransport
from .scope import Scope
from .timing import decode_word


def image(width):
    if width == 'fetch':
        # Jump into a controlled MOVEQ opcode, then store the affected D0.
        return {0: struct.pack('>II', 0x3f0, 0x10000),
                0x10000: bytes.fromhex('4ef9 0000 0200'),
                0x200: bytes.fromhex('7022 31c0 0220 23fc 0000 0001 0010 0004 60fe')}
    opcode = 0x3038 if width == 'word' else 0x1038
    address = 0x201 if width == 'low' else 0x200
    # MOVEQ #0,D0; MOVE.W/B $200/$201,D0; MOVE.W D0,$220;
    # MOVE.L #1,$100004 (completion marker); BRA.S *.
    code = bytes.fromhex('7000') + struct.pack('>HH', opcode, address)
    code += bytes.fromhex('31c0 0220 23fc 0000 0001 0010 0004 60fe')
    return {0: struct.pack('>II', 0x3f0, 0x10000),
            0x200: bytes.fromhex('a55a'), 0x10000: code}


def measure(capture):
    samples = [(tick, decode_word(word)) for tick, word in capture.window()]
    selected = [(tick, row) for tick, row in samples
                if row['address'] == 0x200 and not row['as_n'] and row['read']]
    if not selected:
        raise RuntimeError('missing target read in passive capture')
    start, end = selected[0][0], selected[-1][0] + 1
    ack = next(tick for tick, row in selected if not row['dtack_n'])
    data_changes = []
    previous = None
    for tick, row in selected:
        if row['data'] != previous:
            data_changes.append([tick, row['data']])
            previous = row['data']
    edges = [[tick, row['clock']] for (tick, row), (_, before)
             in zip(samples[1:], samples)
             if start - 20 <= tick <= end + 10 and row['clock'] != before['clock']]
    return {'as_start': start, 'as_end': end, 'dtack_start': ack,
            'data_changes': data_changes, 'clock_edges': edges}


def acquire(harness, scope, lane):
    scope.configure(lane)
    result = harness.run(lane, limit=10000)
    capture = scope.download()
    if not result['passed'] or not result['trace_complete'] or not capture.complete:
        raise RuntimeError('incomplete probe execution/capture')
    observed = int.from_bytes(harness.read_memory(lane, 0x220, 2), 'big')
    return {'lane': lane, 'observed': observed, 'result': result,
            'capture': capture.report(), 'timing': measure(capture)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('sim', 'spi-sim', 'board'), default='sim')
    parser.add_argument('--ack', type=int, nargs='+', default=[0, 4, 5, 6, 9, 10, 14, 15, 16, 19])
    parser.add_argument('--data', type=int, nargs='+', default=list(range(35)))
    parser.add_argument('--width', choices=('word', 'high', 'low', 'fetch'), default='word')
    parser.add_argument('--old', type=lambda s: int(s, 0), default=0x5aa5)
    parser.add_argument('--new', type=lambda s: int(s, 0), default=0xa55a)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (any(not 0 <= t <= 64 for t in args.ack)
            or any(not 0 <= t <= 63 for t in args.data) or args.repeats < 1
            or not 0 <= args.old <= 65535 or not 0 <= args.new <= 65535):
        parser.error('invalid timing/pattern/repeat range')
    if args.width == 'fetch' and (args.old, args.new) != (0x7011, 0x7022):
        parser.error('fetch probe requires --old 0x7011 --new 0x7022')
    if args.output.exists():
        parser.error('choose a fresh output path')
    report = {'target': args.target, 'width': args.width, 'old': args.old,
              'new': args.new, 'cases': [], 'completed': False,
              'error': None, 'cleanup_error': None}
    transport = None
    try:
        if args.target == 'board':
            subprocess.run([sys.executable, str(ROOT / 'tools/check_m68000_build.py')], check=True)
            transport = NuBoard()
            state = json.loads(transport.state())
            receipt = json.loads((ROOT / 'build/fpga/m68000/receipt.json').read_text())
            report.update(board_state=state, build_receipt=receipt)
            if (not state['link'] or state['vccb'] or state['selector_mv'] != 5000
                    or state['core_build'] != CORE_BUILD or CORE_BUILD != 14
                    or state['core_uuid'] != b'nuBoard-68000-v1'.hex()
                    or state['sha256'] != receipt['bitstream_sha256']):
                raise RuntimeError('requires receipt-matched build 14, VCCB off, exclusive 5 V')
            exchange = lambda data: transport.fpga_exchange(CHANNEL, data)
        else:
            transport = SimulationTransport(spi=args.target == 'spi-sim')
            exchange = transport.exchange
        debug = DebugClient(exchange)
        harness, scope = Harness(debug), Scope(debug)
        if struct.unpack('<HH', debug.read(8, 4)) != (5, 8):
            raise RuntimeError('CPU clock/responder setting changed')
        debug.write16(0x80, 0)
        debug.write16(0xa0, 0)
        debug.write16(0xaa, 0)
        if args.target == 'board':
            transport.vccb_enable()
            debug.write16(4, 1)
            # NMOS MC68000 power-up reset requires 100 ms stabilization.
            time.sleep(0.12)
        for ack in args.ack:
            for data in args.data:
                for repeat in range(args.repeats):
                    entry = {'ack': ack, 'data': data, 'repeat': repeat, 'runs': []}
                    path = args.output.with_suffix('') / f'a{ack:02}-d{data:02}-r{repeat:02}.json'
                    report['cases'].append({'ack': ack, 'data': data, 'repeat': repeat,
                                            'artifact': str(path)})
                    try:
                        debug.write(0x90, struct.pack('<5H', 1, ack, data, args.old, args.new))
                        harness.load(image(args.width))
                        for lane in ('model', 'socket') if args.target == 'board' else ('model',):
                            entry['runs'].append(acquire(harness, scope, lane))
                        values = [r['observed'] for r in entry['runs']]
                        report['cases'][-1]['values'] = values
                        print(f'ACK {ack:2} DATA {data:2} repeat {repeat}: '
                              + ' / '.join(f'{value:04x}' for value in values), flush=True)
                    finally:
                        write_json(path, entry)
                        write_json(args.output, report)
        report['completed'] = True
    except BaseException as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if transport is not None:
            try:
                if args.target == 'board':
                    transport.power_off()
                    time.sleep(0.02)
                    state = json.loads(transport.state())
                    report['shutdown_state'] = state
                    if any(state[key] for key in ('vccb', 'rail_1v2', 'rail_3v3')):
                        raise RuntimeError('rails remain on')
            except Exception as exc:
                report['cleanup_error'] = str(exc)
            finally:
                transport.close()
        report['completed'] &= report['error'] is None and report['cleanup_error'] is None
        write_json(args.output, report)
    return 0 if report['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
