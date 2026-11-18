# Claim evidence analysis (read-only code reasoning, not a zero-work attestation)

## Can never-assigned history substitute for unknown Terra stores?
Conditionally, yes. The frozen source supports a stronger invariant than broad filename scanning:
- pipeline_production/dispatch.py _publish builds a dispatch-index ownership entry and _publish_atomic publishes index + job refs in ONE git push --atomic. No split fallback. Successful reservation therefore leaves durable index ancestry evidence even if ACK is lost.
- pipeline_production/git_queue.py reserve returns only after _publish. ops_runtime_r5/worker.py claim writes `.runtime/<run>/<job>/lease.json` and prepares/reconciles the job only after queue.claim returns. Non-claim actions require lease.json and current lease_snapshot before next/save/context.
- Therefore, for work performed by those verified implementations, an index entry pristine in EVERY ancestor since the run's true initialization means no legitimate reservation succeeded. An unassigned job cannot have legitimate unpublished draft/results/context created through that protocol.

This is a conditional proof, not a claim that all possible files anywhere are absent. It does not follow merely from today's pending state, an expired lease, absence of one local directory, or absence of a current job ref.

Required evidence before relying on the invariant:
1. Exact same run/catalog/manifest/post IDs and validated exclusion of earlier pilot posts. All production code revisions actually used must enforce reservation-before-preparation and atomic index/job writes, or their assignments must be separately included.
2. Complete canonical dispatch-index ancestry back to actual initialization, no shallow/gaps; verify initialized all entries and no missing targets. Preserve commit + state digests for every ancestor. Current collect_local_history inspects all reachable ancestors and is useful, but git --is-shallow-repository=false cannot itself prove absence of earlier force-reset/orphan history.
3. No known branch deletion/reinitialization/force-reset/manual out-of-band assignments omitted from that lineage. Use saved management ledgers, launch/ops records, pinned revision documents and existing work reports. Treat contradictions as unknown, not no-work.
4. Cross-check every known Koyo handoff, Terra job branch, dispatch assignment, archived ownership/lease ledger and identified unpublished store. If ANY proves prior work for the target, choose another job rather than reclaim it.
5. Fresh remote job-ref absence and exact current index head immediately before claim; expected-head CAS rejects concurrent normal Terra claim. Do not let a stalled old writer resume a retained key.

If these conditions are verified, selecting a fixed50 NEVER assigned in the complete ownership history is a reasonable way to protect Terra even when some of Terra's old storage locations cannot presently be found. Its unknown stores can contain work for previously reserved jobs, but cannot contain legitimate work for a never-reserved job under the proven protocol. Label that conclusion 'protocol-derived no-prior-assignment evidence', not 'all Terra disks scanned'.

## Practical semantic store inventory
Discover actual checkout/environment paths from existing management records and connected environment inventory, not by inventing directory names. Source code establishes relative layout:
- `<checkout>/.runtime/production-v4-001/<job>/lease.json`
- `draft.json`, `results/<post>.json`, `context/<post>.json`, `context/<post>-budget.json`
- `.ops-r5/unsent-drafts/`, `.ops-r5/history/`, `.ops-r5/reconciliation/` and checkpoint receipts
- Koyo: `post-runtime/<post>/`, connector-outbox receipts/envelopes, body-stage, visual staging, source/recovery snapshots (metadata, not necessarily unshared work)
Inspect a store's schema/owner/job/lease/post and compare result/context digest to remote accepted records. A catalog, manifest, static source, pack, ZIP or state snapshot mentioning all post IDs is shared metadata; it is not a per-post draft. Preserve identified artifacts, never delete or hide them to get an empty scan.

The existing claim_inventory.collect_environment string-search collector marks target IDs in ANY file as work and treats symlinks/unknown roots conservatively. It cannot be fed /tmp or a full checkout containing catalogs and honestly return empty. Do NOT hand-author empty observations. Either establish exhaustive actual work-store roots with documented shared-metadata classification, or independently review an explicit alternate evidence schema representing the protocol-derived proof above. The current ClaimWriter still requires collected inventory; this analysis does not waive that gate or change code.

Reasonable stopping condition: if full-history/protocol coverage is proven, there is no need to search every unrelated personal folder merely for target-number coincidences. If history/protocol coverage is not proven and a relevant worker store is missing, mark that evidence unknown and do not assert no unpublished work. Prefer a demonstrably never-touched candidate with stronger provenance.
