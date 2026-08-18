"""Streamlit composition for the simplified WikiDisputes workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time

import streamlit as st

from wikidisputes_ui.codebook import file_fingerprint, load_codebook, schema_id
from wikidisputes_ui.config import load_config
from wikidisputes_ui.export import build_export, safe_export_name
from wikidisputes_ui.ingest import article_title, read_gold
from wikidisputes_ui.models import BASE_BINARY, KI_FIELDS, KS_FIELDS, applicable_fields, normalize_and_validate
from wikidisputes_ui.navigation import dispute_destination, dispute_progress, previous_utterance
from wikidisputes_ui.storage import Storage
from wikidisputes_ui.ui_components import (
    TaskCounter,
    binary_task,
    focal_card,
    inject_css,
    prior_comment,
    source_details,
    task_heading,
    task_intro,
)
from wikidisputes_ui.validation import render_report, validate_inputs

st.set_page_config(page_title="WikiDisputes annotation", page_icon="✎", layout="wide")
inject_css()
config_path = os.environ.get("WIKIDISPUTES_CONFIG", "config/project.toml")
initial_config = load_config(config_path)


def opened_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@st.cache_resource
def resources(config_file: str, codebook_hash: str, gold_hash: str):
    del codebook_hash, gold_hash
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
        str(config_path), file_fingerprint(initial_config.codebook_path), file_fingerprint(initial_config.gold_path)
    )
except Exception as exc:
    st.error(f"Startup failed: {exc}")
    st.stop()
if qc.blocking:
    st.title("Input quality check blocked annotation")
    st.markdown(render_report(qc, config))
    st.stop()

coder = storage.active_coder()
active_schema_id = schema_id(codebook.file_hash)
if coder is None:
    st.title("WikiDisputes annotation")
    st.info("Enter the pseudonymous coder ID assigned for this study.")
    with st.form("coder_entry"):
        coder_id = st.text_input("Coder ID", placeholder="e.g. coder_01")
        if st.form_submit_button("Continue", type="primary"):
            try:
                storage.set_active_coder(coder_id.strip())
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.stop()

frame = dataset.annotatable_rows
all_ids = set(frame["utterance_id"].astype(str))
current_rows = [r for r in storage.rows("utterance_annotations", coder) if r["schema_hash"] == codebook.file_hash]
submitted = {
    str(r["utterance_id"]): r for r in current_rows if r["status"] == "submitted" and str(r["utterance_id"]) in all_ids
}
dispute_rows = [r for r in storage.rows("dispute_annotations", coder) if r["schema_hash"] == codebook.file_hash]
completed_disputes = {str(r["dispute_id"]) for r in dispute_rows}

st.sidebar.caption(f"Coder: **{coder}**")
st.sidebar.caption(f"Schema: **{active_schema_id}**")
st.sidebar.download_button(
    "Export my annotations",
    build_export(storage, dataset, coder, active_schema_id, codebook.file_hash, tuple(codebook.fields)),
    safe_export_name(coder),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
if st.sidebar.button("Switch coder"):
    with storage.connect() as db:
        db.execute("UPDATE coders SET active=0")
    st.session_state.clear()
    st.rerun()


def go(page: str, *, uid: str | None = None, did: str | None = None) -> None:
    st.session_state.page = page
    if uid is not None:
        st.session_state.unit_id = uid
    if did is not None:
        st.session_state.dispute_id = did


def dispute_choices() -> dict[str, str]:
    choices = {}
    for did in frame["dispute_id"].drop_duplicates().astype(str):
        turns = dataset.annotatable_in_dispute(did)
        done, total = dispute_progress(dataset, did, set(submitted))
        choices[f"{article_title(turns.iloc[0])} · {did} · {done}/{total}"] = did
    return choices


def utterance_choices(dispute_id: str) -> dict[str, str]:
    choices = {}
    for _, turn in dataset.annotatable_in_dispute(dispute_id).iterrows():
        uid = str(turn["utterance_id"])
        status = "Submitted" if uid in submitted else "Not submitted"
        text = " ".join(str(turn["utterance_text"]).split())
        preview = text if len(text) <= 90 else f"{text[:87]}…"
        label = f"#{int(turn['utterance_order'])} · {turn['speaker_id']} · {status} · {preview} · {uid}"
        choices[label] = uid
    return choices


def focal_reply_description(dispute_id: str, source_row) -> str | None:
    raw_target = source_row.get("reply_to_utterance_id")
    target_id = "" if raw_target is None else str(raw_target).strip()
    if target_id.casefold() in {"", "nan", "<na>", "none"}:
        return None
    dispute = dataset.full_dispute(dispute_id)
    matches = dispute[dispute["utterance_id"].astype(str) == target_id]
    if matches.empty:
        return f"Replies to utterance ID {target_id} (target unavailable)"
    target = matches.iloc[0]
    raw_speaker = target.get("speaker_id")
    speaker = "" if raw_speaker is None else str(raw_speaker).strip()
    if speaker.casefold() in {"", "nan", "<na>", "none"}:
        speaker = "unknown speaker"
    return f"Replies to #{int(target['utterance_order'])} · {speaker} · ID {target_id}"


if "page" not in st.session_state:
    st.session_state.page = "home"

if st.session_state.page == "home":
    st.title("Annotation workspace")
    st.metric("Utterances submitted", f"{len(submitted)} / {len(frame)}")
    choices = dispute_choices()
    selected = st.selectbox("Article / dispute", list(choices), index=None, placeholder="Choose an article and dispute")
    selected_utterance = None
    selected_utterances = {}
    if selected:
        selected_utterances = utterance_choices(choices[selected])
        selected_utterance = st.selectbox(
            "Utterance",
            list(selected_utterances),
            index=None,
            placeholder="Choose a specific utterance",
        )
        if selected_utterance and st.button("Open selected utterance →", type="primary"):
            go("utterance", uid=selected_utterances[selected_utterance], did=choices[selected])
            st.rerun()
    if selected and st.button("Open dispute →", type="primary"):
        destination = dispute_destination(dataset, choices[selected], set(submitted), completed_disputes)
        go(destination.page, uid=destination.unit_id, did=destination.dispute_id or choices[selected])
        st.rerun()
    next_rows = frame[~frame["utterance_id"].astype(str).isin(submitted)]
    if not next_rows.empty and st.button("Resume annotation", type="primary"):
        row = next_rows.iloc[0]
        go("utterance", uid=str(row["utterance_id"]), did=str(row["dispute_id"]))
        st.rerun()
    st.stop()

if st.session_state.page == "dispute":
    did = str(st.session_state.dispute_id)
    required_ids = set(dataset.annotatable_in_dispute(did)["utterance_id"].astype(str))
    if not required_ids <= set(submitted):
        st.error("Submit every substantive utterance before completing the dispute-level decision.")
        pending = dataset.annotatable_in_dispute(did)
        pending = pending[~pending["utterance_id"].astype(str).isin(submitted)]
        if st.button("Return to next utterance", type="primary"):
            go("utterance", uid=str(pending.iloc[0]["utterance_id"]), did=did)
            st.rerun()
        st.stop()
    st.title("Final dispute decision")
    for _, turn in dataset.full_dispute(did).iterrows():
        prior_comment(turn, (f"#{int(turn['utterance_order'])}",))
    existing_row = next((r for r in dispute_rows if str(r["dispute_id"]) == did), None)
    existing = {} if existing_row is None else json.loads(existing_row["payload_json"])
    tasks = TaskCounter()
    task_intro(
        tasks,
        "Which article issue mainly organizes this dispute?",
        codebook.fields["C_primary_dispute_object"],
        controlled_values=codebook.dispute_objects,
    )
    options = list(codebook.dispute_objects)
    choice = st.radio(
        "C_primary_dispute_object",
        options,
        index=options.index(existing["C_primary_dispute_object"])
        if existing.get("C_primary_dispute_object") in options
        else None,
        format_func=lambda value: value.replace("_", " ").capitalize(),
    )
    if st.button("Complete dispute", type="primary"):
        if choice is None:
            st.error("Choose exactly one article issue.")
        else:
            storage.save_dispute(
                coder=coder,
                dispute_id=did,
                payload={"C_primary_dispute_object": choice},
                answered_fields={"C_primary_dispute_object"},
                schema_version=active_schema_id,
                schema_hash=codebook.file_hash,
                opened_at=opened_at(),
                elapsed_wall_seconds=0,
            )
            go("home")
            st.rerun()
    st.stop()

uid = str(st.session_state.unit_id)
matches = frame[frame["utterance_id"].astype(str) == uid]
if matches.empty:
    st.error("Selected utterance is not annotatable.")
    st.stop()
row = matches.iloc[0]
did, order = str(row["dispute_id"]), int(row["utterance_order"])
prior = dataset.displayable_prior_context(did, order)
current = storage.current_utterance(coder, uid)
if current and current["schema_hash"] != codebook.file_hash:
    current = None
defaults = {} if current is None else current["payload"]
if st.session_state.get("timer_uid") != uid:
    st.session_state.timer_uid = uid
    st.session_state.utterance_timer_start = time.monotonic()
    st.session_state.utterance_opened_at = opened_at()

st.title(article_title(row))
st.caption(f"Dispute {did} · Utterance #{order} · ID {uid}")
with st.container(border=True):
    left, right = st.columns(2)
    previous = previous_utterance(dataset, did, order)
    if left.button("← Previous utterance", disabled=previous is None):
        go("utterance", uid=previous, did=did)
        st.rerun()
    if right.button("← Workspace"):
        go("home")
        st.rerun()
    navigation_choices = dispute_choices()
    current_dispute_label = next(label for label, value in navigation_choices.items() if value == did)
    selected_dispute_label = st.selectbox(
        "Navigate to article / dispute",
        list(navigation_choices),
        index=list(navigation_choices).index(current_dispute_label),
        key=f"annotation_dispute_navigation_{uid}",
    )
    navigation_did = navigation_choices[selected_dispute_label]
    navigation_utterances = utterance_choices(navigation_did)
    selected_utterance_label = st.selectbox(
        "Navigate to utterance",
        list(navigation_utterances),
        index=None,
        placeholder="Choose a specific utterance",
        key=f"annotation_utterance_navigation_{uid}",
    )
    if selected_utterance_label and st.button("Go to selected utterance →"):
        go("utterance", uid=navigation_utterances[selected_utterance_label], did=navigation_did)
        st.rerun()

st.progress(len(submitted) / max(1, len(frame)), text=f"{len(submitted)} of {len(frame)} utterances submitted")
reading, coding = st.columns([0.56, 0.44], gap="large")
with reading.container(height=650, border=False, key="utterance_reading_pane"):
    focal_card(row, focal_reply_description(did, row))
    source_details(row)
    st.subheader("Earlier conversation")
    if prior.empty:
        st.caption("No earlier conversation. Future turns are never shown here.")
    for _, turn in prior.iterrows():
        badges = (f"#{int(turn['utterance_order'])}",)
        if turn["utterance_role"] == "context":
            badges += ("Context — not annotated",)
        prior_comment(turn, badges)

PROMPTS = {
    "KS_present": "Does this utterance state or challenge knowledge about the article or dispute?",
    "KS_claim_present": "Does it make a substantive claim?",
    "KS_evidence_reference": "Does it directly refer to evidence or another supporting basis?",
    "KS_reasoning": "Does it connect evidence or a premise to a conclusion?",
    "KS_restaking": "Does it repeat an earlier claim or objection without adding evidence or reasoning?",
    "KI_present": "Does this utterance propose, report, or refine an article edit?",
    "KI_solicit_feedback": "Does it ask others to assess, revise, or accept that edit?",
    "KI_compromise_position": "Does the edit visibly accommodate at least two positions or concerns?",
    "C_off_topic_shift": "Does this shift away from the article dispute?",
    "C_interpersonal_attack_or_disrespect": "Does this attack or disrespect another contributor?",
    "C_formal_governance_action": "Does this invoke or threaten a formal governance action?",
}
with coding.container(height=430, border=False, key="utterance_coding_pane"):
    values = dict(defaults)
    answered = set() if current is None else set(current["answered_fields"])
    tasks = TaskCounter()

    def ask(name: str) -> None:
        values[name] = binary_task(
            tasks, PROMPTS[name], codebook.fields[name], f"answer_{name}_{uid}", values.get(name)
        )
        if values[name] is None:
            answered.discard(name)
        else:
            answered.add(name)

    ask("KS_present")
    if values["KS_present"] == 1:
        with st.container(border=True):
            st.caption("Knowledge staking details")
            for name in KS_FIELDS:
                ask(name)
    else:
        for name in KS_FIELDS:
            values[name] = None
            answered.discard(name)
    ask("KI_present")
    if values["KI_present"] == 1:
        with st.container(border=True):
            st.caption("Knowledge integration details")
            for name in KI_FIELDS:
                ask(name)
    else:
        for name in KI_FIELDS:
            values[name] = None
            answered.discard(name)
    for name in BASE_BINARY[2:]:
        ask(name)
    task_intro(tasks, "How confident are you in this utterance annotation?", description="Choose 1 through 5.")
    confidence_options = list(range(1, 6))
    values["coder_confidence"] = st.radio(
        "How confident are you in this utterance annotation?",
        confidence_options,
        index=confidence_options.index(values["coder_confidence"])
        if values.get("coder_confidence") in confidence_options
        else None,
        horizontal=True,
        key=f"coder_confidence_{uid}",
        label_visibility="collapsed",
    )
    if values["coder_confidence"] is not None:
        answered.add("coder_confidence")
    task_intro(tasks, "Flag this utterance for review?", description="Choose No or Yes.")
    values["review_flag"] = st.radio(
        "Flag this utterance for review?",
        [0, 1],
        index=[0, 1].index(values["review_flag"]) if values.get("review_flag") in (0, 1) else None,
        format_func=lambda value: "No" if value == 0 else "Yes",
        horizontal=True,
        key=f"review_flag_{uid}",
        label_visibility="collapsed",
    )
    if values["review_flag"] is not None:
        answered.add("review_flag")

with coding:
    task_heading(tasks, "Optional comment")
    values["coder_notes"] = (
        st.text_area(
            "Optional comment",
            value=values.get("coder_notes") or "",
            key=f"coder_notes_{uid}",
        )
        or None
    )
    if values["coder_notes"]:
        answered.add("coder_notes")
    else:
        answered.discard("coder_notes")

    if st.button("Submit and next", type="primary"):
        result = normalize_and_validate(values, answered)
        if not result.valid:
            for name in result.errors:
                st.error(f"Please answer: {PROMPTS.get(name, name)}")
        else:
            storage.save_utterance(
                coder=coder,
                utterance_id=uid,
                dispute_id=did,
                payload=result.payload,
                answered_fields=answered & applicable_fields(result.payload),
                submit=True,
                schema_version=active_schema_id,
                schema_hash=codebook.file_hash,
                opened_at=st.session_state.utterance_opened_at,
                elapsed_wall_seconds=time.monotonic() - st.session_state.utterance_timer_start,
            )
            turns = dataset.annotatable_in_dispute(did)
            later = turns[turns["utterance_order"] > order]
            pending = later[~later["utterance_id"].astype(str).isin(set(submitted) | {uid})]
            if not pending.empty:
                go("utterance", uid=str(pending.iloc[0]["utterance_id"]), did=did)
            else:
                go("dispute", did=did)
            st.rerun()
