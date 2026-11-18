import json,collections,sys,re
rows=json.load(open(sys.argv[1]))['rows']['rtl']
m={json.loads(l)['run']:json.loads(l) for l in open(sys.argv[2])}
c=collections.Counter(); ex=collections.defaultdict(set)
def gen(i):
    if i.startswith('M0') or i.startswith('M1') or i.startswith('LS') or i.startswith('END'): return i
    i=re.sub(r'_t00[0-9a-f]+','_T',i)
    return i
for x in rows:
    d=m[x['run']]
    st='exact' if d['exact'] else ('miss' if d['status']=='ok' else 'nomodel')
    if st!=sys.argv[3]: continue
    k=(x['div'], 'W0' if x['waits']==0 else 'W12', x['parity'], 'tl' if x.get('timeline_ok') else 'tlbad')
    c[k]+=1; ex[k].add(gen(x['instr'])+'<'+gen(x['prev']))
print(sum(c.values()))
for k,v in c.most_common(int(sys.argv[4])): print(v,*k,'|',' '.join(sorted(ex[k]))[:330])
