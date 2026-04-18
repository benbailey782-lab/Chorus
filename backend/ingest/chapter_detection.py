import re
from dataclasses import dataclass, field
from typing import List

ROMAN = r"[IVXLCDM]+"
WORD_NUM = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?"

HEADING_PATTERNS: list[re.Pattern] = [
    re.compile(rf"^\s*chapter\s+(?:\d+|{ROMAN}|{WORD_NUM})\b.*$", re.IGNORECASE),
    re.compile(rf"^\s*part\s+(?:\d+|{ROMAN}|{WORD_NUM})\b.*$", re.IGNORECASE),
    re.compile(r"^\s*prologue\s*$", re.IGNORECASE),
    re.compile(r"^\s*epilogue\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d{1,3}\s*$"),
    re.compile(rf"^\s*{ROMAN}\s*$"),
]

POV_TITLE = re.compile(r"^\s*([A-Z][A-Z'’\- ]{2,30})\s*$")


@dataclass
class DetectedChapter:
    number: int
    title: str
    text: str
    word_count: int = 0
    warnings: List[str] = field(default_factory=list)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’']+\b", text))


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 80:
        return False
    if any(p.match(stripped) for p in HEADING_PATTERNS):
        return True
    return False


def _looks_like_pov_title(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 40:
        return False
    return bool(POV_TITLE.match(stripped))


def detect_chapters_in_text(text: str, *, min_words: int = 200) -> List[DetectedChapter]:
    lines = text.splitlines()
    boundaries: list[tuple[int, str]] = []

    for idx, line in enumerate(lines):
        if _looks_like_heading(line) or _looks_like_pov_title(line):
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
