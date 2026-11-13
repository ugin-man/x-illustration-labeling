# prod-0114 recovery audit

- Claimed with 33 previously accepted posts restored. Those results were not changed or reclassified.
- Recovery manifest from fixed commit `ff6e37132243137f8e4b6fb968cfc4ec1171216b` matched SHA-256 `5ee14243a62dc790763d5542a6357bb03cf8099a8fd51f20f5f66b9f69e436fb`. All six listed cache/budget files matched their manifest hashes and were inherited byte-for-byte with no conflicting local files.
- Five previously unaccepted posts were evaluated from the inherited caches and actual authorized images, without re-fetching text or adding searches or page visits. The prior recorded search budget was preserved as one search, zero pages, 14.116 seconds for post 2095575705207873708; its unverifiable external source time was not reconstructed. Recovery is noted in each result's review flags.
- Checkpoint `de550bc11e4af36e203b9d00c52bd1f140328ade` accepted 38 posts in total. Viewing metadata is in the accompanying view-events JSONL.

- Continued with ordinary processing after the five inherited-context posts. Checkpoint `2674b4413edc8f7e79658cf8238dcbf2b2822626` accepted 45 posts in total; viewing events remain in the companion metadata file.
