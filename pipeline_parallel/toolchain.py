"""Pin the complete v4 runtime; the v3 checkout and hashes remain unchanged."""
from .common import digest

FILES = (
    'pipeline_parallel/worker.py', 'pipeline_parallel/git_queue.py', 'pipeline_parallel/bundles.py',
    'pipeline_parallel/context.py', 'pipeline_parallel/common.py', 'pipeline_parallel/launch_control.py',
    'pipeline_parallel/toolchain.py', 'pipeline_parallel/collect.py', 'pipeline_parallel/preflight.py',
    'pipeline_parallel/disposition.py', 'pipeline_parallel/isolation.py', 'AGENTS.md', 'docs/WORKER_PARALLEL.md',
    'pipeline_parallel/authoring.py', 'pipeline_parallel/contract_v4.py', 'pipeline_parallel/prepare_run.py',
    'pipeline_parallel/__init__.py',
)


def fingerprint(root):
    return {name: digest(root / name) for name in FILES}


def verify(config, root):
    if config.get('toolchain_sha256') != fingerprint(root):
        raise ValueError('Worker code/instructions changed or are not pinned; use the frozen checkout or prepare a new run')
