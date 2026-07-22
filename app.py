"""Streamlit entry point for local WikiDisputes annotation."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import time

import pandas as pd
import streamlit as st

from wikidisputes_ui.codebook import file_fingerprint, load_codebook, schema_id
from wikidisputes_ui.config import load_config
from wikidisputes_ui.export import build_export, safe_export_name
from wikidisputes_ui.ingest import article_title, read_gold
from wikidisputes_ui.models import BASE_BINARY, ContextState, applicable_fields, normalize_and_validate
from wikidisputes_ui.navigation import (
    Destination,
    dispute_destination,
    dispute_progress,
    is_reviewable_without_gap,
    previous_utterance,
)
from wikidisputes_ui.storage import SchemaDriftError, Storage
from wikidisputes_ui.ui_components import (
    TaskCounter,
    binary_control,
    binary_task,
    discussion_heading,
    focal_card,
    inject_css,
    prior_comment,
    source_details,
    task_heading,
    task_intro,
    turn_card,
)
from wikidisputes_ui.validation import render_report, validate_inputs

st.set_page_config(page_title="WikiDisputes annotation", page_icon="✎", layout="wide")
inject_css()

config_path = os.environ.get("WIKIDISPUTES_CONFIG", "config/project.toml")
initial_config = load_config(config_path)


def cache_fingerprint(path):
    return file_fingerprint(path) if path.is_file() else f"missing:{path}"


def opened_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@st.cache_resource
def resources(config_file: str, codebook_fingerprint: str, gold_fingerprint: str):
    del codebook_fingerprint, gold_fingerprint  # Values are cache keys; loading below remains authoritative.
    config = load_config(config_file)
    qc = validate_inputs(config)
    if qc.blocking:
        return config, qc, None, None, None
    codebook = load_codebook(config.codebook_path, config.schema_sheet)
    dataset = read_gold(config.gold_path, config.annotation_sheet)
    storage = Storage(config.database_path)
    storage.register_schema(
        schema_id(codebook.file_hash), codebook.file_hash, codebook.source_filename, config.schema_locked
    )
    return config, qc, codebook, dataset, storage


try:
    config, qc, codebook, dataset, storage = resources(
        str(config_path),
        cache_fingerprint(initial_config.codebook_path),
        cache_fingerprint(initial_config.gold_path),
    )
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
active_schema_id = schema_id(codebook.file_hash)
if coder is None:
    st.title("WikiDisputes annotation")
    st.info(
        "Your coder ID identifies your local work; it is not authentication. Use a pseudonymous ID assigned for this study."
    )
    with st.form("coder_entry"):
        coder_id = st.text_input("Coder ID", placeholder="e.g. coder_01")
        if st.form_submit_button("Continue", type="primary"):
            try:
                storage.set_active_coder(coder_id.strip())
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.stop()

st.sidebar.caption(f"Coder: **{coder}**")
st.sidebar.caption(f"Schema: **{active_schema_id}**")
if st.sidebar.button("Switch coder"):
    st.session_state.confirm_switch = True
if st.session_state.get("confirm_switch"):
    st.sidebar.warning("Switching changes whose private annotations are shown.")
    if st.sidebar.button("Confirm switch"):
        with storage.connect() as db:
            db.execute("UPDATE coders SET active=0")
        st.session_state.clear()
        st.rerun()

export_data = build_export(storage, dataset, coder, active_schema_id, codebook.file_hash, tuple(codebook.fields))
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
all_utterance_rows = storage.rows("utterance_annotations", coder)
submitted_rows = [row for row in all_utterance_rows if row["schema_hash"] == codebook.file_hash]
historical_count = sum(row["schema_hash"] != codebook.file_hash for row in all_utterance_rows)
if historical_count:
    st.sidebar.caption(
        f"{historical_count} annotation projection(s) use earlier codebooks. They remain in the database backup but "
        "are excluded from this schema-locked Excel export."
    )
submitted = {
    str(row["utterance_id"]): row
    for row in submitted_rows
    if row["status"] == "submitted" and str(row["utterance_id"]) in annotatable_ids
}
dispute_rows = [row for row in storage.rows("dispute_annotations", coder) if row["schema_hash"] == codebook.file_hash]
completed_disputes = {str(row["dispute_id"]) for row in dispute_rows if str(row["dispute_id"]) in dispute_ids}
review_count = sum(bool(__import__("json").loads(row["payload_json"]).get("review_flag")) for row in submitted.values())


def apply_destination(destination: Destination) -> None:
    """Update only destination-specific session state."""
    st.session_state.page = destination.page
    if destination.unit_id is not None:
        st.session_state.unit_id = destination.unit_id
    if destination.dispute_id is not None:
        st.session_state.dispute_id = destination.dispute_id


def active_submitted_ids() -> set[str]:
    return {
        str(item["utterance_id"])
        for item in storage.rows("utterance_annotations", coder)
        if item["schema_hash"] == codebook.file_hash and item["status"] == "submitted"
    }


def dispute_navigation_choices() -> dict[str, str]:
    choices = {}
    submitted_ids = set(submitted)
    for dispute_id in frame["dispute_id"].drop_duplicates():
        dispute_id = str(dispute_id)
        turns = dataset.annotatable_in_dispute(dispute_id)
        first = turns.iloc[0]
        done, total = dispute_progress(dataset, dispute_id, submitted_ids)
        status = "complete" if dispute_id in completed_disputes else f"{done}/{total} utterances"
        choices[f"{article_title(first)} · {dispute_id} · {status}"] = dispute_id
    return choices


if "page" not in st.session_state:
    st.session_state.page = "home"
if st.session_state.get("navigation_notice"):
    st.success(st.session_state.pop("navigation_notice"))

if st.session_state.page == "home":
    st.title("Annotation workspace")
    cols = st.columns(4)
    cols[0].metric("Utterances", f"{len(submitted)} / {len(frame)}")
    cols[1].metric("Disputes", f"{len(completed_disputes)} / {frame['dispute_id'].nunique()}")
    cols[2].metric("Progress", f"{100 * len(submitted) / max(1, len(frame)):.1f}%")
    cols[3].metric("Review flags", review_count)
    with st.container(border=True):
        st.markdown("**Open a dispute**")
        navigation_choices = dispute_navigation_choices()
        selected_dispute_label = st.selectbox(
            "Dispute",
            list(navigation_choices),
            index=None,
            placeholder="Choose an article and dispute",
            key="workspace_dispute_selector",
        )
        if selected_dispute_label and st.button("Open dispute →", key="workspace_open_dispute"):
            destination = dispute_destination(
                dataset,
                navigation_choices[selected_dispute_label],
                set(submitted),
                completed_disputes,
            )
            apply_destination(destination)
            st.rerun()
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
        choices = {}
        for uid, submitted_row in submitted.items():
            source = frame[frame["utterance_id"].astype(str) == uid].iloc[0]
            if is_reviewable_without_gap(
                dataset, str(source["dispute_id"]), int(source["utterance_order"]), set(submitted)
            ):
                choices[
                    f"{article_title(source)} · #{int(source['utterance_order'])} · revision "
                    f"{submitted_row['revision_number']}"
                ] = uid
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

    pending_dispute_navigation = st.session_state.get("pending_dispute_navigation")
    if pending_dispute_navigation:
        st.warning("This dispute decision has unsaved changes. Discard them and navigate, or remain here.")
        discard_col, remain_col = st.columns(2)
        if discard_col.button("Discard changes and continue", type="primary"):
            destination = Destination(**pending_dispute_navigation)
            del st.session_state.pending_dispute_navigation
            apply_destination(destination)
            st.rerun()
        if remain_col.button("Remain on dispute"):
            del st.session_state.pending_dispute_navigation
            st.rerun()

    dispute_navigation_request = None
    with st.container(border=True):
        st.markdown("**Navigation**")
        workspace_col, utterance_col = st.columns(2)
        if workspace_col.button("← Workspace", use_container_width=True, key="dispute_workspace"):
            dispute_navigation_request = Destination("home")
        if utterance_col.button("Review utterances →", use_container_width=True, key="dispute_review_turns"):
            turns = dataset.annotatable_in_dispute(did)
            dispute_navigation_request = Destination("utterance", str(turns.iloc[0]["utterance_id"]), did)
        navigation_choices = dispute_navigation_choices()
        selected_dispute_label = st.selectbox(
            "Move to another dispute",
            list(navigation_choices),
            index=None,
            placeholder="Choose an article and dispute",
            key="dispute_screen_selector",
        )
        if selected_dispute_label and st.button("Open selected dispute →", key="dispute_screen_open"):
            dispute_navigation_request = dispute_destination(
                dataset,
                navigation_choices[selected_dispute_label],
                set(submitted),
                completed_disputes,
            )

    full = dataset.full_dispute(did)
    for _, turn in full.iterrows():
        turn_card(turn)
    existing_rows = [item for item in dispute_rows if str(item["dispute_id"]) == did]
    existing = {} if not existing_rows else __import__("json").loads(existing_rows[0]["payload_json"])
    tasks = TaskCounter()
    object_options = sorted(codebook.dispute_objects)
    object_definitions = {name: codebook.dispute_objects[name]["Definition"] for name in object_options}
    task_intro(
        tasks,
        "What is the primary dispute object?",
        codebook.fields["C_primary_dispute_object"],
        controlled_values=object_definitions,
    )
    choice = st.radio(
        "Primary dispute object",
        object_options,
        index=object_options.index(existing["C_primary_dispute_object"])
        if existing.get("C_primary_dispute_object") in object_options
        else None,
        label_visibility="collapsed",
    )
    task_intro(tasks, "How confident are you in the dispute-level decision?", description="Choose from 1 to 5.")
    confidence = st.radio(
        "Dispute confidence",
        range(1, 6),
        index=existing["coder_confidence"] - 1 if existing.get("coder_confidence") in range(1, 6) else None,
        horizontal=True,
        label_visibility="collapsed",
    )
    task_intro(tasks, "Should this dispute-level decision be flagged for review?", description="Choose No or Yes.")
    review = binary_control(
        "Dispute review flag",
        f"dispute_review_{did}",
        existing.get("review_flag"),
        label_visibility="collapsed",
    )
    task_heading(tasks, "Add an optional note")
    dispute_note_key = f"dispute_coder_notes_{did}"
    if dispute_note_key not in st.session_state:
        st.session_state[dispute_note_key] = existing.get("coder_notes") or existing.get("short_justification") or ""
    note = st.text_input(
        "Optional coder note",
        key=dispute_note_key,
        placeholder="Write an optional note here",
        label_visibility="collapsed",
    )
    current_dispute_values = {
        "C_primary_dispute_object": choice,
        "coder_confidence": confidence,
        "review_flag": review,
        "short_justification": None,
        "coder_notes": note or None,
    }
    dispute_dirty = any(current_dispute_values.get(name) != existing.get(name) for name in current_dispute_values)
    if dispute_navigation_request:
        if dispute_dirty:
            st.session_state.pending_dispute_navigation = {
                "page": dispute_navigation_request.page,
                "unit_id": dispute_navigation_request.unit_id,
                "dispute_id": dispute_navigation_request.dispute_id,
            }
            st.rerun()
        else:
            apply_destination(dispute_navigation_request)
            st.rerun()

    if st.button("Complete dispute", type="primary"):
        errors = []
        if choice is None:
            errors.append("Choose exactly one primary dispute object.")
        if confidence is None:
            errors.append("Choose dispute confidence.")
        if review is None:
            errors.append("Choose a dispute review flag.")
        if errors:
            for error in errors:
                st.error(error)
        else:
            storage.save_dispute(
                coder=coder,
                dispute_id=did,
                payload=current_dispute_values,
                answered_fields={"C_primary_dispute_object", "coder_confidence", "review_flag"},
                schema_version=active_schema_id,
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
if current and current["schema_hash"] != codebook.file_hash:
    current = None
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
    any(v.get("KI_present") == 1 for v in prior_annotations.values()),
)
defaults = {} if not current else current["payload"]
if st.session_state.get("timer_uid") != uid:
    st.session_state.timer_uid = uid
    st.session_state.utterance_timer_start = time.monotonic()
    st.session_state.utterance_opened_at = opened_at()

utterance_navigation_request: tuple[str, str | None] | None = None
with st.container(border=True):
    st.markdown("**Navigation**")
    previous_id = previous_utterance(dataset, did, order)
    previous_col, workspace_col = st.columns(2)
    if previous_col.button(
        "← Previous utterance",
        disabled=previous_id is None,
        use_container_width=True,
        key=f"previous_{uid}",
    ):
        utterance_navigation_request = ("utterance", previous_id)
    if workspace_col.button("← Workspace", use_container_width=True, key=f"workspace_{uid}"):
        utterance_navigation_request = ("home", None)
    navigation_choices = dispute_navigation_choices()
    selected_dispute_label = st.selectbox(
        "Move to another dispute",
        list(navigation_choices),
        index=None,
        placeholder="Choose an article and dispute",
        key=f"utterance_dispute_selector_{uid}",
    )
    open_col, decision_col = st.columns(2)
    if selected_dispute_label and open_col.button("Open selected dispute →", key=f"utterance_open_dispute_{uid}"):
        utterance_navigation_request = ("dispute_choice", navigation_choices[selected_dispute_label])
    if did in completed_disputes and decision_col.button(
        "Review dispute decision →", key=f"utterance_review_dispute_{uid}"
    ):
        utterance_navigation_request = ("dispute_decision", did)

st.progress(len(submitted) / max(1, len(frame)), text=f"{len(submitted)} of {len(frame)} utterances submitted")

gateway_labels = {
    "KS_present": "Knowledge staking (KS)",
    "KI_present": "Knowledge integration (KI)",
    "C_off_topic_shift": "Off-topic shift",
    "C_interpersonal_attack_or_disrespect": "Interpersonal attack or disrespect",
    "C_formal_governance_action": "Formal governance action",
}
field_labels = {
    "KS_claim_target_specified": "Makes at least one specific claim about a target issue",
    "KS_evidence_present": "Shares supporting evidence",
    "KS_warrant_reasoning": "Develops a line of reasoning",
    "KS_unelaborated_restaking": "Unelaborated restaking of earlier knowledge",
    "KI_propose_edit": "Proposes an edit",
    "KI_report_enacted_edit": "Reports an enacted edit",
    "KI_solicit_feedback": "Solicits feedback",
    "KI_iterate": "Develops an earlier proposed or enacted edit",
    "KI_prior_knowledge": "Uses previously staked knowledge",
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
    direct_id = None if direct.empty or direct.iloc[0].get("utterance_role") != "utterance" else str(target)

    def render_prior(turn):
        turn_id = str(turn["utterance_id"])
        prior_values = prior_annotations.get(turn_id, {})
        badges = []
        if turn_id == direct_id:
            badges.append("Reply target")
        if prior_values.get("KS_present") == 1:
            badges.append("Earlier KS")
        if prior_values.get("KI_present") == 1:
            badges.append("Earlier KI")
        prior_comment(turn, tuple(badges))

    for _, turn in prior_turns.iterrows():
        render_prior(turn)
    if not pd.isna(target) and direct.empty:
        st.info("The reply target is not available within the strict prior-context boundary; its text is not shown.")

with coding.container(height=700, border=False, key="coding_pane"):
    values = dict(defaults)
    answered = set() if not current else set(current["answered_fields"])
    tasks = TaskCounter()

    def set_binary(name: str, label: str | None = None, key_prefix: str = "field") -> None:
        visible_label = label or field_labels.get(name, name)
        value = binary_task(
            tasks,
            visible_label,
            codebook.fields[name],
            f"{key_prefix}_{name}_{uid}",
            values.get(name),
        )
        values[name] = value
        if value is not None:
            answered.add(name)

    def save_result(result, submit: bool):
        stored_answered = answered & applicable_fields(result.payload, context, config.low_confidence_threshold)
        return storage.save_utterance(
            coder=coder,
            utterance_id=uid,
            dispute_id=did,
            payload=result.payload,
            answered_fields=stored_answered,
            submit=submit,
            schema_version=active_schema_id,
            schema_hash=codebook.file_hash,
            opened_at=st.session_state.utterance_opened_at,
            elapsed_wall_seconds=time.monotonic() - st.session_state.utterance_timer_start,
        )

    def render_optional_note() -> None:
        values["short_justification"] = None
        task_heading(tasks, "Add an optional note")
        note_key = f"text_coder_notes_{uid}"
        if note_key not in st.session_state:
            st.session_state[note_key] = values.get("coder_notes") or defaults.get("short_justification") or ""
        values["coder_notes"] = st.text_input(
            "Optional coder note",
            key=note_key,
            placeholder="Write an optional note here",
            label_visibility="collapsed",
        )
        if values["coder_notes"].strip():
            answered.add("coder_notes")
            st.caption("Coder note entered; save the draft or submit to record it.")

    if st.session_state.annotation_stage == 1:
        st.subheader("Stage 1 · Identify what is present")
        for name in BASE_BINARY[:2]:
            set_binary(name, gateway_labels[name], "gateway")
        st.markdown("#### Controls")
        for name in BASE_BINARY[2:]:
            set_binary(name, gateway_labels[name], "gateway")
        render_optional_note()
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
        st.subheader("Stage 2 · Code applicable details")
        summary = " · ".join(
            f"{label}: {'Yes' if values.get(name) == 1 else 'No'}"
            for name, label in (
                ("KS_present", "KS"),
                ("KI_present", "KI"),
                ("C_off_topic_shift", "Off-topic"),
                ("C_interpersonal_attack_or_disrespect", "Attack/disrespect"),
                ("C_formal_governance_action", "Governance"),
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
                "KS_claim_target_specified",
                "KS_evidence_present",
                "KS_warrant_reasoning",
            ):
                set_binary(name)
            if context.earlier_ks:
                set_binary("KS_unelaborated_restaking")
                if values.get("KS_unelaborated_restaking") == 1:
                    task_intro(
                        tasks,
                        "Which earlier KS utterances are being restated? (optional)",
                        description="Select one or more strictly earlier substantive utterances.",
                    )
                    values["KS_prior_utterance_ids"] = st.multiselect(
                        "Earlier KS utterances (optional)",
                        list(labels),
                        default=values.get("KS_prior_utterance_ids") or [],
                        format_func=labels.get,
                        key=f"ids_KS_prior_utterance_ids_{uid}",
                        label_visibility="collapsed",
                    )
                    if values["KS_prior_utterance_ids"]:
                        answered.add("KS_prior_utterance_ids")
            if values.get("KS_evidence_present") == 1:
                evidence_definitions = {
                    name: evidence_guide["Definition"] for name, evidence_guide in codebook.evidence_types.items()
                }
                task_intro(
                    tasks,
                    "Which evidence type or types are present?",
                    codebook.fields["KS_evidence_type"],
                    controlled_values=evidence_definitions,
                    collapse_controlled_values=True,
                )
                values["KS_evidence_type"] = st.multiselect(
                    "Evidence types present",
                    sorted(codebook.evidence_types),
                    default=values.get("KS_evidence_type") or [],
                    key=f"ev_{uid}",
                    label_visibility="collapsed",
                )
                if values["KS_evidence_type"]:
                    answered.add("KS_evidence_type")
            if values.get("KS_claim_target_specified") == 1 and (
                values.get("KS_evidence_present") == 1 or values.get("KS_warrant_reasoning") == 1
            ):
                strength_options = {"0 — Unconvincing": 0, "1 — Partly convincing": 1, "2 — Convincing": 2}
                current_strength = next(
                    (label for label, score in strength_options.items() if score == values.get("KS_argument_strength")),
                    None,
                )
                task_intro(tasks, "How strong is the argument?", codebook.fields["KS_argument_strength"])
                strength_choice = st.radio(
                    "Argument strength",
                    list(strength_options),
                    index=list(strength_options).index(current_strength) if current_strength else None,
                    horizontal=True,
                    key=f"argument_strength_{uid}",
                    label_visibility="collapsed",
                )
                if strength_choice is not None:
                    values["KS_argument_strength"] = strength_options[strength_choice]
                    answered.add("KS_argument_strength")
        if values.get("KI_present") == 1:
            st.markdown("#### Knowledge integration details")
            for name in ("KI_propose_edit", "KI_report_enacted_edit", "KI_solicit_feedback"):
                set_binary(name)
            if context.earlier_ki_attempt:
                set_binary("KI_iterate")
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
                task_intro(
                    tasks,
                    "What explicit feedback is given on the earlier proposed or enacted edit?",
                    codebook.fields["KI_explicit_feedback"],
                )
                choice = st.radio(
                    "Explicit feedback on an earlier proposed or enacted edit",
                    list(feedback_options),
                    index=list(feedback_options).index(existing) if existing else None,
                    key=f"feedback_{uid}",
                    label_visibility="collapsed",
                )
                if choice is not None:
                    values["KI_explicit_feedback"] = feedback_options[choice]
                    answered.add("KI_explicit_feedback")
            if context.earlier_ks:
                set_binary("KI_prior_knowledge")
            needs_upstream = (
                values.get("KI_iterate") == 1
                or values.get("KI_explicit_feedback") in {"accept", "reject", "mixed_or_conditional"}
                or values.get("KI_prior_knowledge") == 1
            )
            if needs_upstream:
                task_intro(
                    tasks,
                    "Which earlier utterances are upstream? (optional)",
                    description="Select strictly earlier utterances used for iteration, feedback, or prior knowledge.",
                )
                values["KI_upstream_utterance_ids"] = st.multiselect(
                    "Upstream utterances (optional)",
                    list(labels),
                    default=values.get("KI_upstream_utterance_ids") or [],
                    format_func=labels.get,
                    key=f"ids_KI_upstream_utterance_ids_{uid}",
                    label_visibility="collapsed",
                )
                if values["KI_upstream_utterance_ids"]:
                    answered.add("KI_upstream_utterance_ids")
            task_intro(
                tasks,
                "Record the KI evidence span (optional)",
                description="Copy the focal text that supports the KI coding, if useful for audit.",
            )
            values["KI_evidence_span"] = st.text_area(
                "KI evidence span",
                value=values.get("KI_evidence_span") or "",
                key=f"text_KI_evidence_span_{uid}",
                label_visibility="collapsed",
            )
            if values["KI_evidence_span"].strip():
                answered.add("KI_evidence_span")

        if any(values.get(name) == 1 for name in BASE_BINARY[2:]):
            st.markdown("#### Control evidence (optional)")
            task_intro(
                tasks,
                "Record the control evidence span (optional)",
                description="Copy the focal text that supports any positive control coding, if useful for audit.",
            )
            values["control_evidence_span"] = st.text_area(
                "Control evidence span",
                value=values.get("control_evidence_span") or "",
                key=f"text_control_evidence_span_{uid}",
                label_visibility="collapsed",
            )
            if values["control_evidence_span"].strip():
                answered.add("control_evidence_span")
        if not any(values.get(name) == 1 for name in BASE_BINARY):
            st.info("No detailed fields apply. Complete confidence and review below.")

        st.markdown("#### Confidence and review")
        task_intro(tasks, "How confident are you in this utterance annotation?", description="Choose from 1 to 5.")
        values["coder_confidence"] = st.radio(
            "Coder confidence",
            range(1, 6),
            index=values.get("coder_confidence") - 1 if values.get("coder_confidence") in range(1, 6) else None,
            horizontal=True,
            key=f"confidence_{uid}",
            label_visibility="collapsed",
        )
        if values["coder_confidence"] is not None:
            answered.add("coder_confidence")
        task_intro(tasks, "Should this utterance be flagged for review?", description="Choose No or Yes.")
        values["review_flag"] = binary_control(
            "Flag for review",
            f"review_{uid}",
            values.get("review_flag"),
            label_visibility="collapsed",
        )
        if values["review_flag"] is not None:
            answered.add("review_flag")
        render_optional_note()
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

    if utterance_navigation_request:
        result = normalize_and_validate(
            values,
            answered,
            context,
            set(codebook.evidence_types),
            config.low_confidence_threshold,
            False,
        )
        event = "unchanged"
        if answered or current is not None:
            event, _ = save_result(result, False)
        fresh_submitted = active_submitted_ids()
        request_kind, request_value = utterance_navigation_request
        if request_kind == "utterance":
            destination = Destination("utterance", request_value, did)
        elif request_kind in {"dispute_choice", "dispute_decision"}:
            destination = dispute_destination(dataset, str(request_value), fresh_submitted, completed_disputes)
        else:
            destination = Destination("home")
        if event != "unchanged":
            st.session_state.navigation_notice = "Your current answers were saved as a draft before navigation."
        apply_destination(destination)
        st.rerun()
