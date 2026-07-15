import pandas as pd

from wikidisputes_ui.ui_components import binary_guidance_text, safe_source_text


def test_safe_source_text_escapes_and_preserves_whitespace():
    source = "First line\n*not wiki* <script>alert('x')</script>"
    rendered = safe_source_text(source)
    assert "\n" in rendered
    assert "*not wiki*" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert safe_source_text(pd.NA) == ""


def test_binary_guidance_uses_labels_presented_by_the_control():
    guidance = "If KS_present=1, code 1; otherwise code 0. If KS_present=0, return null."

    assert binary_guidance_text(guidance) == (
        "If KS_present=Yes, code Yes; otherwise code No. If KS_present=No, return null."
    )


def test_binary_guidance_does_not_change_digits_within_larger_numbers():
    assert binary_guidance_text("Use schema 10 and retain 2021.") == "Use schema 10 and retain 2021."
