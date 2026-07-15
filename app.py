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
from wikidisputes_ui.models import ContextState, normalize_and_validate
from wikidisputes_ui.storage import SchemaDriftError, Storage
from wikidisputes_ui.ui_components import binary_control, focal_card, guide, inject_css, not_applicable, turn_card
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
    dataset = read_gold(config.gold_path)
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
st.sidebar.caption(f"Partition: **{config.phase}** · Schema **{config.schema_version}**")
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

frame = dataset.frame(config.phase)
submitted_rows = storage.rows("utterance_annotations", coder)
submitted = {
    str(row["utterance_id"]): row
    for row in submitted_rows
    if row["partition"] == config.phase and row["status"] == "submitted"
}
dispute_rows = storage.rows("dispute_annotations", coder)
completed_disputes = {str(row["dispute_id"]) for row in dispute_rows if row["partition"] == config.phase}
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
        unit_ids = set(dataset.full_dispute(config.phase, dispute_id)["utterance_id"].astype(str))
        if unit_ids <= set(submitted) and dispute_id not in completed_disputes:
            ready_for_dispute.append(dispute_id)
    next_rows = frame[~frame["utterance_id"].astype(str).isin(submitted)]
    if ready_for_dispute:
        st.write(f"Next: complete the dispute-level decision for **{ready_for_dispute[0]}**.")
        if st.button("Complete dispute", type="primary"):
            st.session_state.page = "dispute"
            st.session_state.dispute_id = ready_for_dispute[0]
            st.session_state.timer_start = time.monotonic()
            st.session_state.opened_at = opened_at()
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
            st.session_state.timer_start = time.monotonic()
            st.session_state.opened_at = opened_at()
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
            st.session_state.timer_start = time.monotonic()
            st.session_state.opened_at = opened_at()
            st.rerun()
    st.stop()

if st.session_state.page == "dispute":
    st.title("Complete dispute-level coding")
    did = st.session_state.dispute_id
    full = dataset.full_dispute(config.phase, did)
    for _, turn in full.iterrows():
        turn_card(turn)
    st.subheader("Primary dispute object")
    for name, item in codebook.dispute_objects.items():
        with st.expander(name):
            st.write(item["Definition"])
            st.write(item["Dispute-level coding rule"])
    existing_rows = [
        item for item in dispute_rows if item["partition"] == config.phase and str(item["dispute_id"]) == did
    ]
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
                partition=config.phase,
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
                opened_at=st.session_state.opened_at,
                elapsed_wall_seconds=time.monotonic() - st.session_state.timer_start,
            )
            st.session_state.page = "home"
            st.rerun()
    if existing_rows:
        with st.expander("Dispute decision history"):
            history = [
                item
                for item in storage.rows("dispute_annotation_events", coder)
                if item["partition"] == config.phase and str(item["dispute_id"]) == did
            ]
            for event in history:
                st.write(f"Revision {event['revision_number']} · {event['event_type']} · {event['saved_at']}")
    st.stop()

uid = st.session_state.unit_id
matches = frame[frame["utterance_id"].astype(str) == uid]
if matches.empty:
    st.error("Selected utterance is not in the active partition.")
    st.stop()
row = matches.iloc[0]
did = str(row["dispute_id"])
order = int(row["utterance_order"])
prior = dataset.prior_context(config.phase, did, order)
current = storage.current_utterance(coder, config.phase, uid)
prior_annotations = {
    str(item["utterance_id"]): __import__("json").loads(item["payload_json"])
    for item in submitted_rows
    if item["partition"] == config.phase
    and item["status"] == "submitted"
    and str(item["dispute_id"]) == did
    and str(item["utterance_id"]) in set(prior["utterance_id"].astype(str))
}
context = ContextState(
    tuple(prior["utterance_id"].astype(str)),
    any(v.get("KS_present") == 1 for v in prior_annotations.values()),
    any(
        v.get("KI_propose_action") == 1 or v.get("KI_announce_enacted_action") == 1 for v in prior_annotations.values()
    ),
)
defaults = {} if not current else current["payload"]
if st.session_state.get("timer_uid") != uid:
    st.session_state.timer_uid = uid
    st.session_state.timer_start = time.monotonic()
    st.session_state.opened_at = opened_at()

st.progress(len(submitted) / max(1, len(frame)), text=f"{len(submitted)} of {len(frame)} utterances submitted")
focal_card(row)
left, right = st.columns([0.58, 0.42], gap="large")
with left:
    target = row.get("reply_to_utterance_id")
    if not pd.isna(target):
        direct = prior[prior["utterance_id"].astype(str) == str(target)]
        if not direct.empty:
            st.subheader("Direct reply target")
            turn_card(direct.iloc[0])
    relevant = prior[
        prior["utterance_id"]
        .astype(str)
        .isin([k for k, v in prior_annotations.items() if v.get("KS_present") == 1 or v.get("KI_present") == 1])
    ]
    if not relevant.empty:
        st.subheader("Relevant prior turns")
        st.caption(
            "Surfaced only because you previously coded these as KS or KI; this is not a machine recommendation."
        )
        for _, turn in relevant.iterrows():
            turn_card(turn, "Your earlier KS/KI coding")
    st.subheader("Conversation so far")
    older, recent = prior.iloc[:-4], prior.iloc[-4:]
    if not older.empty:
        with st.expander(f"Older history ({len(older)} turns)"):
            for _, turn in older.iterrows():
                turn_card(turn)
    for _, turn in recent.iterrows():
        turn_card(turn)
    if prior.empty:
        st.caption("No earlier turns. Future turns are never shown here.")

with right:
    values = dict(defaults)
    answered = set() if not current else set(current["answered_fields"])
    st.subheader("Coding")
    for name in ("KS_present", "KI_present", "C_interpersonal_hostility", "C_formal_escalation_signal"):
        value = binary_control(name, f"field_{name}_{uid}", values.get(name))
        values[name] = value
        if value is not None:
            answered.add(name)
        guide(name, codebook.fields[name])
    if values.get("KS_present") == 1:
        for name in (
            "KS_problem_claim_specified",
            "KS_evidence_present",
            "KS_acceptability_condition",
            "KS_derailment",
        ):
            value = binary_control(name, f"field_{name}_{uid}", values.get(name))
            values[name] = value
            if value is not None:
                answered.add(name)
            guide(name, codebook.fields[name])
        if context.earlier_ks:
            name = "KS_repetition_or_restaking"
            value = binary_control(name, f"field_{name}_{uid}", values.get(name))
            values[name] = value
            if value is not None:
                answered.add(name)
            guide(name, codebook.fields[name])
        else:
            not_applicable("KS_repetition_or_restaking")
        if values.get("KS_evidence_present") == 1:
            values["KS_evidence_type"] = st.multiselect(
                "KS_evidence_type",
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
                    st.caption(
                        f"Code when: {evidence_guide['Code when...']} Do not code when: {evidence_guide['Do not code when...']}"
                    )
            values["KS_warrant_explicit"] = st.radio(
                "KS_warrant_explicit",
                range(1, 6),
                index=(
                    values.get("KS_warrant_explicit") - 1 if values.get("KS_warrant_explicit") in range(1, 6) else None
                ),
                horizontal=True,
                key=f"warrant_{uid}",
            )
            if values["KS_warrant_explicit"] is not None:
                answered.add("KS_warrant_explicit")
            st.caption(codebook.fields["KS_warrant_explicit"].rule)
            guide("KS_warrant_explicit", codebook.fields["KS_warrant_explicit"])
    else:
        for name in (
            *(
                "KS_problem_claim_specified",
                "KS_evidence_present",
                "KS_acceptability_condition",
                "KS_derailment",
                "KS_repetition_or_restaking",
                "KS_evidence_type",
                "KS_warrant_explicit",
            ),
        ):
            not_applicable(name)
    if values.get("KI_present") == 1:
        for name in ("KI_propose_action", "KI_announce_enacted_action", "KI_solicit"):
            value = binary_control(name, f"field_{name}_{uid}", values.get(name))
            values[name] = value
            if value is not None:
                answered.add(name)
            guide(name, codebook.fields[name])
        if context.earlier_candidate:
            name = "KI_iterate_on_candidate_action"
            value = binary_control(name, f"field_{name}_{uid}", values.get(name))
            values[name] = value
            if value is not None:
                answered.add(name)
            guide(name, codebook.fields[name])
        else:
            not_applicable("KI_iterate_on_candidate_action")
        if context.earlier_ks:
            values["KI_prior_stake_reflection"] = st.radio(
                "KI_prior_stake_reflection",
                range(1, 6),
                index=(
                    values.get("KI_prior_stake_reflection") - 1
                    if values.get("KI_prior_stake_reflection") in range(1, 6)
                    else None
                ),
                horizontal=True,
                key=f"reflection_{uid}",
            )
            if values["KI_prior_stake_reflection"] is not None:
                answered.add("KI_prior_stake_reflection")
            st.caption(codebook.fields["KI_prior_stake_reflection"].rule)
            guide("KI_prior_stake_reflection", codebook.fields["KI_prior_stake_reflection"])
        else:
            not_applicable("KI_prior_stake_reflection")
    else:
        for name in (
            "KI_propose_action",
            "KI_announce_enacted_action",
            "KI_solicit",
            "KI_iterate_on_candidate_action",
            "KI_prior_stake_reflection",
        ):
            not_applicable(name)
    if context.earlier_candidate:
        feedback_options = {
            "No explicit feedback": None,
            "Accept": "accept",
            "Reject": "reject",
            "Mixed or conditional": "mixed_or_conditional",
        }
        reverse = {v: k for k, v in feedback_options.items()}
        existing = reverse.get(values.get("KI_explicit_feedback")) if "KI_explicit_feedback" in answered else None
        choice = st.radio(
            "KI_explicit_feedback",
            list(feedback_options),
            index=(list(feedback_options).index(existing) if existing else None),
            key=f"feedback_{uid}",
        )
        if choice is not None:
            values["KI_explicit_feedback"] = feedback_options[choice]
            answered.add("KI_explicit_feedback")
        guide("KI_explicit_feedback", codebook.fields["KI_explicit_feedback"])
    else:
        not_applicable("KI_explicit_feedback")
    st.subheader("Audit evidence")
    for name in ("KS_evidence_span", "KI_evidence_span", "control_evidence_span"):
        values[name] = st.text_area(name, value=values.get(name) or "", key=f"text_{name}_{uid}")
        if values[name].strip():
            answered.add(name)
    labels = {
        str(
            turn["utterance_id"]
        ): f"#{int(turn['utterance_order'])} — {turn['speaker_id']} — {str(turn['utterance_text'])[:55]}"
        for _, turn in prior.iterrows()
    }
    for name in ("KS_prior_utterance_ids", "KI_upstream_utterance_ids"):
        values[name] = st.multiselect(
            name, list(labels), default=values.get(name) or [], format_func=labels.get, key=f"ids_{name}_{uid}"
        )
        if values[name]:
            answered.add(name)
    values["coder_confidence"] = st.radio(
        "coder_confidence",
        range(1, 6),
        index=(values.get("coder_confidence") - 1 if values.get("coder_confidence") in range(1, 6) else None),
        horizontal=True,
        key=f"confidence_{uid}",
    )
    if values["coder_confidence"] is not None:
        answered.add("coder_confidence")
    values["review_flag"] = binary_control("review_flag", f"review_{uid}", values.get("review_flag"))
    if values["review_flag"] is not None:
        answered.add("review_flag")
    st.caption(
        f"A short justification is required when confidence ≤ {config.low_confidence_threshold} or review is Yes."
    )
    for name in ("short_justification", "coder_notes"):
        values[name] = st.text_area(name, value=values.get(name) or "", key=f"text_{name}_{uid}")
        if values[name].strip():
            answered.add(name)
    draft_col, submit_col = st.columns(2)
    if draft_col.button("Save draft", use_container_width=True):
        result = normalize_and_validate(
            values, answered, context, set(codebook.evidence_types), config.low_confidence_threshold, False
        )
        storage.save_utterance(
            coder=coder,
            partition=config.phase,
            utterance_id=uid,
            dispute_id=did,
            payload=result.payload,
            answered_fields=answered,
            submit=False,
            schema_version=config.schema_version,
            schema_hash=codebook.file_hash,
            opened_at=st.session_state.opened_at,
            elapsed_wall_seconds=time.monotonic() - st.session_state.timer_start,
        )
        st.success("Draft saved.")
    if submit_col.button("Submit and next", type="primary", use_container_width=True):
        result = normalize_and_validate(
            values, answered, context, set(codebook.evidence_types), config.low_confidence_threshold, True
        )
        if not result.valid:
            for name, message in result.errors.items():
                st.error(f"{name}: {message}")
        else:
            storage.save_utterance(
                coder=coder,
                partition=config.phase,
                utterance_id=uid,
                dispute_id=did,
                payload=result.payload,
                answered_fields=answered,
                submit=True,
                schema_version=config.schema_version,
                schema_hash=codebook.file_hash,
                opened_at=st.session_state.opened_at,
                elapsed_wall_seconds=time.monotonic() - st.session_state.timer_start,
            )
            full = dataset.full_dispute(config.phase, did)
            now_submitted = set(submitted) | {uid}
            if set(full["utterance_id"].astype(str)) <= now_submitted:
                st.session_state.page = "dispute"
                st.session_state.dispute_id = did
            else:
                nxt = full[~full["utterance_id"].astype(str).isin(now_submitted)].iloc[0]
                st.session_state.unit_id = str(nxt["utterance_id"])
            st.rerun()
    with st.expander("Revision history"):
        history = [
            r
            for r in storage.rows("utterance_annotation_events", coder)
            if str(r["utterance_id"]) == uid and r["partition"] == config.phase
        ]
        for event in history:
            st.write(f"Revision {event['revision_number']} · {event['event_type']} · {event['saved_at']}")
