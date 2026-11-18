"""Synthetic 2.6MB ledger. Local Git wall times, never a GitHub network benchmark."""
import copy,tempfile,time,json
from pathlib import Path
from git_adapters import *
from local_gitdata_fixture import LocalGitData
from test_git_adapters import gate
from test_checkpoint import fixture,items,validator,NOW

def baseline():
 with tempfile.TemporaryDirectory() as d:
  io=LocalGitData(Path(d)/'git');s=fixture();s['fixture_padding']='x'*2600000;io.seed(DISPATCH,{'state.json':canonical(s),'other':'unchanged'});writer=GitHubAggregate(io,gate('aggregate'))
  start=time.monotonic()
  for item in items(s):
   h,b,c=writer.read_state();p=prepare(h,b,[item],validator,NOW)['payload'];candidate=writer.commit(h,c['tree'],{'state.json':canonical(p['after'])},'single fixture result')
   hh,bb,cc=writer.read_state();assert hh==h
   writer.call('update_ref',DISPATCH,h,candidate);assert writer.read_state()[1]==p['after']
  return {'wall_seconds':time.monotonic()-start,'metrics':writer.metrics.summary(),'cas_updates':io.updates}
def aggregate():
 with tempfile.TemporaryDirectory() as d:
  io=LocalGitData(Path(d)/'git');s=fixture();s['fixture_padding']='x'*2600000;io.seed(DISPATCH,{'state.json':canonical(s),'other':'unchanged'});io.seed(ARCHIVE,{'README':'fixture'})
  archive=GitHubArchive(io,gate('archive'));writer=GitHubAggregate(io,gate('aggregate'));its=items(s);start=time.monotonic()
  for item in its:assert archive.put(item)['status']=='accepted'
  assert writer.publish(its,validator,archive,Path(d)/'outbox',lambda:NOW)['status']=='accepted'
  return {'wall_seconds':time.monotonic()-start,'aggregate_metrics':writer.metrics.summary(),'archive_metrics':archive.metrics.summary(),'cas_updates':io.updates}
if __name__=='__main__':print(json.dumps({'scope':'5 synthetic completed rows only; excludes body/search reservations, real classification and GitHub latency','baseline_single_row':baseline(),'archive_and_aggregate':aggregate()},indent=2))
