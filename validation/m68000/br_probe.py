"""Source-directed BR synchronization experiment during register multiplication.

Capture DATA bits 0/1/2 mean BR_N/BG_N/fixed-inactive BGACK_N in this mode.
The diagnostic extra stage restores the source's commented falling-edge BR
register externally; it is a reference hypothesis, not a replacement CPU.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

from nuboard.debug import CHANNEL, DebugClient
from nuboard.device import NuBoard
from .campaign import write_json
from .runner import CORE_BUILD, ROOT, Harness, SimulationTransport
from .scope import Scope
from .timing import decode_word

EXPECTED_PRODUCT = 0x1234 * 0xffff


def image():
    # MOVEQ #0,D0; MOVE.W #$ffff,D1; MOVE.W #$1234,D0;
    # MULU.W D1,D0; NOP; NOP; MOVE.L D0,$220; pass marker; BRA.S *.
    # The fetch at $1000c precedes MULU's long internal execution interval.
    return {0: struct.pack('>II', 0x3f0, 0x10000),
            0x10000: bytes.fromhex(
                '7000 323c ffff 303c 1234 c0c1 4e71 4e71 '
                '23c0 0000 0220 23fc 0000 0001 0010 0004 60fe')}


def measure(capture, anchor, delay, width):
    rows = [(tick, decode_word(word)) for tick, word in capture.window()]
    requests = [tick for tick, row in rows if not row['data'] & 1]
    grants = [tick for tick, row in rows if not row['data'] & 2]
    if not requests or not grants:
        raise RuntimeError('missing request or grant')
    request_on, request_off = requests[0], requests[-1] + 1
    grant_on, grant_off = grants[0], grants[-1] + 1
    if (requests != list(range(request_on, request_off)) or
            grants != list(range(grant_on, grant_off))):
        raise RuntimeError('non-contiguous request/grant')
    # Board observation may trail the output by one 20 ns sample.
    if not 0 <= request_on - anchor - delay <= 2:
        raise RuntimeError('request not at commanded phase')
    if abs(request_off - request_on - width) > 1:
        raise RuntimeError('request width changed')
    if not request_on < grant_on < request_off < grant_off:
        raise RuntimeError('invalid held-request handshake')
    window = [(tick, row) for tick, row in rows
              if request_on - 5 <= tick <= grant_off + 5]
    if not all(row['as_n'] for _, row in window):
        raise RuntimeError('arbitration overlaps an active memory cycle')
    if not all(row['data'] & 4 for _, row in window):
        raise RuntimeError('BGACK control not negated')
    return {'anchor': anchor, 'scheduled_request': anchor + delay,
            'request_on': request_on, 'request_off': request_off,
            'grant_on': grant_on, 'grant_off': grant_off,
            'grant_from_anchor_ticks': grant_on - anchor,
            'grant_from_request_ticks': grant_on - request_on,
            'bus_idle_through_handshake': True,
            'clock_edges': [[tick, row['clock']] for (tick, row), (_, old)
                            in zip(rows[1:], rows)
                            if request_on - 20 <= tick <= grant_off + 10
                            and row['clock'] != old['clock']]}


def acquire(harness, scope, lane, delay, width):
    scope.configure(lane)
    result = harness.run(lane, limit=10000)
    capture = scope.download()
    if not result['passed'] or not result['trace_complete'] or not capture.complete:
        raise RuntimeError('incomplete CPU execution/capture')
    anchor_register = 0xac if lane == 'model' else 0xb0
    anchor = struct.unpack('<I', harness.debug.read(anchor_register, 4))[0]
    product = int.from_bytes(harness.read_memory(lane, 0x220, 4), 'big')
    if product != EXPECTED_PRODUCT:
        raise RuntimeError(f'multiply changed: {product:08x}')
    return {'lane': lane, 'product': product, 'result': result,
            'capture': capture.report(), 'capture_layout': 'DATA[2:0]=BGACK_N,BG_N,BR_N',
            'timing': measure(capture, anchor, delay, width)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('sim', 'spi-sim', 'board'), default='sim')
    parser.add_argument('--delays', type=int, nargs='+', default=list(range(60, 80)))
    parser.add_argument('--width', type=int, default=80)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--stages', type=int, nargs='+', choices=(0, 1), default=[0, 1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (any(not 60 <= delay <= 79 for delay in args.delays) or
            not 40 <= args.width <= 150 or args.repeats < 1):
        parser.error('keep the request inside the qualified multiply interval')
    if args.output.exists():
        parser.error('choose a fresh evidence path')
    report = {'target': args.target, 'cases': [], 'completed': False,
              'error': None, 'cleanup_error': None,
              'prediction': 'after-falling-edge BR: unmodified fx68k grants one clock early',
              'extra_stage': 'diagnostic restoration of commented-out rBR sampling',
              'bgack': 'held negated; no external master; never drive address bus'}
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
            raise RuntimeError('unexpected CPU clock or normal responder setting')
        debug.write16(0x80, 0)
        debug.write16(0x90, 0)
        if args.target == 'board':
            transport.vccb_enable()
            debug.write16(4, 1)
            time.sleep(0.12)
        for stage in args.stages:
            for delay in args.delays:
                for repeat in range(args.repeats):
                    entry = {'stage': stage, 'delay': delay, 'width': args.width,
                             'repeat': repeat, 'runs': []}
                    path = args.output.with_suffix('') / f's{stage}-d{delay:03}-r{repeat:03}.json'
                    case = {'stage': stage, 'delay': delay, 'repeat': repeat,
                            'artifact': str(path)}
                    report['cases'].append(case)
                    try:
                        debug.write(0xa0, struct.pack('<6H', 1, delay, args.width, 0xc, 1, stage))
                        harness.load(image())
                        lanes = ('model', 'socket') if args.target == 'board' else ('model',)
                        for lane in lanes:
                            entry['runs'].append(acquire(harness, scope, lane, delay, args.width))
                        values = [r['timing']['grant_from_anchor_ticks'] for r in entry['runs']]
                        case['grant_ticks'] = values
                        print(f'stage {stage} delay {delay} repeat {repeat}: {values}', flush=True)
                    finally:
                        write_json(path, entry)
                        case['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
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
                    if any(state[k] for k in ('vccb', 'rail_1v2', 'rail_3v3')):
                        raise RuntimeError('rails remain enabled')
            except Exception as exc:
                report['cleanup_error'] = str(exc)
            finally:
                transport.close()
        report['completed'] &= report['error'] is None and report['cleanup_error'] is None
        write_json(args.output, report)
    return 0 if report['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
