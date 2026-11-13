"""Bounded transport recovery without network, credentials or image input."""
from contextlib import redirect_stderr
import io
import subprocess
import unittest
from unittest.mock import Mock, patch

from ops_runtime_r3.queue import OpsQueue, git_failure_category
from pipeline_production.git_queue import QueueError


class TransportTests(unittest.TestCase):
    def queue(self):
        return OpsQueue.__new__(OpsQueue)

    def result(self, error=b'', code=1):
        return subprocess.CompletedProcess(['git'], code, stdout=b'fixed-output', stderr=error)

    def test_transient_read_retries_bounded_and_recovers(self):
        with patch('pipeline_production.git_queue.GitQueue.git', side_effect=[
                self.result(b'Could not resolve host: private.invalid'),
                self.result(b'connection reset'), self.result(code=0)]) as run, \
                patch('ops_runtime_r3.queue.time.sleep'):
            self.assertEqual(self.queue().git('fetch', 'origin').returncode, 0)
            self.assertEqual(run.call_count, 3)

    def test_reads_stop_after_three_transient_failures(self):
        with patch('pipeline_production.git_queue.GitQueue.git', return_value=
                self.result(b'Failed to connect to secret.invalid')) as run, \
                patch('ops_runtime_r3.queue.time.sleep'):
            with self.assertRaisesRegex(QueueError, 'transient_network.*attempts=3') as caught:
                self.queue().git('ls-remote', 'origin')
            self.assertNotIn('secret', str(caught.exception))
            self.assertEqual(run.call_count, 3)

    def test_auth_rate_limit_and_unknown_failures_are_not_retried(self):
        for error, category in ((b'HTTP 403 permission denied', 'access'),
                                (b'HTTP 429 rate limit', 'rate_limit'),
                                (b'Unknown secret token xyz', 'other')):
            with self.subTest(category=category), patch(
                    'pipeline_production.git_queue.GitQueue.git', return_value=self.result(error)) as run:
                with self.assertRaisesRegex(QueueError, category) as caught:
                    self.queue().git('fetch', 'origin')
                self.assertNotIn('xyz', str(caught.exception))
                self.assertEqual(run.call_count, 1)

    def test_push_is_never_blindly_retried(self):
        failed = self.result(b'connection reset')
        with patch('pipeline_production.git_queue.GitQueue.git', return_value=failed) as run:
            self.assertIs(self.queue().git('push', '--atomic', check=False), failed)
            self.assertEqual(run.call_count, 1)

    def test_timeout_read_is_bounded_and_does_not_leak_command(self):
        with patch('pipeline_production.git_queue.GitQueue.git', side_effect=
                subprocess.TimeoutExpired(['git', 'secret-url'], 120)) as run, \
                patch('ops_runtime_r3.queue.time.sleep'):
            with self.assertRaisesRegex(QueueError, 'attempts=3') as caught:
                self.queue().git('fetch', 'origin')
            self.assertNotIn('secret', str(caught.exception))
            self.assertEqual(run.call_count, 3)

    def test_cleanup_failure_preserves_success_and_original_error(self):
        q = self.queue()
        q.release_claim_gate = Mock(side_effect=QueueError('synthetic release failure'))
        q.close = Mock()
        with redirect_stderr(io.StringIO()) as output:
            with q:
                pass
        self.assertIn('claim_gate_cleanup_pending', output.getvalue())
        q.close.assert_called_once()
        with redirect_stderr(io.StringIO()), self.assertRaisesRegex(ValueError, 'original'):
            with q:
                raise ValueError('original')


if __name__ == '__main__':
    unittest.main()
