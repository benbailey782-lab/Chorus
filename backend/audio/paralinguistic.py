"""Paralinguistic tag mapping for Chorus emotion_tags → Voicebox.

Only applied when the voice's engine is ``chatterbox-turbo`` (the only engine
with documented support for inline tags like ``[laugh]``, ``[sigh]``,
``[whisper]``).

For other engines the text passes through unmodified — the engine will
treat brackets as literal text, but since we don't emit brackets for
non-turbo engines, there's no harm.

The mapping is best-effort: Chorus' emotion_tag vocabulary is larger
than what any single Voicebox engine supports, and the mapping may
need to expand as new engines with inline-tag support are added. Tags
not in ``TAG_MAP`` are silently skipped.
"""

from __future__ import annotations

TAG_MAP: dict[str, str] = {
    "whispered": "[whisper]",
    "shouted": "[shout]",
    "muttered": "[mutter]",
    "amused": "[laugh]",
    "laughed": "[laugh]",
    "sad": "[sigh]",
    "sighed": "[sigh]",
    "shocked": "[gasp]",
    "gasped": "[gasp]",
    # Unmapped (rely on text + voice): trembling, cold, stern, angry, gentle,
    # warm, calm, hushed, emphatic, urgent. These pass silently.
}

CHATTERBOX_ENGINE = "chatterbox-turbo"


def apply_paralinguistic_tags(
    text: str, emotion_tags: list[str] | None, engine: str
) -> str:
    """Prepend Voicebox paralinguistic tags for chatterbox-turbo.

    Example:
        ``text="The deserter died bravely."``,
        ``emotion_tags=["whispered","sad"]``,
        ``engine="chatterbox-turbo"``
        → ``"[whisper] [sigh] The deserter died bravely."``

    For any other engine, returns ``text`` unchanged.
    Duplicates deduped (order-preserving). Tags not in :data:`TAG_MAP`
    silently skipped.
    """
    if engine != CHATTERBOX_ENGINE or not emotion_tags:
        return text
    prefix_parts: list[str] = []
    seen: set[str] = set()
    for tag in emotion_tags:
        norm = (tag or "").strip().lower()
        mapped = TAG_MAP.get(norm)
        if mapped and mapped not in seen:
            prefix_parts.append(mapped)
            seen.add(mapped)
    if not prefix_parts:
        return text
    return " ".join(prefix_parts) + " " + text


if __name__ == "__main__":
    # Smoke examples — run with `python -m backend.audio.paralinguistic`.
    cases = [
        ("The deserter died bravely.", ["whispered", "sad"], "chatterbox-turbo"),
        ("The deserter died bravely.", ["whispered", "sad"], "qwen3-tts"),
        ("Hello", ["whispered", "sad", "unknown"], "chatterbox-turbo"),
        ("Hello", ["whispered", "whispered"], "chatterbox-turbo"),
        ("Hello", [], "chatterbox-turbo"),
        ("Hello", None, "chatterbox-turbo"),
    ]
    for text, tags, engine in cases:
        out = apply_paralinguistic_tags(text, tags, engine)
        print(f"engine={engine!r} tags={tags!r} → {out!r}")
