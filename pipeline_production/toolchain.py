"""Pin the complete v4 runtime; the v3 checkout and hashes remain unchanged."""
from .common import digest

FILES = (
    'pipeline_production/worker.py', 'pipeline_production/git_queue.py', 'pipeline_production/bundles.py',
    'pipeline_production/context.py', 'pipeline_production/common.py', 'pipeline_production/launch_control.py',
    'pipeline_production/toolchain.py', 'pipeline_production/collect.py', 'pipeline_production/preflight.py',
    'pipeline_production/disposition.py', 'pipeline_production/isolation.py', 'AGENTS.md', 'docs/WORKER_PRODUCTION.md',
    'pipeline_production/authoring.py', 'pipeline_production/contract_v4.py', 'pipeline_production/prepare_run.py',
    'pipeline_production/__init__.py', 'pipeline_production/dispatch.py',
)


def fingerprint(root):
    return {name: digest(root / name) for name in FILES}


def verify(config, root):
    if config.get('toolchain_sha256') != fingerprint(root):
        raise ValueError('Worker code/instructions changed or are not pinned; use the frozen checkout or prepare a new run')
