"""Streamlit entry point for local WikiDisputes annotation."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import time

import pandas as pd
import streamlit as st

from wikidisputes_ui.codebook import load_codebook
from wikidisputes_ui.config import load_config
from wikidisputes_ui.export import build_export, safe_export_name
from wikidisputes_ui.ingest import article_title, read_gold
from wikidisputes_ui.models import BASE_BINARY, ContextState, applicable_fields, normalize_and_validate
from wikidisputes_ui.storage import SchemaDriftError, Storage
from wikidisputes_ui.ui_components import (
    binary_control,
    canonical_caption,
    discussion_heading,
    focal_card,
    guide,
    inject_css,
    prior_comment,
    source_details,
    turn_card,
)
from wikidisputes_ui.validation import render_report, validate_inputs

st.set_page_config(page_title="WikiDisputes annotation", page_icon="✎", layout="wide")
inject_css()


def opened_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@st.cache_resource
def resources():
    config = load_config(os.environ.get("WIKIDISPUTES_CONFIG", "config/project.toml"))
    qc = validate_inputs(config)
    if qc.blocking:
        return config, qc, None, None, None
    codebook = load_codebook(config.codebook_path, config.schema_sheet)
    dataset = read_gold(config.gold_path, config.annotation_sheet)
    storage = Storage(config.database_path)
    storage.register_schema(config.schema_version, codebook.file_hash, codebook.source_filename, config.schema_locked)
    return config, qc, codebook, dataset, storage


try:
    config, qc, codebook, dataset, storage = resources()
except SchemaDriftError as exc:
    st.error(f"Schema registration stopped: {exc}")
    st.stop()
except Exception as exc:
    st.error(f"Startup failed: {exc}")
    st.stop()

if qc.blocking:
    st.title("Input quality check blocked annotation")
    st.error("The source workbook has blocking structural errors. No source data were changed.")
    st.markdown(render_report(qc, config))
    st.stop()

coder = storage.active_coder()
if coder is None:
    st.title("WikiDisputes annotation")
    st.info(
        "Your coder ID identifies your local work; it is not authentication. Use a pseudonymous ID assigned for this study."
    )
    with st.form("coder_entry"):
        candidate = st.text_input("Coder ID", placeholder="e.g. coder_01")
        if st.form_submit_button("Continue", type="primary"):
            try:
                storage.set_active_coder(candidate.strip())
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.stop()

st.sidebar.caption(f"Coder: **{coder}**")
st.sidebar.caption(f"Schema: **{config.schema_version}**")
if st.sidebar.button("Switch coder"):
    st.session_state.confirm_switch = True
if st.session_state.get("confirm_switch"):
    st.sidebar.warning("Switching changes whose private annotations are shown.")
    if st.sidebar.button("Confirm switch"):
        with storage.connect() as db:
            db.execute("UPDATE coders SET active=0")
        st.session_state.clear()
        st.rerun()

qc_text = render_report(qc, config)
export_data = build_export(storage, dataset, coder, qc_text)
st.sidebar.download_button(
    "Export my annotations",
    export_data,
    safe_export_name(coder),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
st.sidebar.download_button(
    "Download database backup",
    storage.backup_bytes(),
    f"wikidisputes_{coder}_backup.sqlite3",
    "application/vnd.sqlite3",
)

frame = dataset.annotatable_rows
annotatable_ids = set(frame["utterance_id"].astype(str))
dispute_ids = set(frame["dispute_id"].astype(str))
submitted_rows = storage.rows("utterance_annotations", coder)
submitted = {
    str(row["utterance_id"]): row
    for row in submitted_rows
    if row["status"] == "submitted" and str(row["utterance_id"]) in annotatable_ids
}
dispute_rows = storage.rows("dispute_annotations", coder)
completed_disputes = {str(row["dispute_id"]) for row in dispute_rows if str(row["dispute_id"]) in dispute_ids}
review_count = sum(bool(__import__("json").loads(row["payload_json"]).get("review_flag")) for row in submitted.values())

if "page" not in st.session_state:
    st.session_state.page = "home"

if st.session_state.page == "home":
    st.title("Annotation workspace")
    cols = st.columns(4)
    cols[0].metric("Utterances", f"{len(submitted)} / {len(frame)}")
    cols[1].metric("Disputes", f"{len(completed_disputes)} / {frame['dispute_id'].nunique()}")
    cols[2].metric("Progress", f"{100 * len(submitted) / max(1, len(frame)):.1f}%")
    cols[3].metric("Review flags", review_count)
    ready_for_dispute = []
    for dispute_id in frame["dispute_id"].drop_duplicates():
        dispute_id = str(dispute_id)
        unit_ids = set(dataset.annotatable_in_dispute(dispute_id)["utterance_id"].astype(str))
        if unit_ids <= set(submitted) and dispute_id not in completed_disputes:
            ready_for_dispute.append(dispute_id)
    next_rows = frame[~frame["utterance_id"].astype(str).isin(submitted)]
    if ready_for_dispute:
        st.write(f"Next: complete the dispute-level decision for **{ready_for_dispute[0]}**.")
        if st.button("Complete dispute", type="primary"):
            st.session_state.page = "dispute"
            st.session_state.dispute_id = ready_for_dispute[0]
            st.session_state.dispute_timer_start = time.monotonic()
            st.session_state.dispute_opened_at = opened_at()
            st.rerun()
    elif not next_rows.empty:
        next_row = next_rows.iloc[0]
        st.write(f"Next: **{article_title(next_row)}**, utterance #{int(next_row['utterance_order'])}")
        if st.button("Resume annotation", type="primary"):
            st.session_state.unit_id = str(next_row["utterance_id"])
            st.session_state.page = "utterance"
            st.rerun()
    else:
        st.success("All utterances have been submitted. Complete any remaining dispute-level decisions.")
        pending_disputes = [
            str(dispute_id)
            for dispute_id in frame["dispute_id"].drop_duplicates()
            if str(dispute_id) not in completed_disputes
        ]
        if pending_disputes and st.button("Complete next dispute", type="primary"):
            st.session_state.page = "dispute"
            st.session_state.dispute_id = pending_disputes[0]
            st.session_state.dispute_timer_start = time.monotonic()
            st.session_state.dispute_opened_at = opened_at()
            st.rerun()
    if submitted:
        choices = {f"{uid} · revision {row['revision_number']}": uid for uid, row in submitted.items()}
        selected = st.selectbox(
            "Review completed", list(choices), index=None, placeholder="Choose an earlier utterance"
        )
        if selected and st.button("Open for review"):
            st.session_state.unit_id = choices[selected]
            st.session_state.page = "utterance"
            st.rerun()
    if completed_disputes:
        dispute_choice = st.selectbox(
            "Review completed dispute",
            sorted(completed_disputes),
            index=None,
            placeholder="Choose a dispute-level decision",
        )
        if dispute_choice and st.button("Open dispute decision"):
            st.session_state.page = "dispute"
            st.session_state.dispute_id = dispute_choice
            st.session_state.dispute_timer_start = time.monotonic()
            st.session_state.dispute_opened_at = opened_at()
            st.rerun()
    st.stop()

if st.session_state.page == "dispute":
    st.title("Complete dispute-level coding")
    did = st.session_state.dispute_id
    if st.session_state.get("dispute_timer_did") != did:
        st.session_state.dispute_timer_did = did
        st.session_state.dispute_timer_start = time.monotonic()
        st.session_state.dispute_opened_at = opened_at()
    full = dataset.full_dispute(did)
    for _, turn in full.iterrows():
        turn_card(turn)
    st.subheader("Primary dispute object")
    for name, item in codebook.dispute_objects.items():
        with st.expander(name):
            st.write(item["Definition"])
            st.write(item["Dispute-level coding rule"])
    existing_rows = [item for item in dispute_rows if str(item["dispute_id"]) == did]
    existing = {} if not existing_rows else __import__("json").loads(existing_rows[0]["payload_json"])
    object_options = sorted(codebook.dispute_objects)
    choice = st.radio(
        "C_primary_dispute_object",
        object_options,
        index=object_options.index(existing["C_primary_dispute_object"])
        if existing.get("C_primary_dispute_object") in object_options
        else None,
    )
    confidence = st.radio(
        "Dispute confidence",
        range(1, 6),
        index=existing["coder_confidence"] - 1 if existing.get("coder_confidence") in range(1, 6) else None,
        horizontal=True,
    )
    review = binary_control("Dispute review flag", f"dispute_review_{did}", existing.get("review_flag"))
    justification = st.text_area("Dispute short justification", value=existing.get("short_justification") or "")
    note = st.text_area("Dispute note (optional)", value=existing.get("coder_notes") or "")
    if st.button("Complete dispute", type="primary"):
        errors = []
        if choice is None:
            errors.append("Choose exactly one primary dispute object.")
        if confidence is None:
            errors.append("Choose dispute confidence.")
        if review is None:
            errors.append("Choose a dispute review flag.")
        if (
            review == 1 or confidence is not None and confidence <= config.low_confidence_threshold
        ) and not justification.strip():
            errors.append("A short justification is required for low confidence or a review flag.")
        if errors:
            for error in errors:
                st.error(error)
        else:
            storage.save_dispute(
                coder=coder,
                dispute_id=did,
                payload={
                    "C_primary_dispute_object": choice,
                    "coder_confidence": confidence,
                    "review_flag": review,
                    "short_justification": justification or None,
                    "coder_notes": note or None,
                },
                answered_fields={"C_primary_dispute_object", "coder_confidence", "review_flag"},
                schema_version=config.schema_version,
                schema_hash=codebook.file_hash,
                opened_at=st.session_state.dispute_opened_at,
                elapsed_wall_seconds=time.monotonic() - st.session_state.dispute_timer_start,
            )
            st.session_state.page = "home"
            st.rerun()
    if existing_rows:
        with st.expander("Dispute decision history"):
            history = [
                item for item in storage.rows("dispute_annotation_events", coder) if str(item["dispute_id"]) == did
            ]
            for event in history:
                st.write(f"Revision {event['revision_number']} · {event['event_type']} · {event['saved_at']}")
    st.stop()

uid = st.session_state.unit_id
matches = frame[frame["utterance_id"].astype(str) == uid]
if matches.empty:
    st.error("Selected utterance is not annotatable.")
    st.stop()
row = matches.iloc[0]
did = str(row["dispute_id"])
order = int(row["utterance_order"])
prior = dataset.displayable_prior_context(did, order)
earlier_turns = dataset.earlier_annotatable_turns(did, order)
current = storage.current_utterance(coder, uid)
prior_annotations = {
    str(item["utterance_id"]): __import__("json").loads(item["payload_json"])
    for item in submitted_rows
    if item["status"] == "submitted"
    and str(item["dispute_id"]) == did
    and str(item["utterance_id"]) in set(earlier_turns["utterance_id"].astype(str))
}
context = ContextState(
    tuple(earlier_turns["utterance_id"].astype(str)),
    any(v.get("KS_present") == 1 for v in prior_annotations.values()),
    any(
        v.get("KI_propose_action") == 1 or v.get("KI_announce_enacted_action") == 1 for v in prior_annotations.values()
    ),
)
defaults = {} if not current else current["payload"]
if st.session_state.get("timer_uid") != uid:
    st.session_state.timer_uid = uid
    st.session_state.utterance_timer_start = time.monotonic()
    st.session_state.utterance_opened_at = opened_at()

st.progress(len(submitted) / max(1, len(frame)), text=f"{len(submitted)} of {len(frame)} utterances submitted")

gateway_labels = {
    "KS_present": "Knowledge staking (KS)",
    "KI_present": "Knowledge integration (KI)",
    "C_interpersonal_hostility": "Interpersonal hostility",
    "C_formal_escalation_signal": "Formal escalation signal",
}
field_labels = {
    "KS_problem_claim_specified": "Specifies a problem or claim",
    "KS_evidence_present": "Presents evidence",
    "KS_acceptability_condition": "States an acceptability condition",
    "KS_derailment": "Derails the knowledge exchange",
    "KS_repetition_or_restaking": "Repeats or restakes earlier knowledge",
    "KI_propose_action": "Proposes an action",
    "KI_announce_enacted_action": "Announces an enacted action",
    "KI_solicit": "Solicits integration",
    "KI_iterate_on_candidate_action": "Iterates on an earlier candidate action",
}

if st.session_state.get("stage_uid") != uid:
    st.session_state.stage_uid = uid
    gateways_complete = current is not None and set(BASE_BINARY) <= set(current["answered_fields"])
    st.session_state.annotation_stage = 2 if gateways_complete else 1

context_rows = prior[prior["utterance_role"] == "context"]
context_row = None if context_rows.empty else context_rows.iloc[0]
target = row.get("reply_to_utterance_id")
direct = prior[prior["utterance_id"].astype(str) == str(target)] if not pd.isna(target) else prior.iloc[0:0]
if not direct.empty and direct.iloc[0].get("utterance_role") == "utterance":
    target_turn = direct.iloc[0]
    reply_description = f"Replying to {target_turn['speaker_id']} (#{int(target_turn['utterance_order'])})"
elif not direct.empty and direct.iloc[0].get("utterance_role") == "context":
    reply_description = "Replies to section heading"
elif not pd.isna(target):
    reply_description = "Reply target unavailable within prior context"
else:
    reply_description = None

reading, coding = st.columns([0.56, 0.44], gap="large")
with reading.container(height=700, border=False, key="reading_pane"):
    if context_row is not None:
        discussion_heading(context_row)
    else:
        st.caption(article_title(row))
    focal_card(row, reply_description)
    source_details(row)
    st.subheader("Earlier conversation")
    prior_turns = prior[prior["utterance_role"] == "utterance"]
    if prior_turns.empty:
        st.caption("No earlier substantive turns. Future turns are never shown here.")
    relevant_ids = {
        key for key, value in prior_annotations.items() if value.get("KS_present") == 1 or value.get("KI_present") == 1
    }
    direct_id = None if direct.empty or direct.iloc[0].get("utterance_role") != "utterance" else str(target)
    older, recent = prior_turns.iloc[:-4], prior_turns.iloc[-4:]

    def render_prior(turn):
        turn_id = str(turn["utterance_id"])
        badges = []
        if turn_id == direct_id:
            badges.append("Reply target")
        if turn_id in relevant_ids:
            badges.append("Earlier KS/KI")
        prior_comment(turn, tuple(badges))

    if not older.empty:
        with st.expander(
            f"Older history ({len(older)} turns)", expanded=direct_id in set(older.utterance_id.astype(str))
        ):
            for _, turn in older.iterrows():
                render_prior(turn)
    for _, turn in recent.iterrows():
        render_prior(turn)
    if not pd.isna(target) and direct.empty:
        st.info("The reply target is not available within the strict prior-context boundary; its text is not shown.")

with coding.container(height=700, border=False, key="coding_pane"):
    values = dict(defaults)
    answered = set() if not current else set(current["answered_fields"])

    def set_binary(name: str, label: str | None = None, key_prefix: str = "field") -> None:
        value = binary_control(label or field_labels.get(name, name), f"{key_prefix}_{name}_{uid}", values.get(name))
        values[name] = value
        if value is not None:
            answered.add(name)
        guide(name, codebook.fields[name], binary=True)

    def save_result(result, submit: bool):
        stored_answered = answered & applicable_fields(result.payload, context, config.low_confidence_threshold)
        return storage.save_utterance(
            coder=coder,
            utterance_id=uid,
            dispute_id=did,
            payload=result.payload,
            answered_fields=stored_answered,
            submit=submit,
            schema_version=config.schema_version,
            schema_hash=codebook.file_hash,
            opened_at=st.session_state.utterance_opened_at,
            elapsed_wall_seconds=time.monotonic() - st.session_state.utterance_timer_start,
        )

    if st.session_state.annotation_stage == 1:
        st.subheader("1. Identify what is present")
        for name in BASE_BINARY[:2]:
            set_binary(name, gateway_labels[name], "gateway")
            canonical_caption(name)
        st.markdown("#### Controls")
        for name in BASE_BINARY[2:]:
            set_binary(name, gateway_labels[name], "gateway")
            canonical_caption(name)
        clearing = [name for name in BASE_BINARY if defaults.get(name) == 1 and values.get(name) == 0]
        if clearing:
            st.warning(
                "Continuing will clear child answers that no longer apply for: "
                + ", ".join(gateway_labels[name] for name in clearing)
                + "."
            )
        if st.button("Apply changes and continue" if clearing else "Continue to details", type="primary"):
            missing = [name for name in BASE_BINARY if values.get(name) not in (0, 1)]
            if missing:
                for name in missing:
                    st.error(f"Answer {gateway_labels[name]} before continuing.")
            else:
                result = normalize_and_validate(
                    values, answered, context, set(codebook.evidence_types), config.low_confidence_threshold, False
                )
                save_result(result, False)
                st.session_state.annotation_stage = 2
                st.rerun()
    else:
        st.subheader("2. Code applicable details")
        summary = " · ".join(
            f"{label}: {'Yes' if values.get(name) == 1 else 'No'}"
            for name, label in (
                ("KS_present", "KS"),
                ("KI_present", "KI"),
                ("C_interpersonal_hostility", "Hostility"),
                ("C_formal_escalation_signal", "Formal escalation"),
            )
        )
        st.caption(summary)
        if st.button("Change presence answers"):
            st.session_state.annotation_stage = 1
            st.rerun()

        labels = {
            str(
                turn["utterance_id"]
            ): f"#{int(turn['utterance_order'])} — {turn['speaker_id']} — {str(turn['utterance_text'])[:55]}"
            for _, turn in earlier_turns.iterrows()
        }
        if values.get("KS_present") == 1:
            st.markdown("#### Knowledge staking details")
            for name in (
                "KS_problem_claim_specified",
                "KS_evidence_present",
                "KS_acceptability_condition",
                "KS_derailment",
            ):
                set_binary(name)
            if context.earlier_ks:
                set_binary("KS_repetition_or_restaking")
                if values.get("KS_repetition_or_restaking") == 1:
                    values["KS_prior_utterance_ids"] = st.multiselect(
                        "Earlier KS utterances",
                        list(labels),
                        default=values.get("KS_prior_utterance_ids") or [],
                        format_func=labels.get,
                        key=f"ids_KS_prior_utterance_ids_{uid}",
                    )
                    if values["KS_prior_utterance_ids"]:
                        answered.add("KS_prior_utterance_ids")
            if values.get("KS_evidence_present") == 1:
                values["KS_evidence_type"] = st.multiselect(
                    "Evidence type",
                    sorted(codebook.evidence_types),
                    default=values.get("KS_evidence_type") or [],
                    key=f"ev_{uid}",
                )
                if values["KS_evidence_type"]:
                    answered.add("KS_evidence_type")
                guide("KS_evidence_type", codebook.fields["KS_evidence_type"])
                with st.expander("Evidence type definitions"):
                    for evidence_name, evidence_guide in codebook.evidence_types.items():
                        st.markdown(f"**{evidence_name}** — {evidence_guide['Definition']}")
                values["KS_warrant_explicit"] = st.radio(
                    "Warrant explicitness",
                    range(1, 6),
                    index=values.get("KS_warrant_explicit") - 1
                    if values.get("KS_warrant_explicit") in range(1, 6)
                    else None,
                    horizontal=True,
                    key=f"warrant_{uid}",
                )
                if values["KS_warrant_explicit"] is not None:
                    answered.add("KS_warrant_explicit")
                guide("KS_warrant_explicit", codebook.fields["KS_warrant_explicit"])
            values["KS_evidence_span"] = st.text_area(
                "KS evidence span", value=values.get("KS_evidence_span") or "", key=f"text_KS_evidence_span_{uid}"
            )
            if values["KS_evidence_span"].strip():
                answered.add("KS_evidence_span")

        if values.get("KI_present") == 1:
            st.markdown("#### Knowledge integration details")
            for name in ("KI_propose_action", "KI_announce_enacted_action", "KI_solicit"):
                set_binary(name)
            if context.earlier_candidate:
                set_binary("KI_iterate_on_candidate_action")
                feedback_options = {
                    "No explicit feedback": None,
                    "Accept": "accept",
                    "Reject": "reject",
                    "Mixed or conditional": "mixed_or_conditional",
                }
                reverse = {value: label for label, value in feedback_options.items()}
                existing = (
                    reverse.get(values.get("KI_explicit_feedback")) if "KI_explicit_feedback" in answered else None
                )
                choice = st.radio(
                    "Explicit feedback on an earlier candidate",
                    list(feedback_options),
                    index=list(feedback_options).index(existing) if existing else None,
                    key=f"feedback_{uid}",
                )
                if choice is not None:
                    values["KI_explicit_feedback"] = feedback_options[choice]
                    answered.add("KI_explicit_feedback")
                guide("KI_explicit_feedback", codebook.fields["KI_explicit_feedback"])
            if context.earlier_ks:
                values["KI_prior_stake_reflection"] = st.radio(
                    "Reflection on prior stakes",
                    range(1, 6),
                    index=values.get("KI_prior_stake_reflection") - 1
                    if values.get("KI_prior_stake_reflection") in range(1, 6)
                    else None,
                    horizontal=True,
                    key=f"reflection_{uid}",
                )
                if values["KI_prior_stake_reflection"] is not None:
                    answered.add("KI_prior_stake_reflection")
                guide("KI_prior_stake_reflection", codebook.fields["KI_prior_stake_reflection"])
            needs_upstream = (
                values.get("KI_iterate_on_candidate_action") == 1
                or values.get("KI_explicit_feedback") in {"accept", "reject", "mixed_or_conditional"}
                or isinstance(values.get("KI_prior_stake_reflection"), int)
                and values["KI_prior_stake_reflection"] > 1
            )
            if needs_upstream:
                values["KI_upstream_utterance_ids"] = st.multiselect(
                    "Upstream utterances",
                    list(labels),
                    default=values.get("KI_upstream_utterance_ids") or [],
                    format_func=labels.get,
                    key=f"ids_KI_upstream_utterance_ids_{uid}",
                )
                if values["KI_upstream_utterance_ids"]:
                    answered.add("KI_upstream_utterance_ids")
            values["KI_evidence_span"] = st.text_area(
                "KI evidence span", value=values.get("KI_evidence_span") or "", key=f"text_KI_evidence_span_{uid}"
            )
            if values["KI_evidence_span"].strip():
                answered.add("KI_evidence_span")

        if values.get("C_interpersonal_hostility") == 1 or values.get("C_formal_escalation_signal") == 1:
            st.markdown("#### Control evidence")
            values["control_evidence_span"] = st.text_area(
                "Control evidence span",
                value=values.get("control_evidence_span") or "",
                key=f"text_control_evidence_span_{uid}",
            )
            if values["control_evidence_span"].strip():
                answered.add("control_evidence_span")
        if not any(values.get(name) == 1 for name in BASE_BINARY):
            st.info("No detailed fields apply. Complete confidence and review below.")

        st.markdown("#### Confidence and review")
        values["coder_confidence"] = st.radio(
            "Coder confidence",
            range(1, 6),
            index=values.get("coder_confidence") - 1 if values.get("coder_confidence") in range(1, 6) else None,
            horizontal=True,
            key=f"confidence_{uid}",
        )
        if values["coder_confidence"] is not None:
            answered.add("coder_confidence")
        values["review_flag"] = binary_control("Flag for review", f"review_{uid}", values.get("review_flag"))
        if values["review_flag"] is not None:
            answered.add("review_flag")
        needs_justification = values.get("review_flag") == 1 or (
            isinstance(values.get("coder_confidence"), int)
            and values["coder_confidence"] <= config.low_confidence_threshold
        )
        if needs_justification:
            st.caption("Required because confidence is low or this utterance is flagged for review.")
        else:
            st.caption(
                "Short justification becomes required when confidence is "
                f"{config.low_confidence_threshold} or lower, or when the utterance is flagged for review."
            )
        values["short_justification"] = st.text_area(
            "Short justification",
            value=values.get("short_justification") or "",
            key=f"text_short_justification_{uid}",
            disabled=not needs_justification,
        )
        if values["short_justification"].strip():
            answered.add("short_justification")
        with st.expander("Optional coder notes"):
            st.caption("Optional. Notes are recorded when you save a draft or submit the annotation.")
            values["coder_notes"] = st.text_area(
                "Coder notes", value=values.get("coder_notes") or "", key=f"text_coder_notes_{uid}"
            )
            if values["coder_notes"].strip():
                answered.add("coder_notes")
                st.caption("Coder notes entered; save the draft or submit to record them.")

        draft_col, submit_col = st.columns(2)
        if draft_col.button("Save draft", use_container_width=True):
            result = normalize_and_validate(
                values, answered, context, set(codebook.evidence_types), config.low_confidence_threshold, False
            )
            event, _ = save_result(result, False)
            st.success("Draft unchanged." if event == "unchanged" else "Draft saved.")
        if submit_col.button("Submit and next", type="primary", use_container_width=True):
            result = normalize_and_validate(
                values, answered, context, set(codebook.evidence_types), config.low_confidence_threshold, True
            )
            if not result.valid:
                for name, message in result.errors.items():
                    st.error(f"{name}: {message}")
            else:
                save_result(result, True)
                full = dataset.annotatable_in_dispute(did)
                now_submitted = set(submitted) | {uid}
                if set(full["utterance_id"].astype(str)) <= now_submitted:
                    st.session_state.page = "dispute"
                    st.session_state.dispute_id = did
                    st.session_state.dispute_timer_start = time.monotonic()
                    st.session_state.dispute_opened_at = opened_at()
                else:
                    nxt = full[~full["utterance_id"].astype(str).isin(now_submitted)].iloc[0]
                    st.session_state.unit_id = str(nxt["utterance_id"])
                st.rerun()
        with st.expander("Revision history"):
            history = [r for r in storage.rows("utterance_annotation_events", coder) if str(r["utterance_id"]) == uid]
            for event in history:
                st.write(f"Revision {event['revision_number']} · {event['event_type']} · {event['saved_at']}")
