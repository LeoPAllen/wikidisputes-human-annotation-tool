# Unified annotation build specification

## Authoritative inputs

The application reads only `Gold_Annotation` from `data/source/gold_input.xlsx` for human coding and reads `Core_Schema_SIMPLIFIED` plus controlled-value sheets from `data/source/codebook.xlsx`. Both workbooks are immutable. Source order and all 438 rows are retained losslessly.

`utterance_role` is exactly `context` or `utterance`. Each dispute begins with one display-only context heading. Only substantive utterances enter the queue, progress, review, applicability state, evidence choices, readiness calculations, SQLite annotation state, and utterance-level provenance.

## Context and interface

For focal order `t`, display only same-dispute rows with lower order. A later-order reply target is a valid reconstruction warning, but its text must remain hidden. Only earlier substantive turns can affect KS/KI applicability or serve as upstream evidence.

Show coder ID and schema version, 404 substantive utterances, and 34 disputes. After every substantive turn in a dispute is submitted, open the separate primary-dispute-object screen with a fresh timer and UTC opened-at timestamp. Preserve drafts, revisions, append-only history, explicit null answers, ordinal 1–5 controls, conditional justification, and coder isolation.

Never render escalation, outcomes, resolution URLs, administrative sampling fields, `Dispute_Rationales`, or `Validation_Audit`. This is UI blinding, not filesystem access control; hard blinding requires a separately sanitized distribution.

## Persistence, export, and versioning

Current SQLite keys are `(coder_id, utterance_id)` and `(coder_id, dispute_id)`; event tables contain no dataset grouping field. Legacy databases are backed up and migrated transactionally after collision checks, with payloads and all audit metadata preserved.

Export one `Gold_Annotations` sheet with all rows in order, blank context labels, submitted substantive annotations, and selected-coder provenance. Include coder-specific dispute state, utterance events, dispute events, schema versions, and QC.

Codebook evolution uses `schema_version` plus whole-file SHA-256 independently of the dataset. A changed hash under the same version must stop startup and instruct the researcher to increment the version. `schema_locked` is an optional administrative freeze.

## Completion checks

Run validation, pytest, Ruff lint and format checks, and Streamlit AppTest. Confirm both source hashes are unchanged and audit the diff for future leakage, context annotation state, administrative exposure, progress denominators, migration safety, and export fidelity.
