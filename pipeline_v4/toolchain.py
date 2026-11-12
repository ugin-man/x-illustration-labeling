"""Pin the complete v4 runtime; the v3 checkout and hashes remain unchanged."""
from .common import digest

FILES = (
    'pipeline_v4/worker.py', 'pipeline_v4/git_queue.py', 'pipeline_v4/bundles.py',
    'pipeline_v4/context.py', 'pipeline_v4/common.py', 'pipeline_v4/launch_control.py',
    'pipeline_v4/toolchain.py', 'pipeline_v4/collect.py', 'pipeline_v4/preflight.py',
    'pipeline_v4/disposition.py', 'pipeline_v4/isolation.py', 'AGENTS.md', 'docs/WORKER_V4.md',
    'pipeline_v4/authoring.py', 'pipeline_v4/contract_v4.py', 'pipeline_v4/prepare_run.py',
    'pipeline_v4/__init__.py',
)


def fingerprint(root):
    return {name: digest(root / name) for name in FILES}


def verify(config, root):
    if config.get('toolchain_sha256') != fingerprint(root):
        raise ValueError('Worker code/instructions changed or are not pinned; use the frozen checkout or prepare a new run')
