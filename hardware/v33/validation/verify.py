import pcbnew as p
import xml.etree.ElementTree as E
import json,csv,math,collections
from pathlib import Path
P=Path(__file__).resolve().parents[1];b=p.LoadBoard(str(P/'v33.kicad_pcb'));t=p.LoadBoard(str(P.parents[1]/'hardware/daughter-template/nuDaughter.kicad_pcb'))
byref={f.GetReference():f for f in b.GetFootprints()}
def padmap(fp):return {x.GetNumber():x for x in fp.Pads()}
j=padmap(byref['J1']);tj=padmap(next(f for f in t.GetFootprints() if f.GetReference()=='J1'))
assert j.keys()==tj.keys()
for n in j:
 assert j[n].GetPosition()==tj[n].GetPosition() and j[n].GetSize()==tj[n].GetSize() and j[n].GetDrillSize()==tj[n].GetDrillSize(),n
# Exact board Edge.Cuts geometry, independent of drawing UUID changes.
def edges(board):
 return sorted((int(s.GetShape()),s.GetStart().x,s.GetStart().y,s.GetEnd().x,s.GetEnd().y,s.GetWidth()) for s in board.GetDrawings() if s.GetLayer()==p.Edge_Cuts)
assert edges(b)==edges(t)
r=E.parse(P/'reports/netlist.xml').getroot();expected={}
for net in r.findall('./nets/net'):
 for nd in net.findall('node'):expected[nd.get('ref'),nd.get('pin')]=net.get('name')
for ref,fp in byref.items():
 for n,pad in padmap(fp).items():
  if (ref,n) in expected: assert pad.GetNetname()==expected[ref,n],(ref,n,pad.GetNetname(),expected[ref,n])
up=padmap(byref['U1']);rows=list(csv.DictReader((P/'pin-map.csv').open()))
assert len(rows)==68 and {int(x['PLCC pin']) for x in rows}==set(range(1,69))
for row in rows:
 pad=up[row['PLCC pin']];net=pad.GetNetname()
 assert net==('GND' if row['Connector signal']=='GND' else '/'+row['Connector signal']),row
 if row['Connector signal']!='GND':assert net==j[row['J1 pad']].GetNetname(),row
assert set(byref)=={'C3', 'C4', 'C2', 'R3', 'R4', 'U1', 'C1', 'J1', 'R2', 'R1'}
assert j['68'].GetNetname()=='GND'
assert 'unconnected-' in j['34'].GetNetname()
assert sum(pad.GetNetname()==j['34'].GetNetname() for fp in byref.values() for pad in fp.Pads())==1
assert not any(t.GetNetname()==j['34'].GetNetname() for t in b.GetTracks())
assert b.GetCopperLayerCount()==2
tracks=[x for x in b.GetTracks() if not isinstance(x,p.PCB_VIA)];vias=[x for x in b.GetTracks() if isinstance(x,p.PCB_VIA)]
assert all(x.GetWidth()==p.FromMM(.2) for x in tracks)
assert all(x.GetWidth(p.F_Cu)==p.FromMM(.5) and x.GetDrillValue()==p.FromMM(.3) for x in vias)
assert all(x.GetLayer() in (p.F_Cu,p.B_Cu) for x in tracks)
zones=list(b.Zones());assert len(zones)==1 and zones[0].GetNetname()=='GND' and zones[0].GetLayer()==p.B_Cu
assert zones[0].GetIslandRemovalMode()==p.ISLAND_REMOVAL_MODE_ALWAYS
assert zones[0].GetFilledPolysList(p.B_Cu).OutlineCount()==2
# Physical library correspondence and actual package dimensions.
assert len(up)==68
assert all(pad.GetDrillSize()==p.VECTOR2I(p.FromMM(.8),p.FromMM(.8)) for pad in up.values())
lib=p.FootprintLoad(str(P/'v33.pretty'),'PLCC-68_THT-Socket')
lp=padmap(lib)
for n,pad in up.items():
 assert pad.GetPosition()-byref['U1'].GetPosition()==lp[n].GetPosition(),n
 assert pad.GetSize()==lp[n].GetSize(),n
assert all(up[str(n)].GetNetname()=='/VCC_TL' for n in (1,19,35,53))
assert all(up[str(n)].GetNetname()=='GND' for n in (2,18,36,52))
e=json.load((P/'reports/erc.json').open());d=json.load((P/'reports/drc.json').open())
assert not any(s['violations'] for s in e['sheets'])
assert not d['violations'] and not d['unconnected_items'] and not d['schematic_parity']
summary={'status':'layout_checks_passed_clock_qualification_pending','kicad_version':p.Version(),'dut':'uPD70136L-16, PLCC68 socket','supply_v':5,'clock_mhz':None,'speed_suffix':'L-16','cpu_rated_max_mhz':16,'dut_pins_verified':68,'connector_pads_unchanged':len(j),'outline_unchanged':True,'voltage_select':{'5V_SELECT':'direct GND','3V3_SELECT':'unconnected on daughter board'},'schematic_netlist_matches_pcb':True,'copper_layers':2,'track_segments':len(tracks),'track_width_mm':.2,'vias':len(vias),'via_preset_mm':{'diameter':.5,'drill':.3},'ground_plane_layer':'B.Cu','ground_plane_fill_polygons':2,'ground_plane_connectivity':'DRC verified; regions joined through C1 ground pad','erc_violations':0,'drc_violations':0,'unrouted_connections':0,'schematic_parity_issues':0,'hardware_tested':False,'bus_hold_drive_margin':'Not guaranteed; direct connection retained by user instruction','voltage_select_firmware':'Required 5V interpretation documented; host firmware not available'}
from bank_pulls import verify_bank_pulls
summary['unused_bank_pulls']=verify_bank_pulls(P,b)
(P/'reports/verification.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
