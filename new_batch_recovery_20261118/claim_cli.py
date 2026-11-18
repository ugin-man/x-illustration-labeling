"""Separate claim connector entrypoint. No body tool and no default activation."""
import json,sys
from pathlib import Path
from claim_writer import ClaimWriter
from connector_protocol import envelope,pack_envelope,validate_envelope,pre_update_ref,readback,execution_receipt,REMOTE
from recovery_adapter import Refused
BASE=Path(__file__).resolve().parent
def load(p):return json.loads(Path(p).read_text())
def main():
    folder=Path(sys.argv[2]).resolve()
    if not folder.is_relative_to(BASE/'connector-outbox'/'lease'):raise Refused('claim outbox scope')
    c=load(folder/'claim-candidate.json');before=load(folder/'before.json');doc=load(BASE/'claim-activation.json');bundle=load(folder/'inventory-bundle.json')
    w=ClaimWriter(REMOTE,before['catalog_sha256'],c['current_key'],'/tmp/x-recovery-isolated',activation_document=doc,claim_candidate=c,inventory_bundle=bundle)
    try:
        op=sys.argv[1]
        if op=='prepare':
            e=envelope(w,c['expected_head'],before,c['after'],'claim-retained',c['current_token'])
            (folder/'envelope.json').write_text(json.dumps(e));pack_envelope(e,folder/'pack');print(json.dumps({'prepared':True}))
        else:
            e=load(folder/'envelope.json')
            if op=='validate':
                validate_envelope(w,e,before);print(json.dumps({'valid':True,'sha256':e['sha256'],'pack':load(folder/'pack/manifest.json')}))
            elif op=='pre-ref':print(json.dumps(pre_update_ref(w,e,before,load(folder/'commit.json'))))
            elif op=='readback':
                r=execution_receipt(e,sys.argv[3],sys.argv[4]=='acknowledged',readback(w,e,sys.argv[3]))
                r['external_request_permitted']=False # Claim never grants body dispatch.
                (folder/'receipt.json').write_text(json.dumps(r));print(json.dumps(r))
            else:raise Refused('claim command unsupported')
    finally:w.close()
if __name__=='__main__':main()
