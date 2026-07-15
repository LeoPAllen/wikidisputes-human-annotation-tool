"""Reusable Streamlit presentation helpers."""

from __future__ import annotations

import html
import re

import pandas as pd
import streamlit as st

from .codebook import FieldGuide
from .ingest import article_title


def inject_css() -> None:
    st.markdown(
        """<style>
    .reading-page-label, .comment-signature, .source-relation {
        color: var(--text-color); opacity: .72;
    }
    .reading-page-label {font-size: .82rem; margin-bottom: .2rem;}
    .discussion-heading {
        color: var(--text-color); font-family: Georgia, 'Times New Roman', serif;
        font-size: 1.3rem; font-weight: 600; line-height: 1.25;
        border-bottom: 1px solid color-mix(in srgb, var(--text-color) 32%, transparent);
        padding-bottom: .25rem; margin: .1rem 0 1rem;
    }
    .focal-comment, .prior-comment {
        color: var(--text-color); overflow-wrap: anywhere;
    }
    .focal-comment {
        border-left: 4px solid var(--primary-color); padding: .85rem 1rem;
        background: var(--secondary-background-color);
        background: color-mix(in srgb, var(--secondary-background-color) 78%, transparent);
        border-radius: .25rem; margin: .25rem 0 1rem;
    }
    .current-label {font-size: .78rem; font-weight: 700; letter-spacing: .02em; margin-bottom: .45rem;}
    .source-text {white-space: pre-wrap; max-width: 78ch; line-height: 1.58; overflow-wrap: anywhere;}
    .comment-signature {font-size: .84rem; margin-top: .55rem;}
    .source-relation {font-size: .82rem; margin: -.4rem 0 .7rem;}
    .prior-comment {padding: .6rem .75rem; margin: .45rem 0; border-left: 2px solid var(--primary-color);}
    .badge {
        display: inline-block; font-size: .72rem; line-height: 1.2; padding: .14rem .42rem;
        margin: 0 .25rem .25rem 0; border: 1px solid currentColor; border-radius: 999px; opacity: .82;
    }
    .na {color:var(--text-color);opacity:.72;font-style:italic;padding:.35rem 0}
    </style>""",
        unsafe_allow_html=True,
    )


def safe_source_text(value: object) -> str:
    """Escape source content while retaining its exact whitespace for CSS rendering."""
    return html.escape("" if pd.isna(value) else str(value), quote=True)


def badge(label: str) -> str:
    return f'<span class="badge">{html.escape(label)}</span>'


def signature(row: pd.Series) -> str:
    speaker = html.escape(str(row.get("speaker_id", "")))
    timestamp = html.escape(str(row.get("timestamp", "")))
    return f'<div class="comment-signature">{speaker} · {timestamp}</div>'


def discussion_heading(row: pd.Series) -> None:
    st.markdown(
        f'<div class="reading-page-label">{html.escape(article_title(row))}</div>'
        f'<div class="discussion-heading">{safe_source_text(row.get("utterance_text"))}</div>',
        unsafe_allow_html=True,
    )


def focal_card(row: pd.Series, reply_description: str | None = None) -> None:
    type_badge = "" if str(row.get("utterance_type", "")).lower() == "talk" else badge(str(row["utterance_type"]))
    order_badge = badge(f"#{int(row['utterance_order'])}")
    st.markdown(
        '<div class="focal-comment"><div class="current-label">Current utterance</div>'
        f"{order_badge}{type_badge}"
        f'<div class="source-text">{safe_source_text(row.get("utterance_text"))}</div>'
        f"{signature(row)}</div>"
        + (f'<div class="source-relation">{html.escape(reply_description)}</div>' if reply_description else ""),
        unsafe_allow_html=True,
    )


def prior_comment(row: pd.Series, badges: tuple[str, ...] = ()) -> None:
    rendered_badges = "".join(badge(item) for item in badges)
    st.markdown(
        f'<div class="prior-comment">{rendered_badges}'
        f'<div class="source-text">{safe_source_text(row.get("utterance_text"))}</div>'
        f"{signature(row)}</div>",
        unsafe_allow_html=True,
    )


def source_details(row: pd.Series) -> None:
    with st.expander("Source details"):
        for label, name in (
            ("Utterance ID", "utterance_id"),
            ("Dispute ID", "dispute_id"),
            ("Original ID", "original_id"),
            ("Reply ID", "reply_to_utterance_id"),
            ("Source row", "_source_row"),
            ("Utterance type", "utterance_type"),
        ):
            value = row.get(name)
            if value is not None and not pd.isna(value):
                st.text(f"{label}: {value}")


def turn_card(row: pd.Series, reason: str | None = None) -> None:
    """Compact full-dispute rendering used only on the post-dispute screen."""
    if row.get("utterance_role") == "context":
        discussion_heading(row)
    else:
        prior_comment(row, (reason,) if reason else ())


def binary_guidance_text(value: str) -> str:
    """Translate stored binary codes into the labels shown by binary controls."""
    return re.sub(r"(?<!\d)[01](?!\d)", lambda match: "Yes" if match.group() == "1" else "No", value)


def guide(label: str, item: FieldGuide, *, binary: bool = False) -> None:
    st.caption(item.definition)
    with st.expander(f"Coding guidance — {label}"):
        st.write(binary_guidance_text(item.rule) if binary else item.rule)
        if item.example:
            st.markdown(f"**Example:** {item.example}")


def binary_control(label: str, key: str, value: int | None = None) -> int | None:
    options = [0, 1]
    index = options.index(value) if value in options else None
    return st.radio(
        label, options, index=index, format_func=lambda item: "No" if item == 0 else "Yes", horizontal=True, key=key
    )


def canonical_caption(name: str) -> None:
    st.caption(f"Codebook field: `{name}`")
