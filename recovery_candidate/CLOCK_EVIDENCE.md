# Clock evidence and unresolved boundary

Pinned formal manual R13: one body request, up to two additional query terms and three additional pages, new exploration starts within 60 seconds. Two terms in one call consume two terms. End early when evidence suffices.
Pinned ops-r5 code stores started_at/deadline=start+60. It does not describe later wait subtraction.

The live snapshot stores later koyo-exploration-clock-v2 seals. For ALL FOUR v2 seals, recorded elapsed exactly equals seal.ended_at minus last search ACK.ack_at minus the sum of seal.management_proof intervals:
- 2097074133989511436: 5.505273103713989 sec
- 2097410359602860524: 5.591034173965454 sec
- 2095184106560848004: 4.348953008651733 sec
- 2095602234746953859: 12.402679920196533 sec
All differences: 0.0. Later wait separation therefore really was applied, rather than merely proposed. The parent also reports a 12:33 UTC update under user direction.

However, every available v2 example has only one accepted search. These examples do NOT establish the multiple-request accumulation rule, whether all tool latency or only saving latency should be excluded, or all restart/renewal edge cases. Missing v7/v8 source/document hashes do not supply their text.

Implementation exposes wall and active-v2-review as explicit isolated test modes. Neither is silently selected for production; wall-only would risk undoing the accepted later change, while inferred active-time rules risk changing research behavior. Old sealed records remain byte-for-byte semantically unchanged. Legacy unsealed clocks cannot be reset or migrated automatically.

Until the later approved specification or equivalent code is recovered, keep new external-search start scheduling disabled on ambiguous cases, and do not mislabel this as exact v8 compatibility. Posts with no leads require no external exploration and preserve zero searches/pages/elapsed as before; ordinary body-once and image-based classifications do not require inferring this clock rule.
