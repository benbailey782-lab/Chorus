# Player Guide

## Overview

Chorus produces multi-voice theatrical audiobooks. The **Player** is how you listen to them — on iPhone (PWA, via LAN) or desktop (browser pointed at the Mac backend). A Spotify-style **mini-player** persists across every page in the app once you've loaded a chapter, so you can navigate Library / Voices / Pronunciations / Chapter Review while your audiobook keeps playing.

## Routes

- **`/player`** — the Player tab. Shows a "Continue Listening" strip at the top (projects with non-empty `playback_state` rows), followed by an "All Projects" grid.
- **`/play/:idOrSlug`** — the full player for a single project. Desktop gets a three-column layout; mobile collapses to a single column with a bottom-sheet for synced text.
- **Mini-player** — appears on every page when a chapter is loaded. Hidden while you're viewing `/play/:idOrSlug` (because the full player already owns the screen).

## Starting playback

1. Pick a project from the Library tab or `/player`.
2. If the project's chapters have **no generated audio yet**, you'll hit the "Chapter incomplete" dialog — it points you at the **Chapter Review** page where you can generate segments (Phase 5).
3. Once segments have audio, the Player **assembles** a chapter WAV on the first play: ffmpeg concat demuxer + transcode to canonical `pcm_s16le` / 44.1 kHz / mono. This takes a few seconds for a typical chapter.
4. Subsequent plays of the same chapter serve the **cached WAV** — no ffmpeg, instant start.

Cache invalidation is automatic: if any segment is regenerated, re-approved, or re-rejected, the cached assembly is deleted and the next play re-assembles.

## Controls (desktop)

Three-column layout:

- **Left:** Chapter list — tap any chapter to jump.
- **Center:** Cover art, chapter title, transport controls, scrubber.
- **Right:** Synced text — the current segment highlights as it plays.

Keyboard shortcuts:

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `←` / `→` | Skip backward / forward 15 s |
| `↑` / `↓` | Speed up / slow down (0.25 steps) |
| `PageUp` / `PageDown` | Previous / next chapter |
| `?` | Show help overlay |

## Controls (mobile)

Single column, optimized for thumb reach:

- Minimal top header (project title + close).
- Large cover art.
- Segment preview strip — tap to expand the full synced text as a **bottom sheet**.
- Transport controls sit at the bottom, within comfortable thumb reach.
- **Double-tap** the left or right half of the scrubber for ±15 s skip.

## Speed control

- Range: **0.5× → 2.0×** in **0.25 steps**.
- Desktop: stepper (−/+ buttons around the current value).
- Mobile: cycle-pill (tap to advance through the available speeds).
- **Pitch-preserving** via the browser's native `HTMLMediaElement.preservesPitch`. No extra libraries involved — the native implementation is good enough at the speeds we support.

## Text sync

- Current segment gets an **accent left-border** + **subtle background tint**.
- Auto-scroll keeps the current segment centered in the synced-text view.
- Auto-scroll **pauses for 5 seconds** after you manually scroll, so you can read ahead without fighting the Player.
- Sync is **segment-level**, not word-level. Timings come from cumulative `segments.duration_ms` sums (see `docs/ASSEMBLY-NOTES.md` for the drift caveat).

## Playback state persistence

One row per project in the `playback_state` table:

- `chapter_id` — last playing chapter (nullable).
- `current_segment_id` — last playing segment (nullable).
- `position_ms` — current offset within the chapter.
- `speed` — last selected playback rate.
- `updated_at` — for Continue Listening sort order.

The Player saves state **every 5 s while playing**. When you reopen a project, it resumes exactly where you left off.

## Auto-advance

Default **ON**. Toggle via the settings cog in the Player. Stored locally in `localStorage` under the key **`player:auto-advance`** — it is a client-side preference, not a DB column.

When enabled, finishing a chapter fires a `chapter-ended` window `CustomEvent`; the PlayerController picks it up and loads the next chapter automatically.

## Mini-player

Sits just above the mobile BottomNav (and anchored to the bottom on desktop):

- Chapter title + current speaker.
- Play / pause button.
- Thin progress strip.
- Close button.

**Tap the identity area** (title / speaker) to expand the full player.

**Close** (the × button) soft-clears playback state: keeps the row with `chapter_id = NULL` so Continue Listening can still surface a "last listened" anchor, but removes the active chapter so the mini-player goes away until you start something new.

## Windows dev testing

Voicebox is Mac-only, so Phase 6 ships a placeholder-audio tool for Windows dev:

```powershell
python scripts/generate_placeholder_audio.py --project <slug>
```

This writes a silent WAV for every segment in the project, sized to match the segment's estimated duration (word count / WPS factor, clamped 1–30 s). The Player UI exercises **end-to-end** — scrubber movement, segment timing, auto-scroll, chapter progression, auto-advance — you just hear silence. See `docs/GENERATION-GUIDE.md` for placeholder caveats.

## Known limitations

- **Live Voicebox + Mac deployment still needed** for real audio validation. Everything else has been exercised on Windows against silent WAVs.
- Chapters with mixed-format segment files transcode through ffmpeg during assembly (one extra pass, lossless for WAV sources).
- Text sync is **segment-level**, not word-level. A long sentence highlights as a single unit.
