import re
from dataclasses import dataclass, field
from typing import List

ROMAN = r"[IVXLCDM]+"
WORD_NUM = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?"

# "Strong" heading patterns — unambiguous enough that neighbouring-line context
# is not needed. A bare Roman numeral line is NOT in this list; it gets its
# own stricter check below because italicized "I" emphasis shows up as a bare
# "I" line after EPUB flattening and would otherwise split chapters at every
# emphatic pronoun (§1A in the Phase 4 instructions).
HEADING_PATTERNS: list[re.Pattern] = [
    re.compile(rf"^\s*chapter\s+(?:\d+|{ROMAN}|{WORD_NUM})\b.*$", re.IGNORECASE),
    re.compile(rf"^\s*part\s+(?:\d+|{ROMAN}|{WORD_NUM})\b.*$", re.IGNORECASE),
    re.compile(r"^\s*prologue\s*$", re.IGNORECASE),
    re.compile(r"^\s*epilogue\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d{1,3}\s*$"),
]

# Bare-Roman pattern, matched with full-line anchors (no surrounding text).
BARE_ROMAN = re.compile(rf"^{ROMAN}$")

POV_TITLE = re.compile(r"^\s*([A-Z][A-Z'’\- ]{2,30})\s*$")

# If more than this many bare-Roman lines are present, we treat every bare
# Roman as italics/artifact rather than chapter breaks (§1A heuristic a).
BARE_ROMAN_MAX_MATCHES = 100

# Characters of neighbouring prose to inspect when deciding whether a bare
# single-letter Roman (I or V) looks like an italics artifact (§1A heuristic b).
BARE_ROMAN_PROSE_PROXIMITY_CHARS = 200

LOWERCASE_PROSE_RE = re.compile(r"[a-z]")


@dataclass
class DetectedChapter:
    number: int
    title: str
    text: str
    word_count: int = 0
    warnings: List[str] = field(default_factory=list)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’']+\b", text))


def _is_strong_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    return any(p.match(stripped) for p in HEADING_PATTERNS)


def _looks_like_pov_title(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 40:
        return False
    return bool(POV_TITLE.match(stripped))


def _prose_is_close(lines: list[str], idx: int) -> bool:
    """Return True if lowercase prose sits within BARE_ROMAN_PROSE_PROXIMITY_CHARS
    of line ``idx`` in either direction.

    Used to distinguish an italics-artifact "I" (surrounded by dialogue/prose)
    from a real chapter-numeral "I" (surrounded by blank lines).
    """
    # Walk backwards counting characters until we find lowercase prose.
    chars_back = 0
    for j in range(idx - 1, -1, -1):
        chars_back += len(lines[j]) + 1  # +1 for the stripped newline
        if LOWERCASE_PROSE_RE.search(lines[j]):
            if chars_back <= BARE_ROMAN_PROSE_PROXIMITY_CHARS:
                return True
            break
        if chars_back > BARE_ROMAN_PROSE_PROXIMITY_CHARS:
            break

    chars_fwd = 0
    for j in range(idx + 1, len(lines)):
        chars_fwd += len(lines[j]) + 1
        if LOWERCASE_PROSE_RE.search(lines[j]):
            return chars_fwd <= BARE_ROMAN_PROSE_PROXIMITY_CHARS
        if chars_fwd > BARE_ROMAN_PROSE_PROXIMITY_CHARS:
            break
    return False


def _count_bare_roman_candidates(lines: list[str]) -> int:
    """Count lines whose raw content (no strip) matches a bare Roman numeral."""
    return sum(1 for ln in lines if BARE_ROMAN.match(ln))


def _is_bare_roman_heading(
    lines: list[str],
    idx: int,
    *,
    suppress_bare_roman: bool,
) -> bool:
    """Guarded detector for a bare Roman-numeral chapter heading.

    Conservative — prefers false negatives (user manually fixes a missed
    break) over false positives (silent bad-split that cascades). Applies:
      * The line must match ``BARE_ROMAN`` on the raw (unstripped) content —
        no trailing whitespace allowed.
      * The previous raw line AND the next raw line must both be EXACTLY
        empty strings (not whitespace-only), per §1A.
      * If the doc has >100 bare-Roman candidates (``suppress_bare_roman``),
        treat every bare-Roman as an italics artifact.
      * For single-letter I / V specifically, suppress when lowercase prose
        sits within ``BARE_ROMAN_PROSE_PROXIMITY_CHARS``.
    """
    line = lines[idx]
    if not BARE_ROMAN.match(line):
        return False
    if suppress_bare_roman:
        return False
    # Blank-line gates on both sides. Treat the doc boundary (before line 0
    # or after the last line) as "blank" since there's no prose there either.
    prev_line = lines[idx - 1] if idx - 1 >= 0 else ""
    next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
    if prev_line != "" or next_line != "":
        return False
    # Extra proximity guard for the ambiguous single letters "I" and "V".
    if line in {"I", "V"} and _prose_is_close(lines, idx):
        return False
    return True


def detect_chapters_in_text(text: str, *, min_words: int = 200) -> List[DetectedChapter]:
    lines = text.splitlines()

    suppress_bare_roman = (
        _count_bare_roman_candidates(lines) > BARE_ROMAN_MAX_MATCHES
    )

    boundaries: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if _is_strong_heading(line) or _looks_like_pov_title(line):
            boundaries.append((idx, line.strip()))
        elif _is_bare_roman_heading(
            lines, idx, suppress_bare_roman=suppress_bare_roman
        ):
            boundaries.append((idx, line.strip()))

    if not boundaries:
        return [
            DetectedChapter(
                number=1,
                title="Untitled",
                text=text.strip(),
                word_count=_word_count(text),
                warnings=["no headings detected; treating whole document as one chapter"],
            )
        ]

    chapters: List[DetectedChapter] = []
    for i, (line_idx, title) in enumerate(boundaries):
        next_start = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(lines)
        body_lines = lines[line_idx + 1 : next_start]
        body = "\n".join(body_lines).strip()
        wc = _word_count(body)
        chapters.append(
            DetectedChapter(
                number=len(chapters) + 1,
                title=title,
                text=body,
                word_count=wc,
                warnings=[] if wc >= min_words else [f"chapter {len(chapters) + 1} is short ({wc} words)"],
            )
        )
    return chapters
