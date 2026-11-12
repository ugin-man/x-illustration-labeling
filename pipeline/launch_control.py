"""An explicit human screening receipt and separate launch instruction are required."""
from pathlib import Path
import sqlite3
from .common import read_json


def require_launch(config, catalog, root):
    path = Path(root) / 'data/launch-control.json'
    if not path.exists():
        raise ValueError('Launch control is missing; do not reserve or inspect research jobs.')
    control = read_json(path)
    if control.get('state') != 'authorized':
        raise ValueError('本番・追加分類は停止中です。人間の事前確認完了と、別の開始指示が必要です。')
    if config.get('schema_version') != 'v3-1' or control.get('authorized_run_id') != config.get('run_id'):
        raise ValueError('This run/schema was not authorized')
    if not catalog.get('screening') or catalog['screening'].get('state') != 'complete':
        raise ValueError('This dataset has not completed human screening')
    if control.get('catalog_sha256') != config['catalog_sha256'] or control.get('screening_receipt_sha256') != catalog['screening'].get('receipt_sha256'):
        raise ValueError('Screening or input catalog differs from launch authorization')
    if not isinstance(control.get('authorization_note'),str) or not control['authorization_note'].strip():
        raise ValueError('Separate user launch instruction must be recorded')
    verify_local_screening(catalog, root)


def verify_local_screening(catalog, root):
    path = Path(root) / 'private/screening/data-v1.sqlite3'
    if path.exists():
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            meta = dict(db.execute('SELECT key,value FROM meta').fetchall())
        finally:
            db.close()
        screening = catalog.get('screening', {})
        if not meta.get('completed_at') or int(meta['revision']) != screening.get('review_revision') or meta['catalog_sha256'] != screening.get('source_catalog_sha256'):
            raise ValueError('Human decisions have changed; rebuild and authorize a new screened run')


def require_no_source_data(catalog):
    if catalog.get('dataset_version') == 'data-v1' or catalog.get('screening',{}).get('state') != 'complete':
        raise ValueError('Use newly built, screened input bundles; never reuse unfiltered data-v1 for v3')
