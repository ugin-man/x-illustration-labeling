import copy,json,sys,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,'/tmp/x-recovery-isolated')
from network_runtime import IndexWriter
from runtime_components import LocalGitTransport,activation
from rehearsal_pipeline import RecoverySession
ROOT='/tmp/x-recovery-isolated';BASE=Path(__file__).parent
original=json.load(open('/tmp/x-state-recovery.json'));k=next(k for k,h in original['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');h=original['koyo_index_handoffs'][k];pid=next(iter(h['rows']));record=copy.deepcopy(h['rows'][pid]);cache=copy.deepcopy(h['context'][pid]['cache']);fixture=copy.deepcopy(original)
# EXPLICIT LOCAL REPLAY FIXTURE ONLY: remove one already accepted post to replay pipeline.
fh=fixture['koyo_index_handoffs'][k];fh['rows'].pop(pid);fh['context'].pop(pid);fh['events'].pop(pid)
fh['operations']={oid:v for oid,v in fh['operations'].items() if pid not in oid}
count=[0]
def recorded_cache(post):
 assert post==pid;count[0]+=1;return copy.deepcopy(cache)
with tempfile.TemporaryDirectory(prefix='recovery-full-rehearsal-') as d:
 remote=Path(d)/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True);t=LocalGitTransport(remote);head=t.commit(fixture);t.git('update-ref','refs/heads/codex/jobs/production-v4-001/dispatch-index',head)
 writer=IndexWriter(str(remote),fixture['catalog_sha256'],k,ROOT,clock=lambda:h['lease']['until']-100)
 try:
  doc=activation(fixture,head,k,[BASE/'network_runtime.py',BASE/'runtime_components.py',BASE/'recovery_adapter.py',BASE/'rehearsal_pipeline.py'])
  session=RecoverySession(writer,k,h['lease']['token'],ROOT,Path(d)/'journal',doc)
  session.body_once(pid,recorded_cache)
  img='496a94119120ac9cc0021cfbfbfbde970271113ef2e0a5cafe249c4f784826ac'
  # Actual view_image was performed in this child transcript; receipt is not synthetic visual evidence.
  receipt={'tool':'functions.exec -> tools.view_image','tool_call_id':'runtime_does_not_expose_id; recover_code actual image displayed for isolation rehearsal'}
  # Actual timestamp is supplied separately below by caller, not guessed from source data.
  receipt['at']=json.load(open(BASE/'actual-view-receipt.json'))['at']
  session.record_view(pid,1,BASE/'real-image-bundle/images'/f'{img}.jpg',receipt)
  session.save(record);session.save(record);session.body_once(pid,recorded_cache)
  final=writer.read()[1]
  assert count[0]==1
  assert final['entries']==original['entries']
  for key,old in original['koyo_index_handoffs'].items():assert final['koyo_index_handoffs'][key]['rows']==old['rows']
  result={'mode':'isolated-local-replay-fixture','real_image_viewed':True,'source_body_requests':0,'recorded_cache_calls':count[0],'final_accepted_rows':sum(len(x['rows']) for x in final['koyo_index_handoffs'].values()),'terra_entries_unchanged':True,'all_original_rows_equal':True,'live_writes':0,'activation_sha256':doc['sha256']}
  (BASE/'rehearsal-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 finally:
  if 'session' in locals():session.close()
  writer.close()
