"""Explicit remote transport probe; writes a synthetic job only, no research labels."""
import hashlib
import json
import uuid
from .git_queue import GitQueue

if __name__ == '__main__':
    run = 'probe-' + uuid.uuid4().hex[:12]
    expected = hashlib.sha256(b'synthetic-queue-probe-v1').hexdigest()
    remote = 'https://github.com/ugin-man/x-illustration-labeling.git'
    with GitQueue(remote, run, expected) as q:
        lease = q.reserve('transport', 'probe-worker')
        q.checkpoint('transport', lease['token'], {'1': {'type': 'synthetic_transport_probe', 'post_id': '1'}})
        head = q.finish('transport', lease['token'], ['1'])
    # A fresh object store verifies the result is on the server, not merely local.
    with GitQueue(remote, run, expected) as q:
        remote_head, state = q.read('transport')
        assert remote_head == head and state['status'] == 'completed'
        assert json.loads(q.git('show', head + ':labels.jsonl').stdout)['type'] == 'synthetic_transport_probe'
    print(json.dumps({'remote_queue_roundtrip': 'passed', 'run_id': run, 'head': head}))
