"""Merge project + global pronunciations into a single per-project view.

Project entries override global entries when the same ``term`` appears in
both. Matching is case-insensitive so 'Tyrion' and 'tyrion' collapse to the
same merged entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.db import connect


@dataclass
class MergedEntry:
    term: str
    phonetic: str
    ipa: str | None
    confidence: float | None
    source: Literal["global", "project"]
    origin_id: str


def merge_pronunciations(project_id: str) -> dict[str, MergedEntry]:
    """Return a case-insensitive-keyed merged mapping of pronunciations.

    Keys are lowercased terms. When a term exists in both the project-scoped
    ``pronunciations`` table and the ``pronunciations_global`` table, the
    project entry wins.
    """
    merged: dict[str, MergedEntry] = {}
    with connect() as conn:
        # Globals first — they'll be overridden by project entries.
        for r in conn.execute(
            "SELECT id, term, phonetic, ipa, confidence FROM pronunciations_global"
        ).fetchall():
            merged[r["term"].lower()] = MergedEntry(
                term=r["term"],
                phonetic=r["phonetic"],
                ipa=r["ipa"],
                confidence=r["confidence"],
                source="global",
                origin_id=r["id"],
            )
        for r in conn.execute(
            """
            SELECT id, term, phonetic, ipa, confidence
            FROM pronunciations WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall():
            merged[r["term"].lower()] = MergedEntry(
                term=r["term"],
                phonetic=r["phonetic"],
                ipa=r["ipa"],
                confidence=r["confidence"],
                source="project",
                origin_id=r["id"],
            )
    return merged
