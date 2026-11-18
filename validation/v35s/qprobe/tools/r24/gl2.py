import json,sys,collections,re
a={json.loads(l)['run']:json.loads(l) for l in open(sys.argv[1])}
b={json.loads(l)['run']:json.loads(l) for l in open(sys.argv[2])}
n=int(sys.argv[3]) if len(sys.argv)>3 else 400
g=[r for r in a if not a[r]['exact'] and b[r]['exact']]
l=[r for r in a if a[r]['exact'] and not b[r]['exact']]
print(sys.argv[2].split('/')[-1],'exact',sum(x['exact'] for x in b.values()),'gained',len(g),'lost',len(l))
def stem(r): return re.sub(r'-p[EO]-w\d$','',r)
def show(name,rs):
    if not rs: return
    c=collections.Counter(stem(r) for r in rs)
    print('  ',name, dict(collections.Counter(r[-5:] for r in rs)), ' '.join(f"{k}:{v}" for k,v in sorted(c.items()))[:n])
if '-g' in sys.argv: show('GAINED',g)
show('LOST',l)
