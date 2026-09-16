# Architecture and versioning

Configuration selects `Gold_Annotation` as the source-data worksheet and `Core_Schema` as the sole codebook worksheet.
Ingestion retains every source row in workbook order while exposing context and substantive views. Legacy annotation
columns in the source workbook are neither UI state nor export metadata.

For focal display position `t`, display context is strictly the same dispute's rows with lower canonical display order,
during initial coding and revision. New Gold uses `substantive_order` (and permits nullable legacy order); older Gold
falls back to its complete `utterance_order` sequence as a whole dispute/file, never by mixing columns row by row.
Context rows are display-only and never annotated; a dispute may also have no context row. Applicability depends only
on the focal answers:

- five binary parent/control fields always apply;
- four KS children apply when `KS_present=1`;
- confidence, review flag, and one optional comment apply to every utterance.

The model clears hidden children to null and removes them from `answered_fields`. KS and KI are independent.
`KS_restaking` is a direct coder judgment based on visible prior discussion. `KI_present` has no child fields.

Only when all substantive utterances in a dispute are submitted may the UI store the final dispute payload. That
payload and its `answered_fields` contain only `C_primary_dispute_object`; allowed values come from its authoritative
Indicator enum, with matching explanations parsed from coding-rule bullets when available.

SQLite current tables are coder-isolated projections; event tables are append-only. No schema migration is needed for
the simplified fields because payloads are JSON. Each write retains schema identity, UTC timestamps, elapsed wall time,
revision number, coder, and application version. Older payloads remain intact. A direct Gold cutover compares old and
new visible-context signatures, removes stale projections for rows promoted from context, marks affected utterances for
re-review, and invalidates only affected dispute projections. The cutover takes a WAL-safe backup immediately before
mutation and is idempotent; source-comparison counts are reported separately from projection mutations.

The complete codebook file hash remains audit metadata, but completion and export compatibility depend on current
payload structure rather than exact hash equality. Excel exports have deterministic columns, include only structurally
compatible submitted substantive rows, propagate only a current-valid final dispute object, map SQL/JSON null to blank
cells, and exclude obsolete and legacy gold annotation fields.
