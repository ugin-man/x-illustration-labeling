# Final forest audit review (2026-11-18)

Implemented in new_batch_images.py and exact binding-key acceptance in new_batch_scope.py. No live runtime, remote classification state, body request, image view, or exploration authority was changed.

## Final design
The byte audit uses the fixed, unchanged pipeline_production.isolation.audit_workspace for directory roots. Exact regular-file roots use the same image-hash/ZIP-entry-hash algorithm without widening coverage to their parent. Bundle/refusal stores remain plain directories; actual research image paths still reject symlinks and must match pinned hashes.

A strict metadata prewalk checks directory readability and symlinks before any byte audit. Link resolution handles each component, including parent components after resolving preceding links; each hop stays inside the explicit forest, outside denied paths. Broken/outside/unresolvable links fail closed. Directory aliases are not recursively followed; their real targets receive additional original audits, including targets under a normally skipped .git parent. File aliases are additionally audited according to intermediate extension aliases. Link/target metadata is rechecked before return. Counts may include repeated alias audit; they are not unique asset counts.

The earlier all-file FD/mtime snapshot implementation was not adopted: it imposed unnecessary global quiescence and was too slow. Its read-only process was stopped with confirmed exit130. This final design retains the fixed original byte audit rather than claiming stronger concurrent-writer guarantees than that original procedure.

## Enforced dynamic coverage
Fixed audit_roots accept plain directory or exact regular file. Optional coverage_boundaries pins directory and excluded_names only. Exclusions are restricted to administrative names .agents/.aws/.codex/.git and require a reviewed scope reason. Every gate includes ALL current nonexcluded plain direct children in its effective forest; symlink/special direct children refuse rather than disappearing from coverage. New plain children are included next gate, not compared forever with an obsolete initial listing.
Within each gate, boundary names/types/inode must match before/after audit, before returning actual image paths, and after the final remote reread. Existing full-state/head/lease reread remains. Added/removed/retyped children during one gate refuse; platform child metadata churn alone does not cause permanent failure.

## Review and tests
88 tests passed independently in0.465s (some inherited gate tests repeat). Cases include outside/denied/broken links, unresolved cycles, benign directory cycles, hidden excluded loose/ZIP bytes, alias extensions/hardlinks, symlink-parent '..' correctness, .git directory-alias coverage, exact-file sibling noncoverage, unreadable dirs, special files, dynamic-boundary new excluded input, and additions during byte audit/path validation/remote reread. The source implementation and changes were independently reviewed after implementation by a separate worker.

## Real opaque audit
Actual reviewed forest:37 fixed research roots/files plus one dynamic cwd boundary with219 current plain direct children, total256 effective roots. Actual audit completed in4.937s,2541 loose-image hash checks,195 archive-image entry hash checks, excluded_images_found=0. No pixels displayed or viewing receipts created. Local exact configuration and full result are operational evidence, not embedded in the source backup.

/tmp/codex-daemon-1000 is platform runtime with mode000 and is explicitly NOT examined or claimed empty. Parent confirmed no research saving/fetching there. Shared and cwd administrative mounts are likewise outside research image-storage scope based on parent storage-history confirmation and independent static save-path review. Other unknown candidate research roots (/tmp/.git, label-queue-* and tmp1raixh9_) were conservatively included. The top-level count-audit-prod-0001.zip is included directly, not moved or hidden. /tmp/x-state-recovery.json is metadata-only, not an image/archive.

Static review found no omitted research image cache destination. New research output/cache destinations outside the current fixed roots/dynamic boundary require a reviewed inventory/activation update; future recovery-full-rehearsal-* directories are one known example. Inaccessible coverage is never converted into an empty/successful audit.

Fixed isolation.py SHA256 remains7d5cc909eb39cf97929ff5c96e78023a990b6e91d6cc3981ed6b84b2709de770. Disposition SHA256 remainsccac0d0e9315a2f7be84b79ba4a29948d61ae318483c4da8b59fdcaa614fc967.
