"""Ingest / chapter-detection regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.ingest.chapter_detection import detect_chapters_in_text

# The Phase-3 test harness dumped the rendered AGoT BRAN chapter to this file.
# It contains a lone italicized "I" (from 'but why *I* must do it.') that EPUB
# flattening left on its own line — that exact artifact tripped the Phase-1
# chapter detector into splitting BRAN into two chapters.
BRAN_CHAPTER = Path(
    r"C:\Users\benba\Downloads\chorus-test-harness\chorus-test-harness"
    r"\outputs\run_20260417_172857\input_chapter.txt"
)


@pytest.mark.skipif(
    not BRAN_CHAPTER.exists(),
    reason="AGoT BRAN test-harness chapter not present on this machine",
)
def test_bran_chapter_is_not_split_by_italic_I():
    """The italicized 'I' inside Eddard's speech must not trigger a chapter split.

    Regression for the Phase 4 §1A bug: bare Roman-numeral detection used to
    fire on any 'I' on its own line, including italics-flattened emphasis.
    After the fix the same text resolves to exactly one chapter.
    """
    text = BRAN_CHAPTER.read_text(encoding="utf-8")
    chapters = detect_chapters_in_text(text)
    assert len(chapters) == 1, (
        f"expected 1 chapter, got {len(chapters)}: "
        f"{[c.title for c in chapters]!r}"
    )
    assert "BRAN" in chapters[0].title


def test_real_roman_chapter_headings_still_split():
    """Bare Roman-numeral headings with blank lines on both sides still count."""
    text = "\n".join(
        [
            "",
            "I",
            "",
            "Chapter one text here. " * 30,
            "",
            "II",
            "",
            "Chapter two text here. " * 30,
        ]
    )
    chapters = detect_chapters_in_text(text)
    assert len(chapters) == 2
    assert chapters[0].title == "I"
    assert chapters[1].title == "II"


def test_italicized_I_inline_not_a_chapter_break():
    """A standalone 'I' surrounded by prose (not blank lines) is italics."""
    text = (
        "She said the words slowly: but why\n"
        "I\n"
        "must do it was not something he understood.\n"
    )
    chapters = detect_chapters_in_text(text)
    assert len(chapters) == 1


def test_many_bare_roman_lines_are_suppressed():
    """Over 100 bare-Roman candidates → treated as italics artifacts."""
    text = "\n".join(["I" for _ in range(150)])
    chapters = detect_chapters_in_text(text)
    assert len(chapters) == 1
