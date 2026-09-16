"""Verify shared pull-down topology from DUT assignments and connector definition."""
from pathlib import Path
import csv,json,re,xml.etree.ElementTree as E
from sexpr import parse,child,children,val

def verify_bank_pulls(base,board):
 base=Path(base);name=base.name
 sch=parse((base/f'{name}.kicad_sch').read_text())
 conn=next(x for x in children(child(sch,'lib_symbols'),'symbol') if x[1]=='nuBoard:nuMezzanine_4x34')
 connector={val(pin,'name'):val(pin,'number') for unit in children(conn,'symbol') for pin in children(unit,'pin')}
 used={row['Connector signal'] for row in csv.DictReader((base/'pin-map.csv').open())}
 usedbanks={n[:2] for n in used if re.fullmatch('[TLBR][012][0-7]',n)}
 groups={bank:{f'{bank}{bit}' for bit in range(8)}-used for bank in usedbanks}
 groups={bank:pins for bank,pins in groups.items() if pins}
 table={row['Bank']:row for row in csv.DictReader((base/'unused-bank-pins.csv').open())}
 assert table.keys()==groups.keys(), 'Missing or unexpected bank pull-down'
 root=E.parse(base/'reports/netlist.xml').getroot()
 nodes={net.get('name'):{(nd.get('ref'),nd.get('pin')) for nd in net.findall('node')} for net in root.findall('./nets/net')}
 expected={node:net for net,items in nodes.items() for node in items}
 byref={f.GetReference():f for f in board.GetFootprints()}
 actual={}
 for ref,fp in byref.items():
  for pad in fp.Pads():
   key=(ref,pad.GetNumber());actual[key]=pad.GetNetname()
   assert expected.get(key)==actual[key],(key,'schematic/PCB mismatch')
 reports=[];refs=set()
 for bank,pins in sorted(groups.items()):
  row=table[bank];ref=row['Resistor'];assert ref not in refs;refs.add(ref)
  assert set(row['Unused connector signals'].split())==pins
  assert set(row['J1 pads'].split())=={connector[pin] for pin in pins}
  net='/'+row['Shared net'];want={('J1',connector[pin]) for pin in pins}|{(ref,'1')}
  assert nodes[net]==want,(bank,'shared net contains wrong pins')
  assert expected[ref,'2']=='GND' and byref[ref].GetValue()=='47k' and row['Value']=='47k'
  assert len(list(byref[ref].Pads()))==2
  mask=sum(1<<int(pin[-1]) for pin in pins)
  reports.append({'bank':bank,'resistor':ref,'resistance_ohms':47000,'shared_net':net,'unused_signals':sorted(pins),'connector_pads':sorted(connector[pin] for pin in pins),'host_output_zero_mask':f'0x{mask:02X}'})
 for pin,num in connector.items():
  if re.fullmatch('[TLBR][012][0-7]',pin) and pin[:2] not in usedbanks:
   net=expected['J1',num];assert 'unconnected-' in net and nodes[net]=={('J1',num)}
 (base/'reports/unused-bank-pins.json').write_text(json.dumps({'topology_verified':True,'host_firmware_verified':False,'bench_tested':False,'banks':reports},indent=2)+'\n')
 return reports
