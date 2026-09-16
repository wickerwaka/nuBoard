import pcbnew as p
import xml.etree.ElementTree as E
import json,csv,math,collections
from pathlib import Path
P=Path(__file__).resolve().parents[1];b=p.LoadBoard(str(P/'z80.kicad_pcb'));t=p.LoadBoard(str(P.parents[1]/'hardware/daughter-template/nuDaughter.kicad_pcb'))
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
assert len(rows)==40 and {int(x['DUT pin']) for x in rows}==set(range(1,41))
for row in rows:
 pad=up[row['DUT pin']];net=pad.GetNetname()
 assert net==('GND' if row['Connector signal']=='GND' else '/'+row['Connector signal']),row
 if row['Connector signal']!='GND':assert net==j[row['J1 pad']].GetNetname(),row
assert set(byref)=={'R7', 'R9', 'R11', 'U1', 'R6', 'R4', 'R10', 'R8', 'R5', 'C1', 'J1', 'R2', 'R1'}
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
assert zones[0].GetFilledPolysList(p.B_Cu).OutlineCount()==1
# Physical library correspondence and actual package dimensions.
assert len(up)==40 and abs(p.ToMM(up['1'].GetPosition().x-up['40'].GetPosition().x))==15.24
assert abs(p.ToMM(up['1'].GetPosition().y-up['2'].GetPosition().y))==2.54
assert all(pad.GetDrillSize()==p.VECTOR2I(p.FromMM(.8),p.FromMM(.8)) for pad in up.values())
e=json.load((P/'reports/erc.json').open());d=json.load((P/'reports/drc.json').open())
assert not any(s['violations'] for s in e['sheets'])
assert not d['violations'] and not d['unconnected_items'] and not d['schematic_parity']
summary={'status':'passed','kicad_version':p.Version(),'dut':'Z84C0008PEG','supply_v':5,'clock_mhz':8,'dut_pins_verified':40,'connector_pads_unchanged':len(j),'outline_unchanged':True,'voltage_select':{'5V_SELECT':'direct GND','3V3_SELECT':'unconnected on daughter board'},'schematic_netlist_matches_pcb':True,'copper_layers':2,'track_segments':len(tracks),'track_width_mm':.2,'vias':len(vias),'via_preset_mm':{'diameter':.5,'drill':.3},'ground_plane_layer':'B.Cu','ground_plane_connected_polygons':1,'erc_violations':0,'drc_violations':0,'unrouted_connections':0,'schematic_parity_issues':0,'hardware_tested':False,'bus_hold_drive_margin':'Not guaranteed; direct connection retained by user instruction','voltage_select_firmware':'Required 5V interpretation documented; host firmware not available'}
from bank_pulls import verify_bank_pulls
summary['unused_bank_pulls']=verify_bank_pulls(P,b)
(P/'reports/verification.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
