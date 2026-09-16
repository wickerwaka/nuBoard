import re,json
class A(str): pass
def parse(s):
 stack=[]; root=None
 for t in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+',s):
  if t=='(':
   n=[]
   if stack: stack[-1].append(n)
   else: root=n
   stack.append(n)
  elif t==')': stack.pop()
  else: stack[-1].append(json.loads(t) if t.startswith('"') else A(t))
 return root
def dump(n,level=0):
 if isinstance(n,list):
  if not any(isinstance(v,list) for v in n): return '('+' '.join(dump(v) for v in n)+')'
  return '('+ ' '.join(dump(v) if not isinstance(v,list) else '\n'+'  '*(level+1)+dump(v,level+1) for v in n)+')'
 return str(n) if isinstance(n,A) else json.dumps(n,ensure_ascii=False)
def children(n,k): return [x for x in n if isinstance(x,list) and x and x[0]==k]
def child(n,k): return next((x for x in children(n,k)),None)
def val(n,k): return child(n,k)[1]
