"""The editing helper binds observations to the selected post without network I/O."""
import hashlib
import unittest
from unittest.mock import patch

import test_batch_runtime as fixture
from pipeline_production.common import atomic_write, canonical
from pipeline_production.git_queue import Conflict
from tools import draft_edit


class DraftEditTests(unittest.TestCase):
    setUp = fixture.BatchRuntimeTests.setUp
    tearDown = fixture.BatchRuntimeTests.tearDown
    call = fixture.BatchRuntimeTests.call
    claimed = fixture.BatchRuntimeTests.claimed
    answer = fixture.BatchRuntimeTests.answer

    def prepared(self):
        job, folder, manifest = self.claimed()
        self.call('next', job=job)
        return job, folder, manifest

    def edit(self, job):
        return draft_edit.edit_current(job, self.config['worker_ids'][0], str(self.path))

    def test_authoring_preserves_identity_history_and_uses_unchanged_save(self):
        job, folder, manifest = self.prepared()
        original = (folder / 'draft.json').read_bytes()
        with patch.object(draft_edit, 'ROOT', self.root), \
             patch.object(fixture.BatchQueue, '__init__', side_effect=AssertionError('Git called')):
            with self.edit(job) as row:
                answer = self.answer(manifest, manifest['posts'][0])
                answer['execution']['started_at'] = row['execution']['started_at']
                answer['execution']['finished_at'] = None
                row.update(answer)
            saved = self.call('save', job=job)
        self.assertEqual(saved['saved_locally'], manifest['posts'][0]['post_id'])
        history = folder / '.batch' / 'draft-history' / (hashlib.sha256(original).hexdigest() + '.json')
        self.assertEqual(history.read_bytes(), original)

    def test_id_or_image_change_keeps_original_and_preserves_candidate(self):
        job, folder, manifest = self.prepared()
        original = (folder / 'draft.json').read_bytes()
        with patch.object(draft_edit, 'ROOT', self.root):
            for kind in ('id', 'image', 'provenance'):
                with self.subTest(kind=kind), self.assertRaises(Conflict):
                    with self.edit(job) as row:
                        if kind == 'id': row['post_id'] = manifest['posts'][1]['post_id']
                        elif kind == 'image': row['images'][0]['sha256'] = 'f' * 64
                        else: row['provenance']['job_id'] = 'wrong-job'
                self.assertEqual((folder / 'draft.json').read_bytes(), original)
        self.assertEqual(len(list((folder / '.batch' / 'edit-candidates').glob('*.json'))), 3)

    def test_exception_or_concurrent_change_never_overwrites_draft(self):
        job, folder, manifest = self.prepared()
        path = folder / 'draft.json'; original = path.read_bytes()
        with patch.object(draft_edit, 'ROOT', self.root):
            with self.assertRaises(RuntimeError):
                with self.edit(job) as row:
                    row['review_flags'].append('partial edit')
                    raise RuntimeError('interrupted authoring')
            self.assertEqual(path.read_bytes(), original)
            replacement = original + b' '
            with self.assertRaises(Conflict):
                with self.edit(job) as row:
                    row['review_flags'].append('stale edit')
                    atomic_write(path, replacement)
            self.assertEqual(path.read_bytes(), replacement)

    def test_deferred_or_saved_post_cannot_be_edited_as_current_draft(self):
        job, folder, manifest = self.prepared()
        pid = manifest['posts'][0]['post_id']
        self.call('defer', job=job, post=pid, reason='approval_required')
        with patch.object(draft_edit, 'ROOT', self.root), self.assertRaises(Conflict):
            with self.edit(job): self.fail('deferred post was exposed')
        current = self.call('next', job=job)
        post = next(p for p in manifest['posts'] if p['post_id'] == current['post_id'])
        atomic_write(folder / 'draft.json', canonical(self.answer(manifest, post)))
        self.call('save', job=job)
        with patch.object(draft_edit, 'ROOT', self.root), self.assertRaises(Conflict):
            with self.edit(job): self.fail('saved post was editable')


if __name__ == '__main__':
    unittest.main()
