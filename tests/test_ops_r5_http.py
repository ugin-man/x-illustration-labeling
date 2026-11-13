"""Regression for a temporary access response incorrectly ending all workers."""
from contextlib import redirect_stderr, redirect_stdout
import io
import subprocess
import unittest
from unittest.mock import patch
from ops_runtime_r5.queue import OpsQueue
from ops_runtime_r5.transport import failure_details, retry_delay, wait_for_retry
from pipeline_production.git_queue import QueueError


class HttpRecoveryTests(unittest.TestCase):
    def response(self, error=b'', code=1):
        return subprocess.CompletedProcess(['git'], code, b'fixed-output', error)

    def test_http_403_then_success_retries_same_read_without_changing_credentials(self):
        q=OpsQueue.__new__(OpsQueue);q.env={'EXISTING_CREDENTIAL_HELPER':'preserve'}
        with patch('pipeline_production.git_queue.GitQueue.git',side_effect=[self.response(b'HTTP/2 403'),self.response(code=0)]) as run, patch('ops_runtime_r5.queue.wait_for_retry') as wait:
            self.assertEqual(q.git('fetch','origin','fixed-ref').returncode,0)
            self.assertEqual(run.call_args_list[0],run.call_args_list[1])
            self.assertEqual(q.env,{'EXISTING_CREDENTIAL_HELPER':'preserve'})
            self.assertEqual(wait.call_args.args[0]['category'],'http_access_response')

    def test_429_honors_retry_after_and_reset(self):
        info=failure_details('HTTP/2 429\nretry-after: 120\nx-ratelimit-remaining: 0\nx-ratelimit-reset: 1500',now=1000)
        self.assertEqual(info['retry_after_seconds'],500)
        self.assertGreaterEqual(retry_delay(info,0),500)

    def test_http_date_retry_after(self):
        info=failure_details('HTTP/2 403\nRetry-After: Thu, 01 Jan 1970 00:02:00 GMT',now=0)
        self.assertEqual(info['retry_after_seconds'],120)

    def test_commit_digits_are_not_http_status(self):
        self.assertEqual(failure_details('unexpected reference abc403fff401502')['category'],'other')

    def test_connect_proxy_response_is_not_mistaken_for_permanent_auth_failure(self):
        info=failure_details('HTTP/1.1 200 Connection established\nCONNECT tunnel failed, response 403')
        self.assertEqual(info['category'],'http_access_response')
        self.assertEqual(info['http_status'],403)

    def test_trace_headers_and_tokens_never_escape_returned_push_response(self):
        q=OpsQueue.__new__(OpsQueue);q.env={}
        raw=b'HTTP/2 403\nAuthorization: secret-token\nLocation: https://private.invalid/\nretry-after: 120'
        with patch('pipeline_production.git_queue.GitQueue.git',return_value=self.response(raw)) as run:
            proc=q.git('push','origin',check=False)
        self.assertEqual(run.call_count,1)
        self.assertNotIn(b'secret',proc.stderr);self.assertNotIn(b'private.invalid',proc.stderr)
        self.assertEqual(proc.stdout,b'')
        self.assertEqual(failure_details(proc.stderr)['retry_after_seconds'],120)

    def test_persistent_403_has_finite_budget(self):
        q=OpsQueue.__new__(OpsQueue);q.env={}
        with patch('pipeline_production.git_queue.GitQueue.git',return_value=self.response(b'HTTP/2 403')) as run, patch('ops_runtime_r5.queue.wait_for_retry'):
            with self.assertRaisesRegex(QueueError,'http_status=403.*attempts=10'):q.git('ls-remote','origin')
            self.assertEqual(run.call_count,10)

    def test_explicit_bad_credentials_do_not_trigger_permission_changes(self):
        q=OpsQueue.__new__(OpsQueue);q.env={}
        with patch('pipeline_production.git_queue.GitQueue.git',return_value=self.response(b'authentication failed')) as run, patch('ops_runtime_r5.queue.wait_for_retry') as wait:
            with self.assertRaisesRegex(QueueError,'access'):q.git('fetch','origin')
            wait.assert_not_called();self.assertEqual(run.call_count,1)

    def test_retry_progress_never_corrupts_stdout_json(self):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err),patch('ops_runtime_r5.transport.time.sleep'),patch('ops_runtime_r5.transport.retry_delay',return_value=61):
            wait_for_retry(failure_details('HTTP/2 403'),0,'fetch')
        self.assertEqual(out.getvalue(),'')
        self.assertIn('git_retry_wait',err.getvalue())


if __name__=='__main__':unittest.main()
