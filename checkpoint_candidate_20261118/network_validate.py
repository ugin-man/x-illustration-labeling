"""Validator for explicit synthetic-only remote test scope, never production activation."""
import json,sys,time
from git_adapters import complete_tree_sha,git_object_sha
from checkpoint import prepare
from test_checkpoint import validator
x=json.loads(sys.argv[1])
if x['op']=='tree':
 b=x['base'];n=x['candidate'];ed=x['edits']
 assert complete_tree_sha(b)==x['base_sha'];assert complete_tree_sha(n)==x['candidate_sha']
 assert set(n)==set(b)|set(ed)
 for p,e in n.items():
  assert e==(dict(mode='100644',type='blob',sha=git_object_sha('blob',ed[p].encode())) if p in ed else b[p])
 print(json.dumps({'verified':True}))
elif x['op']=='prepare':
 print(json.dumps(prepare(x['head'],x['state'],x['items'],validator,time.time())))
else:raise ValueError('unknown')
