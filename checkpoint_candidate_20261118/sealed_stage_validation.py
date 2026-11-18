"""Validate already committed sealed exploration rows; never issue/replay requests."""
import copy,sys
from pathlib import Path
HERE=Path('/tmp/koyo-current-batch-candidate/exploration')
# This module is loaded only by isolated controller after current-runtime imports.
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
from exploration import digest,elapsed,VERSION,Refused
from new_batch_guard import NewBatchClockGuard
from sealed_row import SealedRowWriter

def verify_seal(clock):
 if clock.get('version')!=VERSION or not clock.get('seal'):raise Refused('reviewed sealed exploration required')
 seal=clock['seal'];requests=clock['requests'];times=[];counts={'searches':0,'pages':0}
 for rid,r in requests.items():
  if 'finished_at' not in r or 'started_at' not in r or 'ack' not in r:raise Refused('unfinished/ambiguous exploration')
  if not r['reserved_at']<=r['ack']['payload']['at']<=r['started_at']<=r['finished_at']<=seal['at']:raise Refused('exploration timestamp order')
  if r['kind'] not in ('search','page') or not r['queries']:raise Refused('request shape')
  proof=r['ack']['payload']
  if proof.get('binding')!=clock['binding'] or proof.get('request_id')!=rid:raise Refused('ACK binding mismatch')
  if any(o['finished_at']>r['reserved_at'] for oid,o in requests.items() if oid!=rid and o['reserved_at']<r['reserved_at']):raise Refused('overlapping unfinished requests')
  for at in (r['reserved_at'],r['started_at']):
   prefix=copy.deepcopy(clock);prefix['seal']=None;prefix['last_event_at']=at
   prefix['requests']={i:v for i,v in requests.items() if v['reserved_at']<=at}
   prefix['management_reads']={i:v for i,v in clock['management_reads'].items() if v['payload']['ended_at']<=at}
   # At reserve the current request has no ACK yet; compute budget just before it.
   if at==r['reserved_at']:prefix['requests'].pop(rid)
   if elapsed(prefix,at)>=60:raise Refused('request began after research time budget')
  counts['searches' if r['kind']=='search' else 'pages']+=len(r['queries'])
  times.extend([r['reserved_at'],r['ack']['payload']['at'],r['started_at'],r['finished_at']])
 for receipt in clock['management_reads'].values():times.append(receipt['payload']['ended_at'])
 if counts!={k:clock[k] for k in counts} or counts['searches']>2 or counts['pages']>3:raise Refused('research count budget')
 unsealed=copy.deepcopy(clock);unsealed['seal']=None;unsealed['last_event_at']=max(times) if times else None
 expected={'at':seal['at'],'elapsed_seconds':elapsed(unsealed,seal['at']),'searches':counts['searches'],'pages':counts['pages'],'wall_seconds':0 if clock['started_at'] is None else seal['at']-clock['started_at'],'ledger_sha256':digest(unsealed)}
 if seal!=expected or clock['last_event_at']!=seal['at']:raise Refused('immutable seal/budget mismatch')
 return True

def validate(worker,before,after,pid,token,activation):
 # verify_seal checks only consistency, not authenticated origin. In particular,
 # forged ACK MACs or management-read receipts can be rehashed. The original
 # process-local authority/issued registry is not recoverable from Git state.
 # Neither same-token restart nor historical adoption may turn that into trust.
 raise Refused('sealed stage held: independently verifiable original authority unavailable')
