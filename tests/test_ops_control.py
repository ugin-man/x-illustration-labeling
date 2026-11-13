"""Rollout gates use synthetic metadata; no network or research images."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops_runtime import control


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / 'runs/test.json'
        self.config_path.parent.mkdir()
        self.config_path.write_bytes(b'{"synthetic":true}\n')
        self.workers = ['terra-prod-%02d' % n for n in range(1, 11)]
        self.config = dict(run_id='synthetic-production', worker_ids=self.workers,
                           manual_sha256='a' * 64, contract_sha256='b' * 64)
        paths = ['ops_runtime/' + name for name in
                 ('__init__.py', 'control.py', 'queue.py', 'worker.py')]
        paths.append(control.MANUAL_PATH)
        for name in paths:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('synthetic ' + name + '\n').encode())
        self.manifest = dict(operations_revision='ops-r2',
            base_commit=control.BASE_COMMIT, base_run_id=self.config['run_id'],
            base_config_sha256=control.sha256(self.config_path),
            classification_manual_sha256=self.config['manual_sha256'],
            files_sha256={p: control.sha256(self.root / p) for p in paths})
        self.activation = dict(state='enabled', operations_revision='ops-r2',
            base_run_id=self.config['run_id'], upgraded_worker_ids=self.workers,
            coordinator_ids=['ops-coordinator'])
        self.write_manifest()
        self.root_patch = patch.object(control.base, 'ROOT', self.root)
        self.root_patch.start()
        self.check_patch = patch.object(control.base, 'check_config',
                                      return_value=(self.config, {'jobs': []}))
        self.base_checker = self.check_patch.start()

    def tearDown(self):
        self.check_patch.stop()
        self.root_patch.stop()
        self.tmp.cleanup()

    def write_json(self, name, obj):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(obj, sort_keys=True) + '\n').encode())

    def write_manifest(self):
        self.write_json(control.MANIFEST_PATH, self.manifest)
        self.activation['manifest_sha256'] = control.sha256(self.root / control.MANIFEST_PATH)
        self.write_json(control.CONTROL_PATH, self.activation)

    def verify(self, worker='terra-prod-01', **kwargs):
        return control.verify_revision(self.root, self.config_path, worker, **kwargs)

    def test_blocked_allows_read_only_preflight_but_not_research(self):
        self.activation.update(state='blocked', upgraded_worker_ids=[])
        self.write_manifest()
        self.assertEqual(self.verify(require_enabled=False)['control']['state'], 'blocked')
        with self.assertRaisesRegex(ValueError, 'blocked'):
            self.verify()
        self.base_checker.assert_called_with(self.config_path)

    def test_enable_requires_every_unique_pinned_worker(self):
        for upgraded in (self.workers[:-1], self.workers + [self.workers[0]],
                         self.workers[:-1] + ['terra-prod-99']):
            with self.subTest(upgraded=upgraded):
                self.activation['upgraded_worker_ids'] = upgraded
                self.write_manifest()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_code_manual_manifest_binding_and_module_completeness(self):
        self.verify()
        for name in ('ops_runtime/queue.py', control.MANUAL_PATH):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.assertRaisesRegex(ValueError, 'differs'):
                    self.verify()
                path.write_bytes(original)
        (self.root / 'ops_runtime/unpinned.py').write_bytes(b'added')
        with self.assertRaisesRegex(ValueError, 'pin every'):
            self.verify()

    def test_control_cannot_authorize_another_manifest_or_coordinator(self):
        self.activation['manifest_sha256'] = '0' * 64
        self.write_json(control.CONTROL_PATH, self.activation)
        with self.assertRaisesRegex(ValueError, 'Activation control'):
            self.verify()
        self.write_manifest()
        self.verify('ops-coordinator', coordinator=True)
        with self.assertRaisesRegex(ValueError, 'coordinator identity'):
            self.verify(coordinator=True)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.verify('ops-coordinator')
        self.activation['coordinator_ids'].append('terra-prod-01')
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'coordinator identity'):
            self.verify()

    def test_base_configuration_and_checkout_must_remain_pinned(self):
        original = self.config_path.read_bytes()
        self.config_path.write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'configuration differs'):
            self.verify()
        self.config_path.write_bytes(original)
        with patch.object(control.base, 'ROOT', self.root / 'another-checkout'):
            with self.assertRaisesRegex(ValueError, 'same checkout'):
                self.verify()
        with self.assertRaisesRegex(ValueError, 'inside'):
            control.contained(self.root, '../outside')


if __name__ == '__main__':
    unittest.main()
