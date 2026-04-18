from dataclasses import dataclass
from typing import List, Optional

from backend.ingest.chapter_detection import DetectedChapter, detect_chapters_in_text


@dataclass
class TxtIngestResult:
    title: Optional[str]
    author: Optional[str]
    chapters: List[DetectedChapter]
    warnings: List[str]


def ingest_txt(content: bytes, *, filename: Optional[str] = None) -> TxtIngestResult:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    chapters = detect_chapters_in_text(text)

    warnings: list[str] = []
    for ch in chapters:
        warnings.extend(ch.warnings)

    inferred_title = None
    if filename:
        import os
        inferred_title = os.path.splitext(os.path.basename(filename))[0]

    return TxtIngestResult(
        title=inferred_title,
        author=None,
        chapters=chapters,
        warnings=warnings,
    )
