"""Run with KiCad's Python after exporting reports/netlist.xml and ERC/DRC JSON."""
from pathlib import Path
import pcbnew as p
import xml.etree.ElementTree as E
import csv,json,math,collections
from sexpr import parse,children,child,val
P=Path(__file__).resolve().parents[1];repo=P.parents[1]
b=p.LoadBoard(str(P/'v35s.kicad_pcb'));t=p.LoadBoard(str(repo/'hardware/daughter-template/nuDaughter.kicad_pcb'))
byref={f.GetReference():f for f in b.GetFootprints()}
def pads(fp):return {x.GetNumber():x for x in fp.Pads()}
j=pads(byref['J1']);tj=pads(next(f for f in t.GetFootprints() if f.GetReference()=='J1'));up=pads(byref['U1'])
assert set(byref)=={'C3', 'R7', 'R5', 'C2', 'R3', 'R6', 'R4', 'R8', 'U1', 'C1', 'J1', 'R2', 'R1'}
assert j.keys()==tj.keys() and len(j)==136
for key in j:
 a,z=j[key],tj[key]
 assert a.GetPosition()==z.GetPosition() and a.GetSize()==z.GetSize() and a.GetDrillSize()==z.GetDrillSize() and a.GetOrientationDegrees()==z.GetOrientationDegrees(),key
assert byref['J1'].GetPosition()==next(f for f in t.GetFootprints() if f.GetReference()=='J1').GetPosition()
def edges(board):return sorted((int(s.GetShape()),s.GetStart().x,s.GetStart().y,s.GetEnd().x,s.GetEnd().y,s.GetWidth()) for s in board.GetDrawings() if s.GetLayer()==p.Edge_Cuts)
assert edges(b)==edges(t)
r=E.parse(P/'reports/netlist.xml').getroot();expected={};netnodes={}
for n in r.findall('./nets/net'):
 ns={(nd.get('ref'),nd.get('pin')) for nd in n.findall('node')};netnodes[n.get('name')]=ns
 for node in ns:expected[node]=n.get('name')
for ref,f in byref.items():
 for num,pad in pads(f).items():
  assert (ref,num) in expected,(ref,num,'missing from netlist')
  assert pad.GetNetname()==expected[ref,num],(ref,num,pad.GetNetname(),expected[ref,num])
rows=list(csv.DictReader((P/'pin-map.csv').open()));assert len(rows)==84 and {int(x['PLCC pin']) for x in rows}==set(range(1,85))
for row in rows:
 pin=row['PLCC pin'];net=row['Net label'];want='GND' if net=='GND' else '/'+net
 assert up[pin].GetNetname()==want,row
 if row['J1 pad'].isdigit():assert up[pin].GetNetname()==j[row['J1 pad']].GetNetname(),row
# Verify the exact separately transcribed pinout against both local and embedded symbol libraries.
sch=parse((P/'v35s.kicad_sch').read_text());sym=child(parse((P/'v35s.kicad_sym').read_text()),'symbol');emb=next(x for x in children(child(sch,'lib_symbols'),'symbol') if x[1]=='v35s:uPD70337L')
datasheetpins={int(x['PLCC pin']):(x['Function'],x['Electrical type']) for x in csv.DictReader((P/'dut-pinout.csv').open())}
for definition in [sym,emb]:
 sp=[pin for sub in children(definition,'symbol') for pin in children(sub,'pin')]
 assert len(sp)==84 and len({val(pin,'number') for pin in sp})==84
 assert {int(val(pin,'number')):(val(pin,'name'),str(pin[1])) for pin in sp}==datasheetpins
assert datasheetpins[48][0]=='P20/DMARQ0' and datasheetpins[54][0]=='P23/DMARQ1' and datasheetpins[58][0]=='P27/HLDRQ'
assert datasheetpins[57][0]=='P26/~{HLDAK}'
# Voltage ID and mandatory IC tie-offs, tested as node sets, not just net names.
assert j['68'].GetNetname()=='GND'
ncnet=j['34'].GetNetname();assert 'unconnected-' in ncnet and netnodes[ncnet]=={('J1','34')}
assert not any(x.GetNetname()==ncnet for x in b.GetTracks())
assert netnodes['/IC_BIAS']=={('U1','3'),('U1','49'),('U1','75'),('R2','2')}
assert netnodes['/RESERVED_PD']=={('U1','9'),('R1','1')}
assert expected['R1','2']=='GND' and expected['R2','1']=='/VCC_TL'
assert byref['R1'].GetValue()=='6.8k' and byref['R2'].GetValue()=='15k'
assert {pin for pin in up if up[pin].GetNetname()=='/VCC_TL'}=={'50','76','80'}
assert {pin for pin in up if up[pin].GetNetname()=='GND'}=={'42','77'}
for ref in ['C1','C2','C3']:
 assert byref[ref].GetValue()=='100nF' and expected[ref,'1']=='/VCC_TL' and expected[ref,'2']=='GND'
 cp=pads(byref[ref]);assert abs(p.ToMM((cp['1'].GetPosition()-cp['2'].GetPosition()).EuclideanNorm())-2.075)<1e-6
# Independent Assmann 84-way socket grid derivation. NEC numbering: top 75..84,1..11; left 12..32; bottom33..53; right54..74.
assert byref['U1'].GetOrientationDegrees()==0
for key,pa in up.items():
 n=int(key)
 if n<=11:x,y=-2.54*((n-1)//2),0 if n%2 else 2.54
 elif n<=32:i=n-12;x,y=(-15.24 if i%2==0 else -12.7),2.54*(i//2+1)
 elif n<=53:i=n-33;x,y=-12.7+2.54*(i//2),30.48 if i%2==0 else 27.94
 elif n<=74:i=n-54;x,y=(15.24 if i%2==0 else 12.7),27.94-2.54*(i//2)
 else:i=n-75;x,y=12.7-2.54*(i//2),0 if i%2==0 else 2.54
 rel=pa.GetPosition()-byref['U1'].GetPosition()
 assert abs(p.ToMM(rel.x)-x)<1e-6 and abs(p.ToMM(rel.y)-y)<1e-6,n
 assert pa.GetDrillSize()==p.VECTOR2I(p.FromMM(.8),p.FromMM(.8))
 assert pa.GetSize()==p.VECTOR2I(p.FromMM(1.4224),p.FromMM(1.4224))
 assert (p.ToMM(pa.GetSize().x)-p.ToMM(pa.GetDrillSize().x))/2 >= .3
tracks=[x for x in b.GetTracks() if not isinstance(x,p.PCB_VIA)];vias=[x for x in b.GetTracks() if isinstance(x,p.PCB_VIA)]
assert b.GetCopperLayerCount()==2
assert all(x.GetLayer() in [p.F_Cu,p.B_Cu] and x.GetWidth()==p.FromMM(.2) for x in tracks)
assert all(x.GetWidth(p.F_Cu)==p.FromMM(.5) and x.GetDrillValue()==p.FromMM(.3) and x.GetViaType()==p.VIATYPE_THROUGH for x in vias)
zones=list(b.Zones());assert len(zones)==2 and {z.GetLayer() for z in zones}=={p.F_Cu,p.B_Cu}
assert all(z.GetNetname()=='GND' and z.GetIslandRemovalMode()==p.ISLAND_REMOVAL_MODE_ALWAYS for z in zones)
assert next(z for z in zones if z.GetLayer()==p.F_Cu).GetFilledPolysList(p.F_Cu).OutlineCount()==1
assert sum(x.GetNetname()=='GND' for x in vias)==13
assert up['77'].GetLocalZoneConnection()==p.ZONE_CONNECTION_FULL
# Compatible physical drive direction in all documented operating profiles.
bankpins=collections.defaultdict(list)
for row in rows:
 if row['Bank']!='-':bankpins[row['Bank']].append(int(row['PLCC pin']))
assert set(bankpins)=={s+str(n) for s in 'TLBR' for n in range(3)}
base={'L0':'Z','L1':'Z','L2':'D','B0':'D','T1':'D','T2':'H','T0':'H','R2':'H','B2':'H','R0':'D','R1':'H','B1':'H'}
profiles={}
def profile(name,changes=None,hold=False):
 banks=base| (changes or {})
 # This independent partition is driven by datasheet function, not assigned connector bank.
 out=set(range(29,41))|{1,2,82,83,84,44,47,51,52,55,56,57};inp={41,45,46,53,59,60,61,81}|set(range(67,75));released=set(range(13,29))
 if hold:out-=set(range(29,41))|{1,2,82,83,84};released|=set(range(29,41))|{1,2,82,83,84}
 for ps,bank in [([4,5,6,7,8,10,11,12],'T2'),([63,66],'T0'),([43,62,64,65],'R2'),([48,54,58],'B2'),([51,52,55,56,57],'R0'),(list(range(13,21)),'L0'),(list(range(21,29)),'L1')]:
  for pin in ps:
   out.discard(pin);inp.discard(pin);released.discard(pin)
  (inp if banks[bank]=='H' else out if banks[bank]=='D' else released).update(ps)
 for bank,ps in bankpins.items():
  if banks[bank]=='H':assert not set(ps)&out,(name,bank,'contention')
  elif banks[bank]=='D':assert not set(ps)&inp,(name,bank,'undriven input')
 profiles[name]=banks
profile('reset_ports_input',{'R0':'H'})
profile('CPU_address_idle');profile('CPU_read_word',{'L0':'H','L1':'H'});profile('CPU_write_word',{'L0':'D','L1':'D'})
profile('CPU_read_low_byte',{'L0':'H'});profile('CPU_read_high_byte',{'L1':'H'});profile('turnaround')
for channel in [0,1]:
 for mode in ['mem_mem_single_step','mem_mem_burst']:
  profile(f'DMA{channel}_{mode}_source',{'L0':'H','L1':'H'});profile(f'DMA{channel}_{mode}_destination',{'L0':'D','L1':'D'})
 for mode in ['IO_mem_demand','mem_IO_demand','IO_mem_single','mem_IO_single']:profile(f'DMA{channel}_{mode}',{'L0':'H','L1':'H'})
profile('hold_granted',hold=True);profile('hold_data_stimulus_refresh_disabled',{'L0':'H','L1':'H'},hold=True);profile('hold_release',hold=True)
profile('hold_refresh_observe',hold=True);profile('halt');profile('stop')
profile('P0_all_output_or_CLKOUT',{'T2':'D'})
profile('P1_GPIO_output_INTAK_CTS0_internal_clock',{'T0':'D','R2':'D'})
profile('P1_peripheral_output_INTAK_CTS0_internal_clock',{'R2':'D'})
profile('P2_all_input',{'B2':'H','R0':'H'});profile('P2_all_output',{'B2':'D','R0':'D'})
profile('GPIO_transition_disabled',{'T2':'Z','T0':'Z','R2':'Z','B2':'Z','R0':'Z'})
e=json.loads((P/'reports/erc.json').read_text());d=json.loads((P/'reports/drc.json').read_text())
assert not any(s['violations'] for s in e['sheets']);assert not d['violations'] and not d['unconnected_items'] and not d['schematic_parity']
lengths={net:round(sum(p.ToMM(x.GetLength()) for x in tracks if x.GetNetname()==net),3) for net in ['/RCLK','/TCLK']}
summary={'status':'layout_verified_bench_test_pending','dut':'NEC uPD70337L-8-xxx, PLCC84; factory table suffix unknown','supply_v':5,'socket':'Assmann A-CCS 084-Z-T','kicad_version':p.Version(),'dut_pins_verified':84,'connector_pads_unchanged':136,'mechanical_outline_unchanged':True,'schematic_netlist_matches_pcb':True,'voltage_select':{'5V_SELECT':'direct GND','3V3_SELECT':'floating and unrouted'},'copper_layers':2,'track_segments':len(tracks),'track_width_mm':.2,'vias':len(vias),'via_diameter_mm':.5,'via_drill_mm':.3,'ground_stitch_vias':13,'ground_pours':{'F.Cu':1,'B.Cu':3},'ground_connectivity':'All ground pads connected; B.Cu subregions joined through F.Cu, plated pads and stitching; unconnected islands removed','clock_track_lengths_mm':lengths,'bank_profiles_checked':len(profiles),'erc_violations':0,'drc_violations':0,'unrouted_connections':0,'schematic_parity_issues':0,'hardware_tested':False,'timing_qualified':False,'bus_keeper_margin':'Not guaranteed; direct experimental interface selected by user','security_translation_table':'Unknown until physical suffix/table is identified'}
from bank_pulls import verify_bank_pulls
summary['unused_bank_pulls']=verify_bank_pulls(P,b)
(P/'reports/verification.json').write_text(json.dumps(summary,indent=2)+'\n');(P/'reports/bank-profiles.json').write_text(json.dumps(profiles,indent=2)+'\n');print(json.dumps(summary,indent=2))
