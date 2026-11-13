# prod-0188 metadata audit

- Worker: terra-prod-05; 50 posts saved and checkpointed; finish completed.
- Final checkpoint: 8d1cf4eaedbe4d5d5400b3d18720105e9ee1b0ac; finish: cf4cbf06f043791342e9a47afa6996b84df4ac22.
- View records are in view-events.jsonl. Multi-image batches were recorded after viewing, with individual viewing times unknown. The first attempted rendering of post 2096246825808499025 was truncated by the output context; the same authorized image was successfully viewed subsequently. This was not a policy refusal.
- The bounded text search for post 2096253148742758892 displayed a result mentioning popularity ranking; it was not used as evidence and no ranking values are recorded. The label carries a review flag.
- Individual source HTTP errors and timeout were recorded as technical failures without repeat fetch.
