"""(MX5) Summarise efx_run sta_tclsh's `report_timing -nworst 1` report (v35_timing.sh's
spectrum): the endpoints reported, how many fail (slack < 0), per module (the endpoint's
instance path under the wrapper's `dut`, its first level) the count failing and the worst slack.

usage: v35_spectrum.py SPECTRUM_RPT
"""
import re
import sys
from collections import defaultdict

text = open(sys.argv[1]).read()
paths = []                       # {'b': begin, 'e': end, 's': slack, 'l': levels}
cur = {}
for line in text.splitlines():
    # the summary table: | n | slack | start pin | end pin | launch | capture
    m = re.match(r'\s*\d+\s*\|\s*(-?[0-9.]+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|', line)
    if m:
        paths.append({'b': m.group(2), 'e': m.group(3), 's': float(m.group(1)), 'l': '?'})
        continue
    m = re.match(r'\s*Path Begin\s*:\s*(\S+)', line)
    if m:
        cur = {'b': m.group(1)}
        continue
    m = re.match(r'\s*Path End\s*:\s*(\S+)', line)
    if m:
        cur['e'] = m.group(1)
        continue
    m = re.match(r'\s*Slack\s*:\s*(-?[0-9.]+)', line)
    if m and 'e' in cur:
        cur['s'] = float(m.group(1))
        continue
    m = re.match(r'\s*Logic Level\s*:\s*(\d+)', line)
    if m and 's' in cur:
        cur['l'] = int(m.group(1))
        paths.append(cur)
        cur = {}
if not paths:
    print('spectrum: no paths parsed; the report starts:')
    print('\n'.join(text.splitlines()[:40]))
    raise SystemExit(0)


def mod(name):
    parts = name.split('|')[0].split('/')
    if parts[0] == 'dut':
        return 'dut/' + parts[1] if len(parts) > 2 else 'dut'
    return parts[0] if len(parts) > 1 else '(wrapper)'


paths.sort(key=lambda p: p['s'])
fail = [p for p in paths if p['s'] < 0]
print(f'spectrum: {len(paths)} endpoints reported, {len(fail)} failing'
      f' (worst {paths[0]["s"]:.3f}, the last reported {paths[-1]["s"]:.3f})')
by = defaultdict(list)
for p in fail:
    by[mod(p['e'])].append(p)
for k, v in sorted(by.items(), key=lambda kv: min(p['s'] for p in kv[1])):
    w = min(v, key=lambda p: p['s'])
    print(f'  {k}: {len(v)} failing endpoints, worst {w["s"]:.3f} ({w["l"]} levels, '
          f'{w["b"]} -> {w["e"]})')
hist = defaultdict(int)
for p in fail:
    hist[int(-p['s'] // 2) * 2] += 1
if hist:
    print('  failing by slack: ' + ', '.join(f'-{k}..-{k + 2} ns {hist[k]}'
                                              for k in sorted(hist)))
by = defaultdict(int)
for p in fail:
    by[mod(p['b'])] += 1
if by:
    print('  failing paths by start module: ' + ', '.join(
        f'{k} {v}' for k, v in sorted(by.items(), key=lambda kv: -kv[1])))
