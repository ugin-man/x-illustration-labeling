# Audit note: prod-0096

Post 2095438109416858082 was saved locally but not checkpointed. Its external source `accessed_at` value was estimated rather than captured at the time of the search. Do not treat the timestamp as an actual observed access time or submit this local result unchanged. The fixed CLI rejects replacement of an existing local answer; no result or lease files were manually modified. The preceding nine results were checkpointed at queue head b0502ddf051236727aae366e97ae403fb32a6c50.

View event timestamps in view-events.jsonl were captured immediately after display, not from the image tool itself; they represent the subsequent clock reading rather than an exact image-tool timestamp.
