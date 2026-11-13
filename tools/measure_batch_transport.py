"""Count Git network-command invocations using synthetic local Git fixtures only."""
from collections import Counter
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_batch_runtime import BatchRuntimeTests
from ops_runtime_r5 import worker as old_worker
from ops_runtime_r5.queue import OpsQueue
from ops_batch import worker as batch_worker
from pipeline_production.common import atomic_write, canonical


def measure():
    case = BatchRuntimeTests(); case.setUp()
    output = {}
    original = OpsQueue.git
    counts = Counter()
    def tracked(self, *args, **kwargs):
        if args[0] in {'ls-remote', 'fetch', 'push'}:
            counts[args[0]] += 1
        return original(self, *args, **kwargs)
    def fake_fetch(pid, path):
        result = dict(post_id=pid, state='unavailable', text=None)
        atomic_write(path, canonical(result)); return result
    try:
        with patch.object(OpsQueue, 'git', tracked), patch('pipeline_production.context.fetch', fake_fetch):
            for label, module in [('r5', old_worker), ('batch', batch_worker)]:
                case.ops_worker = module
                jid, folder, manifest = case.claimed()
                metrics = {}
                def call(command, **args):
                    counts.clear()
                    result = case.call(command, job=jid, **args)
                    metrics[command + (':' + args['context_action'] if 'context_action' in args else '')] = dict(counts)
                    return result
                post_id = call('next')['post_id']
                call('context', post=post_id, context_action='fetch')
                call('context', post=post_id, context_action='summary')
                post = next(p for p in manifest['posts'] if p['post_id'] == post_id)
                atomic_write(folder / 'draft.json', canonical(case.answer(manifest, post)))
                call('save')
                call('checkpoint')
                output[label] = metrics
        return dict(method='Synthetic local bare Git. Counts are Git network-command invocations, not HTTP packets or cloud latency.', operations=output)
    finally:
        case.tearDown()


if __name__ == '__main__':
    print(json.dumps(measure(), ensure_ascii=False, indent=2))
