import json,collections,sys
rows=json.load(open(sys.argv[1]))['rows']['rtl']
m={json.loads(l)['run']:json.loads(l) for l in open(sys.argv[2])}
sel=sys.argv[3] if len(sys.argv)>3 else 'miss'
c=collections.Counter(); ex={}
for x in rows:
    d=m[x['run']]
    st='exact' if d['exact'] else ('miss' if d['status']=='ok' else 'nomodel')
    if sel!='all' and st!=sel: continue
    f=d.get('first') or {}
    ins=x['instr']
    k=(ins,x['prev'],x['parity'],x['waits'],x['held'],x['div'],'tl_ok' if x.get('timeline_ok') else 'tl_bad:'+str(f.get('class')))
    c[k]+=1; ex.setdefault(k,x['run'])
print(sum(c.values()),'rows',len(c),'clusters')
n=int(sys.argv[4]) if len(sys.argv)>4 else 40
for k,v in c.most_common(n): print(v,*k,'|',ex[k])
