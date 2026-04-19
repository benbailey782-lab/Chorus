#!/usr/bin/env python3
"""Generate silent WAV placeholder audio for all segments in a project/chapter.

Windows dev aid for testing the Phase 6 player without Voicebox. Each segment
gets a silent WAV sized to its estimated duration
(word_count / voicebox_default_wps, clamped 1s-30s).

DO NOT USE IN PRODUCTION. This is a dev tool only.

Usage:
  python scripts/generate_placeholder_audio.py --project agot-test
  python scripts/generate_placeholder_audio.py --project agot-test --chapter BRAN
  python scripts/generate_placeholder_audio.py --project <uuid-or-slug> --force
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Make the repo root importable when running as a script.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audio.paths import raw_segment_path  # noqa: E402
from backend.config import get_settings  # noqa: E402
from backend.db import connect  # noqa: E402


# ---------------------------------------------------------------------------
# Terminal colouring (only when stderr is a TTY)
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stderr.isatty()


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _USE_COLOR else text


def ok(msg: str) -> None:
    print(_c("32", msg))


def skip(msg: str) -> None:
    print(_c("33", msg))


def err(msg: str) -> None:
    print(_c("31", msg), file=sys.stderr)


def info(msg: str) -> None:
    print(msg)


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def resolve_project(conn, ident: str) -> dict:
    """Look up a project by id first, then by slug. Exit 2 on miss."""
    row = conn.execute(
        "SELECT id, slug, title FROM projects WHERE id = ?", (ident,)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id, slug, title FROM projects WHERE slug = ?", (ident,)
        ).fetchone()
    if row is None:
        err(f"project not found: {ident!r} (tried id, then slug)")
        sys.exit(2)
    return dict(row)


def resolve_chapter(conn, project_id: str, ident: str) -> dict:
    """Look up a chapter by id first, then by title (case-insensitive, trimmed).

    Exit 2 if not found or ambiguous.
    """
    row = conn.execute(
        "SELECT id, title, number FROM chapters WHERE id = ? AND project_id = ?",
        (ident, project_id),
    ).fetchone()
    if row is not None:
        return dict(row)
    needle = ident.strip().lower()
    matches = conn.execute(
        """
        SELECT id, title, number FROM chapters
        WHERE project_id = ?
          AND LOWER(TRIM(COALESCE(title, ''))) = ?
        ORDER BY number
        """,
        (project_id, needle),
    ).fetchall()
    if not matches:
        err(f"chapter not found: {ident!r} (tried id, then title)")
        sys.exit(2)
    if len(matches) > 1:
        err(f"chapter title {ident!r} is ambiguous; matches:")
        for m in matches:
            err(f"  id={m['id']}  number={m['number']}  title={m['title']!r}")
        sys.exit(2)
    return dict(matches[0])


# ---------------------------------------------------------------------------
# ffmpeg wrapper
# ---------------------------------------------------------------------------


def run_ffmpeg_silence(duration_seconds: float, out_path: Path) -> tuple[bool, str]:
    """Invoke ffmpeg to write a silent mono PCM-16 WAV of given duration."""
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-t",
        f"{duration_seconds:.3f}",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "ffmpeg not found on PATH"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "ffmpeg failed").strip()
    return True, ""


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------


def compute_duration_seconds(text: str, wps: float) -> float:
    word_count = len((text or "").split())
    if word_count == 0:
        return 1.0
    raw = word_count / wps
    return max(1.0, min(30.0, raw))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Windows dev aid: generate silent WAV placeholders for every "
            "segment in a project/chapter so the Phase 6 player can be "
            "exercised without Voicebox. Not for production."
        ),
    )
    parser.add_argument(
        "--project",
        "-p",
        required=True,
        help="Project id OR slug.",
    )
    parser.add_argument(
        "--chapter",
        "-c",
        default=None,
        help="Optional chapter id OR title. Defaults to ALL chapters.",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Regenerate even when a file already exists (default: skip).",
    )
    parser.add_argument(
        "--wps",
        type=float,
        default=None,
        help="Override words-per-second factor (default: settings.voicebox_default_wps).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without writing anything.",
    )
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        err(
            "ffmpeg not found on PATH. Install it first:\n"
            "  Windows: winget install ffmpeg  (or scoop install ffmpeg)\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   apt/dnf/pacman install ffmpeg"
        )
        return 2

    settings = get_settings()
    wps = args.wps if args.wps is not None else settings.voicebox_default_wps
    if wps <= 0:
        err(f"--wps must be > 0, got {wps}")
        return 2

    generated = 0
    skipped = 0
    failed = 0
    total_seconds = 0.0

    # Late import so handler-registration side effects don't fire on --help.
    from backend.audio.assembly import invalidate_chapter_cache

    try:
        with connect() as conn:
            project = resolve_project(conn, args.project)
            info(
                f"project: {project['title']!r} "
                f"(id={project['id']}, slug={project['slug']})"
            )

            if args.chapter:
                chapter = resolve_chapter(conn, project["id"], args.chapter)
                chapter_rows = [chapter]
                info(
                    f"chapter filter: {chapter['title']!r} "
                    f"(id={chapter['id']}, number={chapter['number']})"
                )
            else:
                chapter_rows = [
                    dict(r)
                    for r in conn.execute(
                        """
                        SELECT id, title, number FROM chapters
                        WHERE project_id = ?
                        ORDER BY number
                        """,
                        (project["id"],),
                    ).fetchall()
                ]
                info(f"chapter filter: ALL ({len(chapter_rows)} chapter(s))")

            if args.dry_run:
                info(_c("36", "--dry-run: no files will be written, no DB updates."))

            for ch in chapter_rows:
                chapter_id = ch["id"]
                segments = conn.execute(
                    """
                    SELECT id, text, audio_path, status
                    FROM segments
                    WHERE chapter_id = ?
                    ORDER BY order_index
                    """,
                    (chapter_id,),
                ).fetchall()

                info(
                    f"\n[{ch['number']:>3}] {ch['title'] or '(untitled)'} "
                    f"- {len(segments)} segment(s)"
                )
                if not segments:
                    continue

                chapter_had_write = False

                for seg in segments:
                    seg_id = seg["id"]
                    dur_s = compute_duration_seconds(seg["text"], wps)
                    dur_ms = int(round(dur_s * 1000))
                    target = raw_segment_path(
                        project["id"], chapter_id, seg_id, "wav"
                    )

                    already = target.exists()
                    if already and not args.force:
                        skip(f"  skip  {seg_id}  ({dur_s:5.2f}s) exists")
                        skipped += 1
                        continue

                    if args.dry_run:
                        info(
                            f"  plan  {seg_id}  ({dur_s:5.2f}s) -> "
                            f"{target.relative_to(REPO_ROOT)}"
                        )
                        generated += 1
                        total_seconds += dur_s
                        continue

                    target.parent.mkdir(parents=True, exist_ok=True)
                    success, ffmpeg_err = run_ffmpeg_silence(dur_s, target)
                    if not success:
                        err(f"  fail  {seg_id}: {ffmpeg_err}")
                        failed += 1
                        continue

                    try:
                        rel_path = str(
                            target.resolve().relative_to(REPO_ROOT)
                        ).replace("\\", "/")
                    except ValueError:
                        # Target outside repo root (unusual); store absolute.
                        rel_path = str(target.resolve()).replace("\\", "/")

                    conn.execute(
                        """
                        UPDATE segments
                        SET audio_path = ?,
                            duration_ms = ?,
                            status = 'generated',
                            updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (rel_path, dur_ms, seg_id),
                    )
                    ok(f"  gen   {seg_id}  ({dur_s:5.2f}s) -> {rel_path}")
                    generated += 1
                    total_seconds += dur_s
                    chapter_had_write = True

                if chapter_had_write and not args.dry_run:
                    try:
                        invalidate_chapter_cache(chapter_id)
                    except Exception as e:  # pragma: no cover - dev aid
                        err(
                            f"  warn  invalidate_chapter_cache({chapter_id}) "
                            f"failed: {e}"
                        )
    except KeyboardInterrupt:
        err("\ninterrupted; current chapter's uncommitted DB writes discarded.")
        return 130

    print()
    summary = (
        f"{generated} generated, {skipped} skipped, {failed} failed. "
        f"Total silent audio: {total_seconds:.1f} seconds."
    )
    if failed:
        err(summary)
        return 1
    ok(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
