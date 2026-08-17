# Simplified annotation build specification

The application reads immutable `Gold_Annotation` source rows and the single authoritative `Core_Schema` worksheet.
It preserves row/dispute/utterance order and never treats legacy workbook annotations as current coder state.

Within an opened dispute, the focal utterance and strictly earlier discussion appear beside one continuous form.
Conditional KS and KI children appear inline and independently. Every utterance has one confidence, one review flag,
and one optional comment. Submission advances chronologically. The only dispute-level task is
`C_primary_dispute_object`, shown after all substantive utterances are submitted.

Inapplicable values are stored as null and exported blank. SQLite projections remain mutable while event history is
append-only and schema-hash isolated. Exports exclude obsolete fields, legacy gold values, drafts, other coders, and
earlier schemas.
