"""Run with KiCad Python after netlist/XML, ERC and refilled DRC exports."""
from pathlib import Path
import csv,json,math,collections,xml.etree.ElementTree as E
import pcbnew as p
from sexpr import parse,child,children,val
from bank_pulls import verify_bank_pulls
P=Path(__file__).resolve().parents[1];repo=P.parents[1]
b=p.LoadBoard(str(P/'68030.kicad_pcb'));t=p.LoadBoard(str(repo/'hardware/daughter-template/nuDaughter.kicad_pcb'))
fs={f.GetReference():f for f in b.GetFootprints()};assert set(fs)=={'U1','J1','R1','R2'}|{f'C{i}' for i in range(1,17)}
def pads(fp):return {x.GetNumber():x for x in fp.Pads()}
u=pads(fs['U1']);j=pads(fs['J1']);tj=pads(next(f for f in t.GetFootprints() if f.GetReference()=='J1'))
assert j.keys()==tj.keys() and len(j)==136
for key in j:
 a,z=j[key],tj[key];assert a.GetPosition()==z.GetPosition() and a.GetSize()==z.GetSize() and a.GetDrillSize()==z.GetDrillSize() and a.GetOrientationDegrees()==z.GetOrientationDegrees(),key
assert fs['J1'].GetPosition()==next(f for f in t.GetFootprints() if f.GetReference()=='J1').GetPosition()
def edges(board):return sorted((int(s.GetShape()),s.GetStart().x,s.GetStart().y,s.GetEnd().x,s.GetEnd().y,s.GetWidth()) for s in board.GetDrawings() if s.GetLayer()==p.Edge_Cuts)
assert edges(b)==edges(t)
root=E.parse(P/'reports/netlist.xml').getroot();netnodes={n.get('name'):{(nd.get('ref'),nd.get('pin')) for nd in n.findall('node')} for n in root.findall('./nets/net')};expected={node:net for net,nodes in netnodes.items() for node in nodes}
for ref,fp in fs.items():
 for pin,pad in pads(fp).items():assert expected[ref,pin]==pad.GetNetname(),(ref,pin)
rows=list(csv.DictReader((P/'dut-pinout.csv').open()));source={r['PGA pin']:r for r in rows};assert len(rows)==len(source)==len(u)==128
vcc={'C6','D10','L6','K10','K4','D4','H3','F2','F11','H11'}
gnd={'C5','C7','C9','E11','J11','L9','L7','L5','J3','E3','L8','G3','F3','G11'}
nc={'D5','E12','F4','F10','K5'}
assert {k for k,r in source.items() if r['Function']=='VCC'}==vcc
assert {k for k,r in source.items() if r['Function']=='GND'}==gnd
assert {k for k,r in source.items() if r['Function']=='NC'}==nc
assert {k for k in u if u[k].GetNetname()=='/VCC_TL'}==vcc
assert {k for k in u if u[k].GetNetname()=='GND'}==gnd
# Independent occupied-row geometry and direct CPU lead fit, top view rotated180.
occupied={}
for row in 'ABCDEFGHJKLMN':
 occupied[row]=set(range(1,14)) if row in 'ABCLMN' else ({1,2,3,4,5,10,11,12,13} if row in 'DK' else {1,2,3,4,10,11,12,13} if row=='F' else {1,2,3,11,12,13})
assert set(u)=={r+str(c) for r,cols in occupied.items() for c in cols}
assert fs['U1'].GetOrientationDegrees()==180
for key,pad in u.items():
 row=key[0];col=int(key[1:]);x=150.99+(col-7)*2.54;y=96+('ABCDEFGHJKLMN'.index(row)-6)*2.54
 assert abs(p.ToMM(pad.GetPosition().x)-x)<1e-5 and abs(p.ToMM(pad.GetPosition().y)-y)<1e-5,key
 assert pad.GetSize()==p.VECTOR2I(p.FromMM(1.5),p.FromMM(1.5)) and pad.GetDrillSize()==p.VECTOR2I(p.FromMM(.8),p.FromMM(.8))
 assert (.8-.56)/2>=.119 and (1.5-.8)/2>=.349
assert u['A1'].GetShape()==p.PAD_SHAPE_RECT
# Source symbol function, polarity and electrical type include the bidirectional RESET output.
sch=parse((P/'68030.kicad_sch').read_text());local=child(parse((P/'68030.kicad_sym').read_text()),'symbol');embedded=next(x for x in children(child(sch,'lib_symbols'),'symbol') if x[1]=='68030:MC68030RC')
for definition in [local,embedded]:
 sp=[pin for sub in children(definition,'symbol') for pin in children(sub,'pin')]
 assert len(sp)==128 and {val(pin,'number'):(val(pin,'name'),str(pin[1])) for pin in sp}=={k:(r['Symbol name'],r['Electrical type']) for k,r in source.items()}
assert source['F12']['Electrical type']=='open_collector' and source['H2']['Electrical type']=='input'
assert source['B2']['Electrical type']=='output' and source['M2']['Electrical type']=='output'
pinmap=list(csv.DictReader((P/'pin-map.csv').open()));assert len(pinmap)==128
for r in pinmap:
 pin=r['PGA pin'];net=r['Net label']
 if net=='-':assert pin in nc and netnodes[expected['U1',pin]]=={('U1',pin)} and 'unconnected-' in expected['U1',pin]
 else:
  assert expected['U1',pin]==('GND' if net=='GND' else '/'+net)
  if r['J1 pad'].isdigit():assert expected['J1',r['J1 pad']]==expected['U1',pin]
for pin in nc:assert not any(x.GetNetname()==expected['U1',pin] for x in b.GetTracks())
assert j['68'].GetNetname()=='GND'
for pin in ['34','35','69','103']:
 net=expected['J1',pin];assert 'unconnected-' in net and netnodes[net]=={('J1',pin)} and not any(x.GetNetname()==net for x in b.GetTracks())
for i in range(1,17):
 ref=f'C{i}';want='100nF' if i<=10 else '330pF' if i<=15 else '10uF'
 assert fs[ref].GetValue()==want and expected[ref,'1']=='/VCC_TL' and expected[ref,'2']=='GND'
 pp=pads(fs[ref]);spacing=2 if i==16 else 5;assert abs(p.ToMM((pp['1'].GetPosition()-pp['2'].GetPosition()).EuclideanNorm())-spacing)<1e-6
track=[x for x in b.GetTracks() if not isinstance(x,p.PCB_VIA)];vias=[x for x in b.GetTracks() if isinstance(x,p.PCB_VIA)]
assert b.GetCopperLayerCount()==2
assert all(x.GetLayer() in [p.F_Cu,p.B_Cu] and x.GetWidth()==p.FromMM(.2) for x in track)
assert all(x.GetWidth(p.F_Cu)==p.FromMM(.5) and x.GetDrillValue()==p.FromMM(.3) and x.GetViaType()==p.VIATYPE_THROUGH for x in vias)
zones=list(b.Zones());assert len(zones)==2 and {(z.GetLayer(),z.GetNetname()) for z in zones}=={(p.B_Cu,'GND'),(p.F_Cu,'/VCC_TL')}
assert all(z.GetIslandRemovalMode()==p.ISLAND_REMOVAL_MODE_ALWAYS for z in zones)
pulls=verify_bank_pulls(P,b);assert len(pulls)==2
# Independent manufacturer-direction sets: only address, data and three-state controls may be driven on takeover.
logical={r['Function']:r['PGA pin'] for r in rows if r['Function'] not in ['VCC','GND','NC']}
bankpins=collections.defaultdict(set)
for r in pinmap:
 if r['Bank']!='-':bankpins[r['Bank']].add(r['PGA pin'])
assert len(bankpins)==12 and sum(map(len,bankpins.values()))==90
bybank={'R0':set(range(0,8)),'B2':set(range(8,16)),'B1':set(range(16,24)),'B0':set(range(24,32))}
for bank,bits in bybank.items():assert bankpins[bank]=={logical[f'D{bit}'] for bit in bits}
always={logical[n] for n in 'BG ECS OCS IPEND REFILL STATUS'.split()}
tri={k for k,r in source.items() if r['Electrical type']=='tri_state'};data={logical[f'D{i}'] for i in range(32)}
inputs={logical[n] for n in 'DSACK0 DSACK1 STERM CIIN CBACK AVEC BERR HALT'.split()}
assert bankpins['R1']==always and bankpins['L1']==inputs
profiles={}
def profile(name,data_mode='Z',width=0,reset=False,takeover=False,drive_released=False):
 out=set(always);inp=set(inputs);released=set(data)
 if reset or takeover:released|=tri
 else:out|=tri
 if data_mode=='D':out|=data;released-=data
 elif data_mode=='H':
  selected={logical[f'D{i}'] for i in range(32-width,32)};inp|=selected;released-=selected
 if drive_released:inp|=tri|data;released-=tri|data
 dirs={}
 for bank,pins in bankpins.items():
  assert not (pins&out and pins&inp),(name,bank)
  dirs[bank]='H' if pins&inp else 'D' if pins&out else 'Z' if reset or bank in bybank else 'D'
  if dirs[bank]=='H':assert not pins&out
 assert dirs['R1']=='D' and dirs['L1']=='H'
 profiles[name]=dirs
profile('power_reset',reset=True);profile('idle_turnaround')
for width in [8,16,32]:
 profile(f'asynchronous_read_port{width}','H',width);profile(f'CPU_write_port{width}','D')
profile('synchronous_read32','H',32);profile('burst_fill32','H',32);profile('interrupt_vector8','H',8);profile('interrupt_autovector')
profile('wait_no_response');profile('halt_or_STOP');profile('RMC_write','D');profile('retry_turnaround')
profile('takeover_observe',takeover=True);profile('takeover_drive',takeover=True,drive_released=True);profile('takeover_release',takeover=True);profile('single_wire_granted',takeover=True,drive_released=True)
e=json.loads((P/'reports/erc.json').read_text());d=json.loads((P/'reports/drc.json').read_text());assert not any(s['violations'] for s in e['sheets']);assert not d['violations'] and not d['unconnected_items'] and not d['schematic_parity']
summary={'status':'layout_verified_bench_qualification_pending','dut':'Motorola MC68030RC25B','package':'CPGA128, CASE789C-01, direct through-hole mounting','supply_v':5,'supply_tolerance_percent':5,'clock_range_mhz':[12.5,25],'dut_pins_verified':128,'VCC_pins':10,'GND_pins':14,'NC_pins':5,'connector_pads_unchanged':136,'outline_unchanged':True,'schematic_netlist_matches_pcb':True,'copper_layers':2,'track_segments':len(track),'track_width_mm':.2,'vias':len(vias),'via_diameter_mm':.5,'via_drill_mm':.3,'filled_regions':{('F.Cu' if z.GetLayer()==p.F_Cu else 'B.Cu'):{'net':z.GetNetname(),'count':z.GetFilledPolysList(z.GetLayer()).OutlineCount()} for z in zones},'clock_track_length_mm':round(sum(p.ToMM(x.GetLength()) for x in track if x.GetNetname()=='/LCLK'),3),'bank_profiles_checked':len(profiles),'unused_bank_pulls':pulls,'erc_violations':0,'drc_violations':0,'unrouted_connections':0,'schematic_parity_issues':0,'hardware_tested':False,'host_firmware_verified':False,'timing_qualified':False,'TTL_CMOS_high_margin':'Not guaranteed: CPU VOH 2.4 V; host VIH 0.7*VCCB','bus_keeper_drive_margin':'Not guaranteed: CPU IOH400uA vs up to900uA keeper overdrive','kicad_version':p.Version()}
(P/'reports/verification.json').write_text(json.dumps(summary,indent=2)+'\n');(P/'reports/bank-profiles.json').write_text(json.dumps(profiles,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='unused_bank_pulls'},indent=2))
