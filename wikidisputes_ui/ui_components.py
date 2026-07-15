"""Reusable Streamlit presentation helpers."""

from __future__ import annotations

import html
import streamlit as st
import pandas as pd

from .codebook import FieldGuide
from .ingest import article_title


def inject_css() -> None:
    st.markdown(
        """<style>
    .focal {border-left: 5px solid #2364aa; background:#f6f8fb; padding:1.1rem 1.25rem; border-radius:.35rem; margin:.3rem 0 1rem}
    .focal-meta,.turn-meta {color:#46505a;font-size:.86rem;margin-bottom:.45rem}
    .turn {border-left:3px solid #8b98a5;padding:.55rem .8rem;margin:.45rem 0;background:#fafafa}
    .context-heading {border-left:3px solid #6b7280;padding:.55rem .8rem;margin:.45rem 0;background:#eef1f4;font-weight:600}
    .na {color:#59636e;font-style:italic;padding:.35rem 0}
    </style>""",
        unsafe_allow_html=True,
    )


def guide(label: str, item: FieldGuide) -> None:
    st.caption(item.definition)
    with st.expander(f"Coding guidance — {label}"):
        st.write(item.rule)
        if item.example:
            st.markdown(f"**Example:** {item.example}")


def focal_card(row: pd.Series) -> None:
    target = (
        ""
        if pd.isna(row.get("reply_to_utterance_id"))
        else f" · Reply to {html.escape(str(row['reply_to_utterance_id']))}"
    )
    st.markdown(
        f"""<div class="focal"><div class="focal-meta"><strong>{html.escape(article_title(row))}</strong> · Dispute {html.escape(str(row["dispute_id"]))} · Utterance #{int(row["utterance_order"])}<br>{html.escape(str(row["speaker_id"]))} · {html.escape(str(row["timestamp"]))} · ID {html.escape(str(row["utterance_id"]))} · {html.escape(str(row["utterance_type"]))}{target}</div><div>{html.escape(str(row["utterance_text"])).replace(chr(10), "<br>")}</div></div>""",
        unsafe_allow_html=True,
    )


def turn_card(row: pd.Series, reason: str | None = None) -> None:
    prefix = f"<strong>{html.escape(reason)}</strong><br>" if reason else ""
    is_context = row.get("utterance_role") == "context"
    css_class = "context-heading" if is_context else "turn"
    role = "Conversation heading · " if is_context else ""
    st.markdown(
        f"<div class='{css_class}'>{prefix}<div class='turn-meta'>{role}#{int(row['utterance_order'])} · {html.escape(str(row['speaker_id']))} · {html.escape(str(row['timestamp']))} · {html.escape(str(row['utterance_id']))}</div>{html.escape(str(row['utterance_text'])).replace(chr(10), '<br>')}</div>",
        unsafe_allow_html=True,
    )


def binary_control(label: str, key: str, value: int | None = None) -> int | None:
    options = [0, 1]
    index = options.index(value) if value in options else None
    return st.radio(
        label, options, index=index, format_func=lambda item: "No" if item == 0 else "Yes", horizontal=True, key=key
    )


def not_applicable(label: str) -> None:
    st.markdown(f"**{label}**")
    st.markdown("<div class='na'>Not applicable</div>", unsafe_allow_html=True)
