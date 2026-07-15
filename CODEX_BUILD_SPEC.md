# WikiDisputes Human Annotation UI — Codex Build Specification

## Goal

Build a complete, tested, visually clean, local Python application for two human annotators to code the WikiDisputes gold sample independently. Each annotator will run a private local copy of the repository and its own SQLite database. The interface must reduce information overload while preserving every piece of context that the coding rules legitimately require.

This is an implementation task, not a planning exercise. Work autonomously from repository inspection through implementation, validation, UI inspection, documentation, and final review. Do not stop after scaffolding or a plan. Ask the user only if a genuinely blocking ambiguity remains after inspecting the repository and the two source workbooks.

## Source files and authority

Expect these files:

- `data/source/gold_input.xlsx`: the current human-annotation sample.
- `data/source/codebook.xlsx`: the current KS/KI annotation codebook.

Never modify either source workbook.

The authoritative schema is the `Core_Schema_SIMPLIFIED` sheet in `data/source/codebook.xlsx`, supplemented by `Evidence_Types` and `Primary_Dispute_Objects`. Do not use the gold workbook's embedded codebook sheet as the rule source; it may contain an older schema.

The intended starting schema is v0.9.7, with edit-only knowledge integration. Use the ordinal 1–5 option for both fields that offer binary and ordinal alternatives:

- `KS_warrant_explicit`
- `KI_prior_stake_reflection`

Knowledge integration concerns identifiable candidate article edits, not appeals to process. Preserve the wording in the authoritative workbook rather than recreating definitions from this specification.

Create `config/project.toml` with at least:

- the source paths;
- `schema_version = "0.9.7"`;
- `schema_sheet = "Core_Schema_SIMPLIFIED"`;
- `phase = "calibration"`;
- `schema_locked = false`;
- `low_confidence_threshold = 2`;
- a configurable local database and export directory.

Do not duplicate the full codebook in source code. Parse definitions, coding rules, examples, and controlled values from the workbook. A small explicit dependency map for the current labels is appropriate; a generic no-code schema builder is out of scope.

## Core measurement constraints

1. The unit of utterance coding is one focal utterance.
2. When coding utterance `t`, expose the focal utterance and only utterances `1..t-1` from that dispute. Never expose a later utterance, even when revisiting a completed earlier item.
3. Keep every prior utterance available in chronological order. The interface may foreground recent or rule-relevant turns, but it must not semantically truncate the available past.
4. KS and KI are independent and may both equal 1.
5. Use `null` as the sole stored representation of not applicable. In spreadsheet exports, render null as a blank cell. Never use structural zero, `NA`, `N/A`, `none`, an empty array, or an equivalent token for inapplicability.
6. `C_primary_dispute_object` is dispute-level and requires the complete dispute. Collect it only on a separate post-dispute screen after all utterances in that dispute have been submitted. Do not expose the complete dispute during utterance coding. Store the dispute label once and propagate it to utterance rows on export.
7. Keep escalation outcome and all administrative sampling information hidden from coders and out of the coder interface.
8. Enforce calibration before held-out annotation. With `phase = "calibration"`, expose only calibration data. Held-out operation requires `phase = "heldout"` and `schema_locked = true`. Explain the transition in the README.

## Technology and scope

Use:

- Python 3.11 or newer;
- Streamlit for the local browser UI;
- standard-library `sqlite3` for persistence;
- pandas and/or openpyxl for `.xlsx` ingestion and export;
- pytest for tests;
- Ruff for lightweight linting/format checks;
- Streamlit's native `AppTest` for a small UI smoke-test suite where practical.

Prefer standard-library functionality when it is clear and reliable. Keep dependencies few and pinned or sensibly bounded. Do not add a server database, ORM, Docker, authentication service, external API, cloud dependency, telemetry, LLM assistance, semantic retrieval, JavaScript framework, or generic annotation-platform machinery.

Use a modest package structure such as:

```text
app.py
wikidisputes_ui/
  config.py
  codebook.py
  ingest.py
  models.py
  storage.py
  validation.py
  export.py
  ui_components.py
config/project.toml
tests/
data/source/
data/local/
exports/
```

Adjust names if a simpler coherent structure emerges. Keep business rules out of `app.py` so they can be unit tested.

## Input ingestion and quality checks

Recognize the coder-facing sheets in the current gold workbook, normally:

- `3_Calibration_Coder`
- `4_Heldout_Coder`

Preserve source rows and metadata. At minimum, expect and validate:

- `dispute_sequence`
- `dispute_id`
- `utterance_order`
- `utterance_id`
- `speaker_id`
- `timestamp`
- `reply_to_utterance_id`
- `utterance_type`
- `article_title`
- `utterance_text`
- the annotation columns defined in the current gold workbook

Create a deterministic validation command, for example:

```bash
python -m wikidisputes_ui.validation
```

Validation must produce a readable console summary and `reports/input_qc.md`. It must check:

- required files, sheets, and columns;
- unique utterance IDs within the sample;
- nonempty dispute IDs and texts;
- strictly increasing, gap-free `utterance_order` within each dispute;
- source row order consistent with `utterance_order`;
- reply targets exist within the same dispute and precede the focal utterance;
- the same dispute is not split or interleaved;
- every codebook label expected by the UI exists;
- allowed-value lists are available;
- calibration and held-out partitions do not overlap;
- exact or normalized repeated-text blocks within a dispute, reported as warnings rather than automatically deleted;
- obvious absorbed-turn or duplicate-ID risks that can be detected deterministically.

Do not silently reorder, delete, deduplicate, truncate, or repair source data. Blocking structural errors should prevent annotation and identify exact sheet rows/IDs. Warnings should remain visible to the researcher without exposing administrative information to the coder. If the supplied source currently fails QC, finish and test the software using small test fixtures, write the exact QC report, and state that the input—not the implementation—requires correction.

## Codebook loading and version control

At startup:

1. Read the simplified schema and controlled-value sheets.
2. Compute SHA-256 for the entire codebook file.
3. Register `schema_version`, hash, source filename, and UTC registration time in SQLite.
4. If an already registered version appears with a different hash, stop with a clear message requiring a version bump. Never silently treat changed directions as the same version.
5. If `schema_locked = true`, reject a changed version or hash for the active phase.
6. Record schema version and hash on every draft, submission, revision, and dispute-level decision.

Existing events must remain associated with the schema under which they were produced. A later revision under a new schema creates a new event and updates current state; it does not rewrite history.

## Local coder identity

On first launch, ask the annotator for a unique pseudonymous coder ID. Validate a concise format such as 3–40 characters containing letters, numbers, hyphens, or underscores. This is identification, not authentication; state that plainly.

Persist the ID locally and show it unobtrusively in the sidebar. Provide an explicit `Switch coder` action with a warning. Never display another coder's labels in the annotation interface. The normal research workflow is one local repository/database copy per coder.

## Annotation workflow

### Start/resume page

Show:

- active coder;
- active partition and schema version;
- number of completed utterances and disputes;
- percentage progress;
- review-flag count;
- current or next dispute;
- a prominent `Resume annotation` action.

Do not show escalation, sampling stratum, construct-enrichment scores, another coder's work, or aggregate label distributions that could prime decisions.

### Sequence and navigation

- Present disputes in the source `dispute_sequence` order and utterances in `utterance_order`.
- Within a dispute, do not permit skipping to a later uncoded utterance.
- Permit saving an incomplete draft and returning later.
- Permit revisiting submitted earlier utterances through a `Review completed` view.
- When revisiting utterance `t`, continue to show only `1..t-1`, regardless of how many later turns have since been coded.
- After a valid submission, provide `Save and next` and advance predictably.
- Do not label ordinary UI navigation as an annotation revision. Only saving changed annotation content creates a revision event.

## Main coding screen

Use Streamlit wide mode and a clean desktop-oriented layout. A good default is:

1. Compact progress/header row.
2. A prominent full-width focal-utterance card.
3. Two columns beneath it: context on the left (approximately 55–60%) and coding controls on the right.

### Focal card

Display:

- article title;
- dispute and utterance order;
- speaker;
- timestamp;
- utterance ID;
- utterance type;
- reply-to ID if present;
- full focal text without truncation.

Use hierarchy, whitespace, and a restrained accent color. Do not rely on color alone.

### Context column

Provide three layers:

1. **Direct reply target:** if present and valid, display it clearly near the top.
2. **Relevant prior turns:** list the direct parent plus earlier turns that this coder has already submitted as KS or KI. Label why a turn is surfaced. This is a navigational aid, not a machine recommendation. Do not hide the full history if an earlier coding choice was wrong.
3. **Conversation so far:** display all and only earlier turns chronologically in a bounded scrollable container. Show the most recent four turns directly and place older history in a clearly labeled expandable section if that improves readability. Never group turns by speaker or reorder them.

Each prior turn should show order, speaker, timestamp where available, ID, and full text. Use consistent, accessible speaker markers or initials without assigning a rainbow of colors.

### Coding column and progressive disclosure

Do not preselect substantive answers. Every applicable label must receive an explicit coder response before submission.

Start with these required fields:

- `KS_present`
- `KI_present`
- `C_interpersonal_hostility`
- `C_formal_escalation_signal`

Use clear `No` / `Yes` controls while storing canonical `0` / `1`.

Show the concise definition next to each decision. Put the detailed coding rule, boundary, and example in an expander or popover immediately associated with the field. All displayed guidance must come from the active codebook.

Apply these dependencies:

- If `KS_present = 0`, all KS subfields are null.
- If `KS_present = 1`, require applicable KS subfields.
- Show `KS_evidence_type` and `KS_warrant_explicit` only when `KS_evidence_present = 1`.
- `KS_evidence_type` is a multi-select using canonical values from `Evidence_Types`; export unique values alphabetically with semicolons.
- Render `KS_warrant_explicit` as five discrete ordinal choices with the codebook anchors visible. Do not use a continuous slider.
- `KS_repetition_or_restaking` is null if there is no earlier submitted KS utterance; otherwise require 0/1 when KS is present.
- If `KI_present = 0`, KI subfields governed by KI presence are null. Treat `KI_explicit_feedback` separately: when an earlier candidate edit exists, it may be answered even if `KI_present = 0`, exactly as allowed by the codebook.
- If `KI_present = 1`, require applicable KI subfields.
- `KI_iterate_on_candidate_action` is null when there is no earlier identifiable submitted candidate edit.
- Render `KI_prior_stake_reflection` as five discrete ordinal choices with anchors. It is null when there is no earlier submitted KS utterance.
- When an earlier candidate edit exists, show `KI_explicit_feedback` regardless of `KI_present` and require an explicit UI choice. Include `No explicit feedback`, which is stored as null but marked as deliberately answered. Other stored values must be exactly `accept`, `reject`, or `mixed_or_conditional`. When no earlier candidate edit exists, make this field automatically inapplicable/null.

Maintain an `answered_fields` collection or equivalent so deliberate null is distinguishable from an untouched control. Disabled inapplicable fields should visibly say `Not applicable` and must not invite input.

### Audit inputs

Include:

- `KS_evidence_span`
- `KS_prior_utterance_ids`
- `KI_evidence_span`
- `KI_upstream_utterance_ids`
- `control_evidence_span`
- `coder_confidence`
- `short_justification`
- `review_flag`
- `coder_notes`

For upstream IDs, use a multiselect of valid earlier utterances with readable labels such as `#4 — Speaker — short excerpt`; store canonical IDs and export them separated by semicolons. Never permit a current or future ID.

Evidence-span fields may be compact text areas for pasted exact phrases. Do not build text-selection/highlighting JavaScript in the MVP.

Require compact audit evidence only when it is directly relevant: require `KS_evidence_span` for a positive KS decision, `KI_evidence_span` for a positive KI decision, and `control_evidence_span` when either utterance-level control is positive. Require `KS_prior_utterance_ids` when repetition/restaking is positive. Require `KI_upstream_utterance_ids` when iteration is positive, explicit feedback is non-null, or prior-stake reflection indicates an identifiable connection above the no-connection endpoint. Otherwise these audit fields may be blank/null.

Require `coder_confidence` as a discrete 1–5 choice and `review_flag` as explicit No/Yes. Require `short_justification` only when confidence is at or below `low_confidence_threshold` or `review_flag = 1`. Otherwise it is optional. Explain the trigger inline. `coder_notes` is always optional.

### Submit validation

`Save draft` may persist incomplete work. `Submit and next` must block until:

- all applicable fields have explicit valid responses;
- all inapplicable fields are null;
- every dependency is satisfied;
- evidence types are canonical;
- upstream IDs precede the focal utterance;
- targeted justification requirements are satisfied.

Give specific, field-level error messages. Preserve entered values after validation errors.

## Dispute-level coding

After all utterances in a dispute have been submitted:

1. Display the complete dispute in chronological order.
2. Show all primary-object definitions and rules from `Primary_Dispute_Objects` in a compact, readable form.
3. Require exactly one canonical `C_primary_dispute_object` value.
4. Collect dispute-level confidence, review flag, and an optional note; require a short justification only for low confidence or review flag.
5. Record this as a versioned dispute event.
6. Mark the dispute complete only after this step.

Do not make the complete-dispute view accessible from an unfinished utterance-level dispute.

## Persistence, timestamps, timing, and revisions

Use SQLite with foreign keys and transactions. WAL mode is acceptable but no concurrency engineering beyond sensible SQLite practices is needed for a private local copy.

Maintain current-state tables and append-only event history. A reasonable design includes:

- coders;
- schema versions;
- current utterance annotations;
- utterance annotation events;
- current dispute annotations;
- dispute annotation events.

Every saved event should have:

- an immutable event ID;
- coder ID;
- unit type and canonical unit IDs;
- partition;
- event type (`draft`, `submit`, or `revise`);
- full label/audit payload or an unambiguous snapshot;
- answered fields;
- schema version and hash;
- UTC `opened_at` and `saved_at` in timezone-aware ISO 8601 form ending in `Z`;
- elapsed wall seconds;
- revision number;
- application version or Git commit when available without failure.

Start a timing attempt when a focal item is opened for work and close it when draft/submission/revision is saved. Treat timing as best-effort wall time, not verified active-attention time. Handle refresh/restart conservatively and document the limitation. Do not add browser-activity tracking or custom JavaScript.

Submitting a new item creates revision 1. Saving changed content on an already submitted item appends a revision event and increments its revision. Never overwrite or delete earlier events. Show the current coder a compact history expander with revision numbers and UTC save times.

## Export and backup

Provide an `Export my annotations` action that creates a single `.xlsx` workbook for the active coder. It should contain at least:

- `Calibration_Annotations`
- `Heldout_Annotations`
- `Dispute_Annotations`
- `Annotation_Events`
- `Dispute_Events`
- `Schema_Versions`
- `QC_Report`

The two current-state utterance sheets must preserve the original source metadata and annotation columns, populate `coder_id`, and add audit/provenance columns after the existing schema where useful. Propagate the dispute-level primary object to each submitted utterance row. Use blanks for null. Preserve integer types. Export evidence types and ID lists as canonical semicolon-separated strings.

Include all of this coder's historical events so revisions remain auditable. Do not include another coder's data. Make exports deterministic except for explicitly generated export timestamps. Use a safe filename containing coder ID and UTC time.

Also provide a prominent `Download database backup` action for the local SQLite file, using a safe consistent snapshot rather than copying during an open write transaction.

Never modify or overwrite `gold_input.xlsx`.

## Visual and interaction requirements

- Optimize for a laptop/desktop at approximately 1280–1600 px width.
- Use a restrained neutral palette, one accent color, readable typography, and generous but not wasteful whitespace.
- Avoid spreadsheet-like grids, decorative charts, gradients, excessive cards, and animation.
- Use clear section headings and a visible progress indicator.
- Keep definitions close to their controls and detailed rules available on demand.
- Preserve full text and sensible wrapping.
- Maintain keyboard tab order and visible labels.
- Meet basic WCAG-oriented contrast and do not encode meaning only through color.
- Use minimal documented CSS only where native Streamlit cannot achieve a clear focal/context hierarchy. Do not target fragile generated CSS class names.
- Hide Streamlit development chrome only if it can be done safely and accessibly.

## Documentation and repo hygiene

Create:

- `README.md` with concise Windows PowerShell and macOS/Linux setup, validation, launch, export, backup, calibration-to-held-out transition, and troubleshooting commands;
- `AGENTS.md` with repository layout, commands, conventions, source-file immutability, and definition of done for future Codex work;
- a short architecture/versioning note under `docs/`;
- `requirements.txt` and `requirements-dev.txt` so setup and verification commands are deterministic;
- `.gitignore` covering `.venv`, caches, `data/local`, generated exports, and reports where appropriate without ignoring the two intended source workbooks;
- test fixtures that are synthetic and small rather than copies of real conversations.

The README must state that each coder should receive a separate copy of the repository or at minimum a separate database path, and that coder IDs identify rather than authenticate users.

## Tests and verification

Write focused automated tests for at least:

1. codebook parsing and controlled values;
2. ordinal selection for the two specified fields;
3. version/hash drift detection;
4. input ordering, duplicate IDs, reply closure, partition overlap, and warnings;
5. strict no-future-context retrieval, including revision of an earlier item;
6. conditional applicability and null semantics;
7. explicit answered-null handling for `KI_explicit_feedback`;
8. upstream-ID validation;
9. targeted justification trigger;
10. calibration/held-out gating;
11. append-only events and revision numbering;
12. UTC timestamps and nonnegative elapsed wall time;
13. dispute-level completion and propagation;
14. export round-trip values, blank nulls, semicolon lists, and coder isolation;
15. a Streamlit `AppTest` smoke path for coder entry and the first focal item, if supported without brittle mocking.

Run the complete test suite and lint/format checks. Run input validation against the supplied source files and retain the generated QC report. Start the Streamlit app against valid synthetic fixtures if real input is blocked. Inspect the rendered interface in a browser at desktop width if browser tooling is available; otherwise use AppTest plus a careful code-level UI review. Fix serious usability, overflow, state-loss, dependency, and accessibility defects found.

Perform a final diff review for:

- accidental source-workbook changes;
- future-context leakage;
- hidden defaults;
- structural zeros in place of null;
- lost revision history;
- unversioned annotations;
- exports that cannot be re-imported or audited;
- unnecessary complexity or dependencies.

## Definition of done

The task is complete only when:

- a coder can enter an ID, resume work, annotate a dispute sequentially, complete its dispute-level object, revise earlier work, and export an auditable workbook;
- source workbooks remain byte-for-byte unchanged;
- the UI reads v0.9.7 `Core_Schema_SIMPLIFIED` and uses ordinal warrant/prior-stake reflection;
- future turns and escalation information cannot leak into utterance coding;
- schema version/hash, UTC timestamps, wall time, and revisions are recorded;
- rationales are required only for low-confidence or review-flagged decisions;
- calibration/held-out gating works;
- automated tests and lint checks pass;
- the actual input QC result is documented precisely;
- README commands work from a fresh virtual environment;
- there are no placeholder implementations, unresolved TODOs in the requested scope, or silently ignored validation failures.

In the final response, lead with whether the application is ready to run. Summarize the implementation, tests/checks run and their results, actual input QC status, and the exact commands the user should run next. Clearly distinguish an invalid source workbook from an implementation defect.

## Design references

These sources motivate the interface constraints; they are not additional functionality requirements:

- Klie et al. (2024), *Analyzing Dataset Annotation Quality Management in the Wild*: https://aclanthology.org/2024.cl-3.1/
- Siro et al. (2024), *Implications for Crowdsourced Evaluation Labels in Task-Oriented Dialogue Systems*: https://aclanthology.org/2024.findings-naacl.80/
- Guibon et al. (2022), *EZCAT: an Easy Conversation Annotation Tool*: https://aclanthology.org/2022.lrec-1.190/
- Dandapat et al. (2009), *Complex Linguistic Annotation—No Easy Way Out!*: https://aclanthology.org/W09-3002/
- Gooding et al. (2023), *A Pilot Study on Annotation Interfaces for Summary Comparisons*: https://aclanthology.org/2023.law-1.18/
