# Architecture and versioning

Configuration selects `Gold_Annotation` as the source-data worksheet and `Core_Schema` as the sole codebook worksheet.
Ingestion retains every source row in workbook order while exposing context and substantive views. Legacy annotation
columns in the source workbook are neither UI state nor export metadata.

For focal utterance order `t`, display context is strictly the same dispute's rows with lower `utterance_order`, during
initial coding and revision. Context rows are never annotated. Applicability depends only on the focal answers:

- five binary parent/control fields always apply;
- four KS children apply when `KS_present=1`;
- two KI children apply when `KI_present=1`;
- confidence, review flag, and one optional comment apply to every utterance.

The model clears hidden children to null and removes them from `answered_fields`. KS and KI are independent.
`KS_restaking` is a direct coder judgment based on visible prior discussion. `KI_compromise_position` is binary.

Only when all substantive utterances in a dispute are submitted may the UI store the final dispute payload. That
payload and its `answered_fields` contain only `C_primary_dispute_object`; the allowed values and explanations are
parsed from bullets in its authoritative coding rule.

SQLite current tables are coder-isolated projections; event tables are append-only. No schema migration is needed for
the simplified fields because payloads are JSON. Each write retains schema identity, UTC timestamps, elapsed wall time,
revision number, coder, and application version. Older payloads remain intact.

The complete codebook file hash is the canonical schema identity. Progress and exports select the active hash. Excel
exports have deterministic columns, include only submitted substantive rows, propagate the final dispute object, map
SQL/JSON null to blank cells, and exclude obsolete and legacy gold annotation fields.
