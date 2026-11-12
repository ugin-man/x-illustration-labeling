"""Local human-only archive location. Never copied into a worker run."""
from pathlib import Path
from .common import read_json


def bundle_root(root):
    root = Path(root).resolve()
    config = root / 'private/human-source.json'
    if not config.exists():
        return root / 'dist/data-v1'
    settings = read_json(config)
    path = Path(settings['bundle_root'])
    if settings.get('version') != 1 or not path.is_absolute():
        raise ValueError('Invalid human archive location')
    path = path.resolve()
    if path.is_relative_to(root) or not path.is_dir():
        raise ValueError('Human archive must exist outside the AI workspace')
    return path
