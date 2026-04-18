import io
import re
import warnings
from dataclasses import dataclass
from typing import List, Optional

from bs4 import BeautifulSoup, NavigableString
from bs4 import XMLParsedAsHTMLWarning
from ebooklib import ITEM_DOCUMENT, epub

from backend.ingest.chapter_detection import DetectedChapter

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SKIP_KEYWORDS = {
    "cover", "title", "copyright", "toc", "nav", "contents", "dedication",
    "acknowledgments", "acknowledgements", "about-the-author", "also-by",
    "colophon", "front-matter", "back-matter", "frontmatter", "backmatter",
    "index", "glossary", "appendix", "preview", "excerpt", "bonus",
    "map", "maps", "genealogy", "family-tree", "epigraph-front",
}

SKIP_TOKEN_RE = re.compile(
    r"_(cop|ack|ata|adc|ded|tp|fm|bm|bm\d+|toc|nav|cvr|cover|map|copy|index|"
    r"excerpt|preview|teaser|bonus|ata\d*|also|about|col|ded\d*|aut|auth|"
    r"back|front|prv|nxt|loi|lot|title|ttl|ffm|bbm|rom|epi)[_\d]*(_r\d+)?\b",
    re.IGNORECASE,
)


@dataclass
class EpubIngestResult:
    title: Optional[str]
    author: Optional[str]
    chapters: List[DetectedChapter]
    warnings: List[str]


def _extract_text(html: bytes) -> tuple[str, Optional[str]]:
    soup = BeautifulSoup(html, "lxml")
    heading_el = soup.find(["h1", "h2", "h3"])
    heading = heading_el.get_text(" ", strip=True) if heading_el else None
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    body = soup.body if soup.body else soup
    parts: list[str] = []
    for elem in body.descendants:
        if isinstance(elem, NavigableString):
            continue
        name = getattr(elem, "name", None)
        if name in {"p", "div", "blockquote", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            text = elem.get_text(" ", strip=True)
            if text:
                italics_present = bool(elem.find(["i", "em"]))
                if italics_present:
                    for i_el in elem.find_all(["i", "em"]):
                        i_text = i_el.get_text(" ", strip=True)
                        if i_text:
                            i_el.replace_with(f"*{i_text}*")
                    text = elem.get_text(" ", strip=True)
                parts.append(text)
    raw = "\n\n".join(parts)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip(), heading


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’']+\b", text))


def _looks_like_skip(name: str, heading: Optional[str], body: str) -> bool:
    lower_name = (name or "").lower()
    if any(kw in lower_name for kw in SKIP_KEYWORDS):
        return True
    if SKIP_TOKEN_RE.search(lower_name):
        return True
    if heading:
        lower_h = heading.lower().strip()
        if lower_h in {
            "copyright", "contents", "table of contents", "dedication",
            "acknowledgments", "acknowledgements", "about the author",
            "about the authors", "also by", "title page", "map", "maps",
            "appendix", "glossary", "family tree", "genealogy",
        }:
            return True
    # heuristic: short front-matter snippets packed with "copyright" or "published by"
    head = body[:1500].lower()
    if any(s in head for s in ("all rights reserved", "isbn", "published by",
                               "library of congress", "penguin random house",
                               "printed in the united states")):
        return True
    return False


def _clean_title(raw: str, fallback_index: int) -> str:
    """Turn a heading or filename into a human title."""
    if not raw:
        return f"Chapter {fallback_index}"
    # Reject obvious filenames.
    if "/" in raw or raw.lower().endswith((".htm", ".html", ".xhtml")):
        return f"Chapter {fallback_index}"
    return raw.strip()


def ingest_epub(content: bytes) -> EpubIngestResult:
    book = epub.read_epub(io.BytesIO(content))

    title = None
    author = None
    try:
        md_title = book.get_metadata("DC", "title")
        if md_title:
            title = md_title[0][0]
        md_author = book.get_metadata("DC", "creator")
        if md_author:
            author = md_author[0][0]
    except Exception:
        pass

    spine_items = [book.get_item_with_id(itemref[0]) for itemref in book.spine]
    spine_items = [it for it in spine_items if it and it.get_type() == ITEM_DOCUMENT]
    if not spine_items:
        spine_items = list(book.get_items_of_type(ITEM_DOCUMENT))

    chapters: list[DetectedChapter] = []
    warnings: list[str] = []

    for item in spine_items:
        name = item.get_name() or item.id or ""
        try:
            body_text, heading = _extract_text(item.get_content())
        except Exception as e:
            warnings.append(f"failed to parse {name}: {e}")
            continue
        if not body_text:
            continue
        if _looks_like_skip(name, heading, body_text):
            continue
        wc = _word_count(body_text)
        if wc < 100:
            continue
        ch_title = _clean_title(heading or "", len(chapters) + 1)
        chapters.append(
            DetectedChapter(
                number=len(chapters) + 1,
                title=ch_title,
                text=body_text,
                word_count=wc,
                warnings=[],
            )
        )

    if not chapters:
        warnings.append("no chapters extracted from EPUB spine")

    return EpubIngestResult(
        title=title,
        author=author,
        chapters=chapters,
        warnings=warnings,
    )
