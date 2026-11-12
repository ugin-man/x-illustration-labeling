"""Pin executable worker code and instructions along with each new v3 run."""
from .common import digest

FILES = (
    'pipeline/worker.py', 'pipeline/git_queue.py', 'pipeline/bundles.py',
    'pipeline/context.py', 'pipeline/common.py', 'pipeline/launch_control.py',
    'pipeline/toolchain.py', 'pipeline/collect.py', 'pipeline/preflight.py',
    'pipeline/disposition.py', 'pipeline/isolation.py', 'AGENTS.md', 'docs/WORKER.md',
)


def fingerprint(root):
    return {name: digest(root / name) for name in FILES}


def verify(config, root):
    if config.get('toolchain_sha256') != fingerprint(root):
        raise ValueError('Worker code/instructions changed or are not pinned; use the frozen checkout or prepare a new run')
