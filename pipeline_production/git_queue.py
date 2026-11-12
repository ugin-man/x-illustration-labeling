"""One branch per batch; non-fast-forward rejection is the reservation CAS.

No issue comments, shared spreadsheet, local coordinator, or force-push required.
Each CLI invocation uses its own disposable bare object store, not the checkout.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid

from .common import canonical


class Conflict(RuntimeError):
    pass


class LostLease(RuntimeError):
    pass


class QueueError(RuntimeError):
    pass


class ClaimBusy(RuntimeError):
    pass


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,90}", value):
        raise ValueError("Invalid run, job, or worker identifier")
    return value


class GitQueue:
    def __init__(self, remote, run_id, catalog_sha256, lease_seconds=3600, clock=time.time):
        self.remote = str(remote)
        self.run_id = safe_id(run_id)
        self.catalog_sha256 = catalog_sha256
        self.lease_seconds = lease_seconds
        self.clock = clock
        self.claim_gate = None
        self.tmp = tempfile.TemporaryDirectory(prefix="label-queue-")
        self.repo = Path(self.tmp.name)
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
                        GIT_AUTHOR_NAME="Illustration queue", GIT_AUTHOR_EMAIL="queue@localhost",
                        GIT_COMMITTER_NAME="Illustration queue", GIT_COMMITTER_EMAIL="queue@localhost")
        self.git("init", "--bare", "--quiet")
        self.git("remote", "add", "origin", self.remote)

    def close(self):
        self.tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.release_claim_gate()
        finally:
            self.close()

    def acquire_claim_gate(self, worker_id):
        """Serialize claim attempts for one identity; release on leaving the context."""
        jid = 'claim-gate-' + safe_id(worker_id)
        safe_id(jid)
        previous_seconds = self.lease_seconds
        try:
            self.lease_seconds = 60
            lease = self.reserve(jid,worker_id)
        except Conflict as exc:
            raise ClaimBusy('Concurrent claim for this worker identity') from exc
        finally:
            self.lease_seconds = previous_seconds
        if lease is None:
            raise ClaimBusy('Concurrent claim for this worker identity')
        self.claim_gate = (jid,lease['token'])
        return lease

    def release_claim_gate(self):
        if self.claim_gate:
            jid, token = self.claim_gate
            self.release(jid, token, 'claim_finished', retry_seconds=0)
            self.claim_gate = None

    def git(self, *args, data=None, check=True):
        proc = subprocess.run(["git", "-C", str(self.repo), *args], input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, timeout=120)
        if check and proc.returncode:
            # Never echo remote URLs, command strings, or credential-helper output.
            raise QueueError("Git operation failed: " + args[0] + " (check repository access/network)")
        return proc

    def ref(self, job_id):
        return f"refs/heads/codex/jobs/{self.run_id}/{safe_id(job_id)}"

    def heads(self):
        out = self.git("ls-remote", "--heads", "origin", f"refs/heads/codex/jobs/{self.run_id}/*").stdout.decode()
        return {line.split()[1].rsplit("/", 1)[1]: line.split()[0] for line in out.splitlines() if line}

    def read(self, job_id):
        ref = self.ref(job_id)
        found = self.git("ls-remote", "--heads", "origin", ref).stdout.decode().strip()
        if not found:
            return None, None
        # Each invocation uses a disposable store. Only the current commit/tree is
        # needed; fetching all accumulated index/checkpoint history would make
        # later claims progressively slower. The server already has the parent.
        self.git("fetch", "--quiet", "--no-tags", "--depth=1", "origin", ref)
        sha = self.git("rev-parse", "FETCH_HEAD").stdout.decode().strip()
        state = json.loads(self.git("show", f"{sha}:state.json").stdout)
        if (state["run_id"] != self.run_id or state["job_id"] != job_id
                or state["catalog_sha256"] != self.catalog_sha256):
            raise QueueError("Job belongs to a different catalog/run")
        return sha, state

    def files(self, sha):
        if not sha:
            return {}
        raw = self.git("ls-tree", "-r", "-z", sha).stdout
        result = {}
        for item in raw.split(b"\0"):
            if item:
                meta, name = item.split(b"\t", 1)
                mode, kind, oid = meta.decode().split()
                result[name.decode()] = (mode, kind, oid)
        return result

    def _commit(self, state, parent=None, additions=None):
        files = self.files(parent)
        additions = dict(additions or {})
        additions["state.json"] = canonical(state)
        for path, content in additions.items():
            # Flat root names only, simplifying tree creation and preventing traversal.
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", path):
                raise ValueError("Unsafe result file name")
            oid = self.git("hash-object", "-w", "--stdin", data=content).stdout.decode().strip()
            files[path] = ("100644", "blob", oid)
        tree_input = b"".join(f"{mode} {kind} {oid}\t{name}\0".encode()
                              for name, (mode, kind, oid) in sorted(files.items()))
        tree = self.git("mktree", "-z", data=tree_input).stdout.decode().strip()
        args = ["commit-tree", tree]
        if parent:
            args += ["-p", parent]
        args += ["-m", f"{state['job_id']} {state['status']} attempt {state['attempt']}"]
        return self.git(*args).stdout.decode().strip()

    def _publish(self, job_id, expected, candidate):
        # With a unique child of exactly expected, a normal Git push rejects
        # concurrent siblings. An initial claim is a unique root commit.
        proc = self.git("push", "--porcelain", "origin", f"{candidate}:{self.ref(job_id)}", check=False)
        if proc.returncode == 0:
            return candidate
        observed = self.heads().get(job_id)
        if observed == candidate:
            return candidate  # Server accepted, but acknowledgement was lost.
        if observed != expected:
            raise Conflict("Another worker updated this job; refresh and retry")
        raise QueueError("Push was not accepted; no reservation was acquired")

    def reserve(self, job_id, worker_id):
        safe_id(worker_id)
        parent, current = self.read(job_id)
        now = int(self.clock())
        if current and (current["status"] in ("completed", "needs_review")
                        or (current["status"] == "leased" and current["lease_until"] + 120 > now)):
            return None
        state = dict(current or {})
        state.update(run_id=self.run_id, job_id=job_id, catalog_sha256=self.catalog_sha256,
                     worker_id=worker_id, token=uuid.uuid4().hex,
                     attempt=(current["attempt"] + 1 if current else 1), status="leased",
                     acquired_at=now, updated_at=now, lease_until=now + self.lease_seconds,
                     completed_posts=list(current.get("completed_posts", [])) if current else [],
                     retry_after=0)
        if current and current.get("retry_after", 0) > now:
            return None
        sha = self._publish(job_id, parent, self._commit(state, parent))
        return dict(state, head=sha)

    def _owned(self, job_id, token):
        sha, state = self.read(job_id)
        if not state or state["status"] != "leased" or state["token"] != token:
            raise LostLease("Reservation is no longer owned by this worker")
        if state["lease_until"] <= self.clock():
            raise LostLease("Reservation expired; reacquire before further work")
        return sha, state

    def checkpoint(self, job_id, token, records, manifest=None, hold=None):
        parent, state = self._owned(job_id, token)
        additions = {}
        if manifest is not None:
            additions['manifest.json'] = canonical(manifest)
        existing = self.files(parent)
        if manifest is not None and 'manifest.json' in existing:
            if self.git('show',f'{parent}:manifest.json').stdout != canonical(manifest):
                raise Conflict('Pinned job manifest cannot be changed')
        done = set(state["completed_posts"])
        for post_id, record in records.items():
            if not re.fullmatch(r"[0-9]{1,25}", post_id):
                raise ValueError("Post IDs must be decimal strings")
            filename = f"post-{post_id}.json"
            content = canonical(record)
            if filename in existing:
                old = self.git("show", f"{parent}:{filename}").stdout
                if old != content:
                    raise Conflict("A saved post has different contents; use a separate review revision")
            additions[filename] = content
            done.add(post_id)
        now = int(self.clock())
        state.update(completed_posts=sorted(done), updated_at=now,
                     lease_until=now + self.lease_seconds)
        if hold is not None:
            if (set(hold) != {'post_id','reason'} or not re.fullmatch(r'[0-9]{1,25}',hold['post_id'])
                    or hold['reason'] not in {'input_requires_review','image_unavailable','schema_ambiguity'}):
                raise ValueError('Invalid non-descriptive hold reason')
            state.update(status='needs_review',lease_until=0,review=hold)
        return self._publish(job_id, parent, self._commit(state, parent, additions))

    def finish(self, job_id, token, expected_post_ids):
        parent, state = self._owned(job_id, token)
        if set(state["completed_posts"]) != set(expected_post_ids):
            raise QueueError("Cannot complete: expected post IDs and checkpointed results differ")
        names = self.files(parent)
        rows = []
        for pid in sorted(expected_post_ids):
            name = f"post-{pid}.json"
            if name not in names:
                raise QueueError("Cannot complete: a result file is missing")
            rows.append(json.loads(self.git("show", f"{parent}:{name}").stdout))
        payload = b"".join(canonical(row) for row in rows)
        state.update(status="completed", updated_at=int(self.clock()), lease_until=0,
                     result_sha256=hashlib.sha256(payload).hexdigest(), result_count=len(rows))
        return self._publish(job_id, parent, self._commit(state, parent, {"labels.jsonl": payload}))

    def release(self, job_id, token, reason, retry_seconds=600):
        parent, state = self._owned(job_id, token)
        state.update(status="available", updated_at=int(self.clock()), lease_until=0,
                     retry_after=int(self.clock()) + retry_seconds, last_error=str(reason)[:200])
        return self._publish(job_id, parent, self._commit(state, parent))

    def restore(self, job_id, destination):
        sha, state = self.read(job_id)
        if not state:
            return 0
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        for pid in state["completed_posts"]:
            path = destination / f"{pid}.json"
            content = self.git("show", f"{sha}:post-{pid}.json").stdout
            if path.exists() and path.read_bytes() != content:
                raise Conflict("Local result differs from remote checkpoint")
            path.write_bytes(content)
        return len(state["completed_posts"])
