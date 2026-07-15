# Architecture and versioning

`config` selects the single `Gold_Annotation` worksheet and resolves local paths. Validation reads that sheet and the authoritative `Core_Schema_SIMPLIFIED` codebook before annotation can start. Ingestion retains every source row in its original order while exposing separate views for all rows, context headings, and substantive annotatable turns.

For focal order `t`, the UI may display only same-dispute rows with `utterance_order < t`. Only earlier substantive turns contribute to applicability or selectable evidence IDs. Context headings remain display-only and never enter progress, readiness, storage, review, or utterance annotation exports.

SQLite stores coder-isolated current projections and append-only events. Current keys are `(coder_id, utterance_id)` and `(coder_id, dispute_id)`. A one-time transactional migration backs up older databases, checks unified-key collisions, and rebuilds the four annotation tables without the obsolete column. Collision detection aborts before any database change.

The utterance screen derives its two-stage state from the existing current projection. Completing the four gateway fields saves a normal draft and advances to applicable details without resetting `opened_at`. A draft or submitted record with all four gateways answered opens directly in the detail stage. Returning to the gateway stage does not mutate child answers; applying a parent change normalizes newly inapplicable children to null through the same model used at submission. No workflow table or storage schema is involved.

Applicability is model-owned. In particular, `KI_explicit_feedback` applies only when KI is present and an earlier candidate exists. Its explicitly answered “No explicit feedback” state is represented by a null payload plus membership in `answered_fields`; when the field is inapplicable, both its payload and answered-state membership are removed.

Codebook evolution is independent of the dataset. Every event records `schema_version` and the entire codebook file's SHA-256. Reusing a version with a changed hash is rejected and requires a version increment. `schema_locked` is an optional administrative freeze, not a prerequisite for annotation.
