import json,sys
S='/tmp/claude-1000/-home-wickerwaka-src-nuBoard/b9107762-85c1-4fee-8904-bf25a28b914c/scratchpad'
rm={json.loads(l)['run']:json.loads(l)['exact'] for l in open(S+'/v2/qprobe/land17/miss-v35_chk.jsonl')}
f={json.loads(l)['run']:json.loads(l)['exact'] for l in open(sys.argv[1])}
b={json.loads(l)['run']:json.loads(l)['exact'] for l in open(sys.argv[2])}
lost=[r for r in f if f[r] and not b[r]]; g=[r for r in f if b[r] and not f[r]]
print(sys.argv[3], 'carries', len(lost), 'of them RTL-miss', sum(not rm[r] for r in lost), '(off gains', len(g), ')')
