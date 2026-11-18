"""Dedicated single-index claim boundary. No automatic activation or publication."""
import json,copy
from pathlib import Path
from next_batch import validate_candidate
from network_runtime import IndexWriter
from recovery_adapter import Refused,sha
from runtime_components import digest
class ClaimWriter(IndexWriter):
    def __init__(self,*args,claim_candidate=None,inventory_bundle=None,**kwargs):
        super().__init__(*args,**kwargs);self.claim_candidate=claim_candidate;self.inventory_bundle=inventory_bundle
    def guard(self,before,after):
        c=self.claim_candidate
        if not c or after!=c['after']:raise Refused('claim differs from reviewed typed candidate')
        validate_candidate(c,before,c['expected_head'],self.clock())
        p=(self.activation_document or {}).get('payload',{})
        from claim_inventory import assemble
        bundle=self.inventory_bundle or {}
        if bundle.get('schema')=='never-assigned-protocol-v1':
            from protocol_claim_evidence import assemble_protocol
            inventory=assemble_protocol(before,c['expected_head'],after['koyo_index_handoffs'][c['new_key']]['job_id'],after['koyo_index_handoffs'][c['new_key']]['plan']['payload']['source']['post_ids'],bundle,self.clock())
        else:
            inventory=assemble(c['expected_head'],after['koyo_index_handoffs'][c['new_key']]['job_id'],after['koyo_index_handoffs'][c['new_key']]['plan']['payload']['source']['post_ids'],bundle.get('coverage',{}),bundle.get('observations',[]),bundle.get('refs',{}),self.clock())
        # Compare evidence commitment, not moving checked_at.
        supplied=after['koyo_index_handoffs'][c['new_key']]['plan']['payload']['eligibility']['inventory']
        if bundle.get('schema')=='never-assigned-protocol-v1':
            if {k:v for k,v in inventory.items() if k!='checked_at'}!={k:v for k,v in supplied.items() if k!='checked_at'}:raise Refused('protocol claim summary differs from original evidence')
        elif inventory.get('evidence_sha256')!=supplied.get('evidence_sha256'):raise Refused('claim inventory not collected evidence')
        required={str(Path(__file__).with_name(f).resolve()) for f in ('claim_writer.py','claim_inventory.py','next_batch.py','network_runtime.py','connector_protocol.py','connector_bridge.py','connector_transport.js','pack_compressed.py','rehearsal_pipeline.py','claim_cli.py','claim_transport.js')}
        if bundle.get('schema')=='never-assigned-protocol-v1':required.add(str(Path(__file__).with_name('protocol_claim_evidence.py').resolve()))
        if (self.activation_document or {}).get('sha256')!=sha(p) or p.get('mode')!='reviewed-live-claim' or not p.get('review_reference') or p.get('candidate_sha256')!=sha(c) or p.get('before_sha256')!=sha(before):raise Refused('dedicated exact claim activation required')
        if not required<=set(p.get('code_sha256',{})) or any(digest(f)!=v for f,v in p['code_sha256'].items()):raise Refused('claim/scheduler code not pinned')
        return after['koyo_index_handoffs'][self.key]
    def authorize_transition(self,before,after,operation,lease_token,fencing_receipt=None):
        if operation!='claim-retained' or lease_token!=self.claim_candidate['current_token']:raise Refused('claim operation/token mismatch')
        self.guard(before,after)
    def preservation(self,before,after):return self.guard(before,after)
    def publish(self,*args,**kwargs):raise Refused('claim uses connector expected-head CAS only; no CLI push')
