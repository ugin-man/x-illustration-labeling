# Cycle-aware workspace audit candidate

Scope: replaces only blanket audit-root symlink rejection in new_batch_images.py. Source isolation/disposition files, policy hashes, actual bundle/image path symlink rejection, refusal journals, remote double-read, and actual-view receipts are unchanged. Same full audit root union is required; no path exclusions added.

Directories reached through internal links are traversed by inode identity; files are checked by inode plus image/archive type to prevent alias-extension gaps. Each symlink hop is restricted to the declared root union, including relative parent components processed AFTER actual preceding symlink resolution. Unresolvable link chains, broken/outside/denied targets, read failures, and metadata changes fail closed. Directory listing/file reads/path stat/readlink are FD-relative with O_NOFOLLOW ancestor traversal. Images and ZIP entries remain opaque byte hashes; no pixels viewed.

Tests: test_cycle_audit + test_new_batch_images: 33 passed. Independent review caught pathname directory traversal race and pre-link normpath semantics; both corrected. Final independent outcome is reported separately.

Actual /tmp and /workspace read-only attempt: stopped after26.6 seconds at PermissionError for /tmp/codex-daemon-1000 (mode000). No exclusion or permission change was made, no images viewed. This candidate does NOT claim a successful complete audit of the real environment. Original rglob-based audit can suppress directory traversal errors; this implementation refuses unknown coverage. Broad directory/file change checks can additionally reject concurrent workspace changes. No guarantee against hostile mutation after a completed audit is claimed.

This source-only correction is not live activation. Deployment requires independently reviewed installed code hash and reissuing the still-pristine classification activation against its exact unchanged claim baseline. Do not change roots, replace a refusal store, clear authority, or invent a successful audit.

Final independent re-review: 33 tests passed independently; prior symlink/../raw.bin false-negative fixture now rejects the excluded hash. FD-relative parent/final checks and component-order parent resolution verified; no remaining code Blocking found in inspected scope. Actual unreadable-root failure remains unresolved coverage, not code-test success.
