# CHORUS — Multi-Voice Theatrical Audiobook Generator

> **Status:** Spec v0.3 — director-only workflow, file-drop LLM integration. Supersedes v0.2.

> **Working name:** Chorus. Alternatives: Bard, Prologue, Dotrice, Cadence, Voxbook. Decide before Phase 0.

---

## 1. Vision

Chorus turns any book into a **full theatrical audiobook performance** — every character voiced distinctly, emotional beats rendered inline, ambient soundscapes layered under scenes, cover art generated — using local TTS models (Voicebox) and the Anthropic API for dialogue understanding.

The target production quality sits somewhere between a BBC radio drama and a top-tier Audible performance. The user **directs the production step by step** — Chorus pauses at every major creative decision so the user can review the output before committing. Output plays back in-app on phone or desktop, or exports to any standard audiobook player.

This is a personal tool that may eventually be open-sourced, so code quality, documentation, and UX polish matter from the start.

**Primary test case:** *A Game of Thrones* — complex cast (~30 speaking characters), invented names requiring pronunciation control, POV chapter structure, varied emotional registers. If Chorus can handle AGoT, it can handle most books.

---

## 2. Why Now

Voicebox v0.2 ships five local TTS engines with a REST API and 2–3s-per-chunk inference on Apple Silicon via MLX. Chatterbox Turbo supports inline paralinguistic tags (`[laugh]`, `[sigh]`, `[gasp]`, etc.). Claude is genuinely good at dialogue attribution and character modeling. The cost structure finally works locally.

---

## 3. Review-Gated Workflow

Chorus is a review-gated workflow where the user explicitly advances through each stage of the pipeline. Each stage produces output the user inspects before proceeding.

**Stages, in order:**
1. **Upload** — drop in a `.txt` or `.epub`; Chorus parses chapters.
2. **Cast extraction** — Claude returns a cast list; user edits names, descriptions, merges duplicates.
3. **Voice casting** — auto-cast from the voice library; user previews each assignment, overrides where wanted, clones new voices if the library is thin.
4. **Pronunciation review** — approve/edit phonetic overrides for unusual names and terms.
5. **Per-chapter attribution review** — fix low-confidence segments inline.
6. **Generation** — TTS runs; progress streamed; user can pause/resume.
7. **Assembly** — FFmpeg stitches the chapter MP3s and the full M4B with chapter markers, cover, and ambient beds.

Each gate can be skipped when the output already looks good, but every stage is an explicit step the user confirms — there is no "drop in and walk away" path. Real-time voice preview is essential throughout.

---

## 4. Scope & Non-Goals

### v1 In Scope
- TXT and EPUB ingestion with automatic chapter detection
- Character extraction and profiling via Claude
- **Voice library with auto-casting** (see §7)
- POV narrator switching (toggleable per project)
- Full dialogue attribution with emotion tagging
- Special content rendering: epigraphs, letters, poetry, song lyrics, italicized emphasis
- Audio generation per segment via Voicebox
- FFmpeg assembly into per-chapter MP3 + full M4B with chapter markers
- **Ambient soundscapes** (scene-level)
- **Cover art generation** (one per project)
- **In-app library with web-based player** (mobile-responsive, LAN-accessible from phone)
- Review-gated workflow (explicit user gates at cast, casting, pronunciation, attribution, generation)
- Project persistence with resume
- Cost + time estimation with live tracking

### v1 Out of Scope / Post-v1
- PDF ingestion (defer; EPUB covers most books)
- Per-segment regeneration after export
- Per-beat sound effects (door slams, sword clashes) — scene-level ambient only in v1
- Multi-language single-book support
- **Translation between languages** (future feature, architecturally anticipated)
- Multi-book series / shared casts
- Community voice library / sharing
- Native mobile app (PWA is the mobile story for v1)
- Publishing/distribution to any platform

---

## 5. Architecture

### 5.1 Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Runtime | Python 3.11+ | Matches Voicebox backend; strong audio lib ecosystem |
| Web framework | FastAPI | Async, auto OpenAPI docs, SSE support for progress |
| Database | SQLite | Single-file, zero-config, sufficient for local-only use |
| Frontend framework | React 18 + Vite + TypeScript | Matches Cortex workflow; mobile-responsive UIs are easier |
| Styling | Tailwind CSS | Fast iteration, mobile-first defaults |
| State management | Zustand | Lightweight, no boilerplate |
| Data fetching | TanStack Query | Cache, polling for job progress |
| LLM (primary) | Claude Opus 4.7 via Anthropic API | Cast extraction, low-confidence attribution |
| LLM (bulk) | Claude Sonnet 4.6 via Anthropic API | Per-chapter attribution |
| LLM (dev) | Claude Code subscription | Initial dev work without API costs |
| Image generation | DALL-E 3 or Flux via API | Cover art |
| TTS | Voicebox REST API (localhost) | Local, free, high quality |
| Audio processing | FFmpeg (subprocess) | Assembly, normalization, M4B packaging |
| Ambient audio | `pydub` | Ambient bed layering under narration |
| EPUB parsing | `ebooklib` + `BeautifulSoup` | Handles metadata and nested HTML |
| mDNS | `zeroconf` | Advertises chorus.local on LAN |

### 5.2 Deployment Model — Mobile-First via LAN

Chorus runs on the Mac because Voicebox runs on the Mac. The phone accesses it via local network:

```
┌────────────────────┐         ┌────────────────────┐
│   Ben's iPhone     │         │   Ben's MacBook    │
│                    │         │                    │
│   Safari →         │◄────────┤   Chorus Backend   │
│   chorus.local:    │  WiFi   │   :8765            │
│   8765             │  LAN    │                    │
│                    │         │   Voicebox         │
│                    │         │   :8090            │
└────────────────────┘         └────────────────────┘
```

**Concretely:**
- FastAPI binds to `0.0.0.0:8765` (not just localhost)
- Bonjour/mDNS advertises the service as `chorus.local` via `zeroconf`
- Phone accesses `http://chorus.local:8765` in Safari
- The web UI is a Progressive Web App — "Add to Home Screen" behaves like a native app
- Listening works as long as Mac is on the same WiFi and awake (Chorus's own keep-awake mode activates during active playback sessions, leveraging `caffeinate` like KeepAwake.py)
- For offline mobile listening: in-app "Send to Files" button AirDrops the M4B to the phone where Apple Books picks it up with full chapter support

### 5.3 System Diagram

```
                    ┌───────────────────────────────────────┐
                    │       React + Vite Frontend           │
                    │   (mobile-responsive; PWA-ready)      │
                    └────────────────┬──────────────────────┘
                                     │ REST + SSE
                    ┌────────────────▼──────────────────────┐
                    │          Chorus Backend               │
                    │          (FastAPI, :8765)             │
                    │                                       │
                    │  ┌─────────┐ ┌─────────┐ ┌─────────┐  │
                    │  │ Ingest  │ │  NLP    │ │ Audio   │  │
                    │  │ txt/    │ │ Claude  │ │ Gen +   │  │
                    │  │ epub    │ │ passes  │ │ Mix     │  │
                    │  └────┬────┘ └────┬────┘ └────┬────┘  │
                    │       │           │           │       │
                    │       └───────┬───┴───────────┘       │
                    │               │                       │
                    │  ┌────────────▼────────────────────┐  │
                    │  │   SQLite + Job Queue + Files    │  │
                    │  └────────────┬────────────────────┘  │
                    │               │                       │
                    │  ┌────────────▼────────────────────┐  │
                    │  │     FFmpeg / pydub pipelines    │  │
                    │  └─────────────────────────────────┘  │
                    └────┬──────────────────┬───────────┬───┘
                         │                  │           │
                ┌────────▼──────┐  ┌────────▼──────┐  ┌─▼────────┐
                │ Anthropic API │  │ Voicebox API  │  │ Image    │
                │   (Claude)    │  │ (localhost)   │  │ Gen API  │
                └───────────────┘  └───────────────┘  └──────────┘
```

### 5.4 Directory Layout

```
chorus/
├── backend/
│   ├── main.py                       # FastAPI app
│   ├── config.py                     # Env + runtime config
│   ├── db.py                         # SQLite schema + helpers
│   ├── mdns.py                       # Bonjour advertisement
│   ├── ingest/
│   │   ├── txt.py
│   │   ├── epub.py
│   │   └── chapter_detection.py      # Regex + Claude fallback
│   ├── nlp/
│   │   ├── claude_client.py
│   │   ├── extract_characters.py
│   │   ├── attribute_dialogue.py
│   │   ├── special_content.py
│   │   ├── pronunciation.py
│   │   └── prompts/
│   │       ├── extract_cast.md
│   │       ├── attribute_chapter.md
│   │       ├── detect_special_content.md
│   │       ├── auto_cast_voices.md
│   │       └── pronounce_unusual.md
│   ├── voices/
│   │   ├── library.py                # Voice library CRUD
│   │   ├── auto_caster.py            # Claude-based matching
│   │   └── voicebox_client.py        # REST wrapper
│   ├── audio/
│   │   ├── generator.py              # Queue + orchestration
│   │   ├── renderer.py               # Per-segment with engine/effects
│   │   ├── ambient.py                # Scene soundscape mixing
│   │   └── assembly.py               # FFmpeg pipelines
│   ├── export/
│   │   ├── mp3.py
│   │   ├── m4b.py
│   │   └── cover_art.py              # Image model integration
│   ├── jobs/
│   │   ├── queue.py                  # Background job runner
│   │   ├── estimator.py              # Time + cost ETA
│   │   └── events.py                 # SSE event hub
│   └── api/
│       ├── projects.py
│       ├── characters.py
│       ├── voices.py
│       ├── segments.py
│       ├── generate.py
│       ├── player.py
│       └── jobs.py
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── routes/
│   │   │   ├── Library.tsx
│   │   │   ├── Project.tsx
│   │   │   ├── Casting.tsx
│   │   │   ├── Review.tsx
│   │   │   ├── Player.tsx
│   │   │   └── VoiceLibrary.tsx
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── stores/
│   │   └── lib/
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   └── tailwind.config.js
├── ambient/                          # User-supplied CC0 ambient tracks
│   ├── tavern.mp3
│   ├── storm.mp3
│   └── ...
├── data/                             # .gitignored
│   ├── chorus.db
│   ├── voice_library/
│   │   └── metadata.json
│   ├── llm_queue/                    # File-drop LLM integration (§12A)
│   │   ├── pending/                  # request_<id>.md — Chorus writes here
│   │   ├── responses/                # response_<id>.json — Claude Code writes here
│   │   └── completed/                # Claude Code moves pending files here after answering
│   └── projects/
│       └── <slug>/
│           ├── source.txt
│           ├── cover.png
│           ├── segments/
│           └── output/
│               ├── chapters/
│               └── book.m4b
├── scripts/
│   ├── setup.sh
│   ├── run.sh                        # Launches backend + frontend + opens browser
│   └── keepawake.py                  # Keeps Mac awake during generation
├── .env.example
├── requirements.txt
├── CHORUS-SPEC.md                    # This file
├── LICENSE                           # MIT, for eventual open-source
└── README.md
```

---

## 6. Special Content Rendering

Books are not just prose. Chorus treats different content types as first-class render modes with distinct audio treatments. Each segment has a `render_mode` field that controls how it's synthesized.

| Render Mode | Trigger | Audio Treatment |
|---|---|---|
| `prose` | Default | Narrator voice, natural pacing |
| `dialogue` | Quoted speech | Assigned character voice, emotional tags inline |
| `epigraph` | Italicized block at chapter start | Narrator voice, slower pace, 1s pre-silence, slight reverb |
| `letter` | Detected letter/diary format | Character voice (if known) OR neutral voice with paper-shuffle SFX beat, parchment filter |
| `poetry` | Verse structure detected | Narrator voice, exaggerated pacing at line breaks, rhythmic delivery |
| `song_lyrics` | Song/ballad detected | HumeAI TADA engine (more expressive), slight reverb, extended post-silence |
| `emphasis` | Italicized within prose | Stress injected via engine-specific prosody hints |
| `thought` | Italicized first-person internal monologue | Character voice OR narrator with subtle filter (configurable) |
| `chapter_heading` | Chapter title | Narrator voice, slow, 2s pre/post silence |

Detection happens in a dedicated Claude pass (`detect_special_content.md`) or merged into attribution pass 4. Italics detection requires EPUB parsing that preserves formatting — for .txt inputs, we warn users and offer manual tagging during review.

---

## 7. The Voice Library System

This is the core creative piece of Chorus and what makes auto-casting possible.

### 7.1 Concept

A Voice Library is a curated collection of voice profiles, each enriched with metadata that describes the voice's character — not just its technical properties. Think of it like a casting agency catalog.

Every voice has:
- A link to a Voicebox profile (where the actual voice data lives)
- Rich descriptive metadata for auto-casting
- Pool assignment: `main` / `background` / `narrator`
- Usage tracking: which projects have used this voice

### 7.2 Voice Metadata Schema

```json
{
  "id": "v_brynden_001",
  "voicebox_profile_id": "vb_xyz...",
  "display_name": "Old Scottish Soldier",
  "gender": "male",
  "age_range": "elder",
  "accent": "scottish_highland",
  "tone": ["gravelly", "weathered", "stern"],
  "timbre": "deep",
  "pace": "measured",
  "register": "rough",
  "character_archetypes": ["mentor", "veteran", "hermit", "tragic"],
  "pool": "main",
  "engine_preference": "chatterbox_turbo",
  "sample_text": "The winds of winter have come for us all.",
  "source_notes": "Cloned from public-domain BBC archive recording, 1952",
  "tags": ["mature", "authoritative", "war-weary"],
  "added_at": "2026-04-16T...",
  "times_used": 3
}
```

### 7.3 Pool Strategy

- **main pool:** Distinct, memorable voices for named characters. Target 20–40 voices in a well-stocked library.
- **background pool:** Generic voices for 1–2-line characters (tavern wench, city guard #2). Cycled through to avoid repetition within a scene. Target 5–10 voices.
- **narrator pool:** Voices specifically suited to narration (clear, neutral, pleasant endurance). Target 3–5 voices.

### 7.4 Seeding the Library

Chorus does **not** ship with pre-cloned voices (legal minefield). Instead:

1. First run: Chorus walks the user through recording or uploading at least 3 voices (1 narrator, 2 main pool) to start.
2. Ships with a **library of metadata templates** — empty slots with descriptions like "Gravelly Old Man," "Bright Young Woman," "Cold Aristocrat" — that users can fill as they go.
3. README documents suggested sources: LibriVox, Internet Archive old-time radio (public domain), their own voice, consenting friends.

### 7.5 Auto-Casting Algorithm

When a project's cast is extracted, auto-casting assigns a voice to each character.

**Input to Claude:**
- Full cast list with attributes (gender, age, description, speaking_style, line_count)
- Full voice library metadata
- Constraint hints (e.g., "narrator voice pref is neutral clear")

**Claude returns:**
```json
[
  {
    "character_id": "c_eddard",
    "voice_id": "v_stern_lord_001",
    "confidence": 92,
    "reasoning": "Stern northern lord, dignified, gravelly — matches 'cold honor' descriptor"
  }
]
```

**Rules enforced by code (post-Claude):**
- No voice assigned to >1 main character per project
- Background pool voices can be reused (characters with <3 lines)
- Gender mismatches flagged but allowed (user can override at the voice-casting review gate)
- If library has insufficient voices for distinct assignments, flag "need more voices" with suggestions for what's missing

**Fallback:** If auto-casting fails (library too small), the user is routed into manual casting at the same review gate.

---

## 8. POV Narrator Switching

For books structured around POV characters (AGoT, most modern fantasy), a toggle enables per-chapter narrator switching.

**How it works:**
- Each chapter gets a `pov_character_id` field (auto-detected from chapter titles like "BRAN" in AGoT, or detected by Claude analyzing the chapter opening)
- If the project has "POV Narrator" enabled, narration segments in that chapter use the POV character's voice
- Dialogue from other characters still uses their own voices
- Net effect: Bran's inner monologue sounds like Bran, but when Eddard speaks in a Bran chapter, Eddard still sounds like Eddard

**Detection:**
- Pass 1: Regex for chapters titled after a cast character
- Pass 2: Claude reads the first paragraph; if written in third-person limited from a named perspective, assigns POV

**UI:**
- Toggle in project settings: "Use POV character voice for narration"
- Per-chapter override at the attribution review gate (user can set/change POV assignment)

---

## 9. Data Model

All timestamps ISO 8601 UTC. All IDs are UUIDs.

### 9.1 `projects`
| Column | Type | Notes |
|---|---|---|
| id | TEXT | PK |
| slug | TEXT | URL-safe |
| title | TEXT | |
| author | TEXT | |
| language | TEXT | ISO 639-1, default `en` |
| status | TEXT | `ingesting`/`casting`/`attributing`/`generating`/`assembling`/`complete` |
| pov_narrator_enabled | INTEGER | 0/1 |
| ambient_enabled | INTEGER | 0/1 |
| cover_art_path | TEXT | |
| total_duration_ms | INTEGER | |
| estimated_cost_usd | REAL | |
| actual_cost_usd | REAL | |
| created_at, updated_at | TEXT | |

> **Migration note (v0.3):** the `mode` column was removed when Automated Mode was dropped from the product. Any existing projects should be treated as director-mode by default; at the time of this change no projects existed, so the column can simply be dropped in the migration.

### 9.2 `chapters`
| Column | Type | Notes |
|---|---|---|
| id | TEXT | PK |
| project_id | TEXT | FK |
| number | INTEGER | 1-indexed |
| title | TEXT | |
| raw_text | TEXT | |
| pov_character_id | TEXT | FK, nullable |
| ambient_scene_tag | TEXT | e.g. "tavern", "forest_night" |
| word_count | INTEGER | |
| estimated_duration_ms | INTEGER | |
| status | TEXT | `pending`/`attributed`/`generated`/`assembled` |

### 9.3 `characters`
| Column | Type | Notes |
|---|---|---|
| id | TEXT | PK |
| project_id | TEXT | FK |
| name | TEXT | |
| aliases | TEXT (JSON) | |
| description | TEXT | |
| gender | TEXT | |
| age_estimate | TEXT | `child`/`teen`/`young_adult`/`middle_aged`/`elder`/`unknown` |
| speaking_style | TEXT | |
| character_archetype | TEXT | For matching |
| voice_id | TEXT | FK → voices |
| engine_override | TEXT | Nullable |
| line_count | INTEGER | Computed |
| is_narrator | INTEGER | 0/1 |
| first_chapter_id | TEXT | FK |

### 9.4 `voices` (the voice library)
See §7.2 schema; stored in SQL with JSON columns for arrays.

### 9.5 `segments`
| Column | Type | Notes |
|---|---|---|
| id | TEXT | PK |
| chapter_id | TEXT | FK |
| order | INTEGER | |
| character_id | TEXT | FK |
| text | TEXT | |
| render_mode | TEXT | See §6 |
| emotion_tags | TEXT (JSON) | `["sigh", "whispered"]` |
| pre_silence_ms | INTEGER | Default by render_mode |
| post_silence_ms | INTEGER | Default by render_mode |
| confidence | INTEGER | 0–100 |
| audio_path | TEXT | |
| duration_ms | INTEGER | |
| status | TEXT | `pending`/`generated`/`approved`/`error` |
| error_message | TEXT | |
| generated_at | TEXT | |

### 9.6 `pronunciations`
| Column | Type | Notes |
|---|---|---|
| id | TEXT | PK |
| project_id | TEXT | FK |
| word | TEXT | |
| phonetic | TEXT | Respelling applied via text substitution |
| applies_to_character_id | TEXT | Nullable; scope. **Per-character scoping deferred to Phase 7** — the column is reserved but unused in v1. Phase 5 ships global + project scopes only (project overrides global). See `docs/PRONUNCIATION-GUIDE.md`. |

### 9.7 `playback_state`

One row per project. Rebuilt in schema v7 (Phase 6) — the original v1 shape only carried `chapter_id` + `position_ms`.

| Column | Type | Notes |
|---|---|---|
| project_id | TEXT | PK. FK to `projects`, `ON DELETE CASCADE`. |
| chapter_id | TEXT | Nullable. FK to `chapters`, `ON DELETE SET NULL`. |
| current_segment_id | TEXT | Nullable. FK to `segments`, `ON DELETE SET NULL`. |
| position_ms | INTEGER | `NOT NULL DEFAULT 0` |
| speed | REAL | `NOT NULL DEFAULT 1.0 CHECK (0.25 <= speed <= 4.0)` |
| updated_at | TEXT | `NOT NULL DEFAULT CURRENT_TIMESTAMP` |

Soft-close (the mini-player × button) keeps the row but sets `chapter_id = NULL` so Continue Listening can still surface a "last listened" anchor for the project.

#### Chapter assembly cache (`chapter_assemblies`)

Added in schema v7. A disk+DB cache of ffmpeg-concatenated chapter audio — one row per chapter that has at least one successful assembly.

| Column | Type | Notes |
|---|---|---|
| chapter_id | TEXT | PK. FK to `chapters`, `ON DELETE CASCADE`. |
| audio_path | TEXT | Absolute path to the cached WAV (`data/projects/<id>/audio/assembled/<chapter_id>.wav`). |
| duration_ms | INTEGER | From ffprobe after concat + transcode. |
| segment_hash | TEXT | SHA-256 of sorted `(segment_id, updated_at, audio_path, approved_at)` tuples. Cache invalidation key. |
| created_at | TEXT | `NOT NULL DEFAULT CURRENT_TIMESTAMP` |

Invalidation happens automatically on any segment generate/regenerate/approve/reject (see `docs/ASSEMBLY-NOTES.md`).

### 9.8 `jobs`
| Column | Type | Notes |
|---|---|---|
| id | TEXT | PK |
| project_id | TEXT | FK |
| type | TEXT | `extract_characters`/`attribute_chapter`/`auto_cast`/`generate_chapter`/`assemble_chapter`/`generate_cover`/etc. |
| payload | TEXT (JSON) | |
| status | TEXT | `queued`/`running`/`awaiting_response`/`complete`/`failed` — `awaiting_response` is used by the file-drop LLM integration (§12A) between rendering the prompt and parsing the JSON response |
| progress | INTEGER | 0–100 |
| estimated_duration_ms | INTEGER | |
| estimated_cost_usd | REAL | |
| actual_cost_usd | REAL | |
| created_at, started_at, completed_at | TEXT | |
| error | TEXT | |

---

## 10. Claude NLP Passes

Prompts live in `backend/nlp/prompts/` as editable `.md` files. Each is versioned; tuning does not require code changes.

### 10.1 Pass 1 — Cast Extraction (Opus)
Input: Full book text (chunked if needed). Output: JSON cast list with attributes.

### 10.2 Pass 2 — Auto-Casting (Opus)
Input: Cast list + voice library. Output: Voice assignments with reasoning.

### 10.3 Pass 3 — Pronunciation Survey (Sonnet)
Input: Cast + book sample for unusual words. Output: Phonetic overrides. User accepts/edits.

### 10.4 Pass 4 — Chapter Attribution (Sonnet, Opus fallback)
Input: One chapter + cast. Output: Ordered segments with speaker, render_mode, emotion_tags, confidence.

### 10.5 Pass 5 — Special Content Detection (Sonnet)
Input: Chapter text. Output: Ranges that are epigraphs/letters/poetry/etc. Often merged with Pass 4 in practice but can be split when attribution accuracy drops.

### 10.6 Pass 6 — Ambient Scene Tagging (Sonnet, optional)
Input: Chapter text. Output: Suggested scene tags for ambient backing (tavern, forest, storm, battle, ship, castle, etc.) with time ranges. Feeds into §11.

**Prompt files delivered separately after spec approval.**

---

## 11. Ambient Soundscapes

Scene-level ambient audio layered under narration. Per-beat SFX deferred to post-v1.

### 11.1 How It Works
- `backend/ambient/` holds user-supplied CC0 or licensed ambient tracks, one per scene tag
- Claude tags chapters (or sub-chapter ranges) with ambient scene tags
- During assembly, pydub layers the ambient at ~-24 dB under the narration
- Crossfades between scenes handled automatically
- User can disable ambient per project or per chapter

### 11.2 Scene Tag Vocabulary (starter set)
`tavern`, `forest_day`, `forest_night`, `storm`, `battle`, `castle_interior`, `castle_exterior`, `ship_deck`, `ocean`, `city_market`, `dungeon`, `cave`, `desert`, `snow`, `fire_crackling`, `quiet_room`, `court_hall`, `wilderness_wind`

### 11.3 Where Tracks Come From
- Freesound.org (CC0 or attribution)
- Internet Archive
- User's own recordings
- Ship Chorus with a curated starter pack of CC0 tracks referenced by tag

### 11.4 Opt-Out
Ambient is on by default but trivially disabled per project. Some listeners hate it; the option respects that.

---

## 12. Voicebox Integration

### 12.1 Assumptions
- Voicebox runs separately on the same Mac
- Default URL `http://localhost:8090` (configurable via `VOICEBOX_BASE_URL`). The default port is `8090` rather than Voicebox's upstream `5173` to avoid collisions with Vite (`5173`) and the Chorus backend (`8765`) when all three run on one Mac. Users running Voicebox at its upstream default should set `VOICEBOX_BASE_URL=http://localhost:5173`.
- Pre-flight check on Chorus startup: confirm Voicebox is reachable
- Display clear error if not: "Chorus requires Voicebox running locally. Install from https://github.com/jamiepine/voicebox"

### 12.2 Expected Endpoints (to verify against real API before coding)

| Purpose | Route | Notes |
|---|---|---|
| List profiles | `GET /api/profiles` | |
| Create profile | `POST /api/profiles` | multipart |
| Generate speech | `POST /api/generate` | `{text, profile_id, engine, effects?}` |
| Check status | `GET /api/generations/{id}` | |
| Download audio | `GET /api/generations/{id}/audio` | |

**Pre-Phase-0 action:** Clone Voicebox, run `just dev`, hit its `/docs` endpoint, update this section with the real API surface.

### 12.3 Engine Selection Strategy

| Engine | Primary Use |
|---|---|
| **Chatterbox Turbo** | Default — best paralinguistic tags, English |
| **Qwen3-TTS** | Fallback / non-English passages / neutral delivery |
| **HumeAI TADA** | Songs, highly emotional scenes |
| **LuxTTS / Chatterbox Multilingual** | Language coverage edge cases |

### 12.4 Concurrency
Start at 2 parallel workers. Measure on real hardware before committing. Expose as a config setting.

---

## 12A. LLM Integration — File-Drop Mode

For initial development (and through at least v1), Chorus does **not** call the Anthropic API directly. Instead, when a Claude-driven pass is triggered, Chorus renders the prompt to disk and waits for a companion Claude Code session to answer it. This lets development run against a Claude Code subscription instead of paying per-API-call for prompt iteration.

### 12A.1 Mechanism

1. **Render.** When a pass starts, Chorus renders the full prompt with all inputs substituted in (cast list JSON, chapter text, voice library, etc.) — the same text Claude would receive via the API.
2. **Queue.** The rendered prompt is written to:
   ```
   data/llm_queue/pending/request_<id>.md
   ```
   where `<id>` is the corresponding `jobs.id`.
3. **Mark the job as `awaiting_response`** (§9.8). The project UI surfaces this state so the user knows Chorus is waiting on Claude Code.
4. **Watch.** A file watcher polls `data/llm_queue/responses/` for `response_<id>.json`.
5. **Ingest.** When a response appears, Chorus parses the JSON, associates it with the job by `id`, advances the project state (cast extracted / chapter attributed / etc.), and marks the job `complete`. On parse failure, the job is marked `failed` with the parse error; the user can re-drop a fixed response file to retry.

### 12A.2 The companion Claude Code session

The user runs Claude Code in a parallel window with this standing instruction:

> Watch `data/llm_queue/pending/` for new `request_*.md` files. For each, execute the prompt inside and write the resulting JSON (exact shape defined inside the prompt) to `data/llm_queue/responses/response_<id>.json` with the matching `<id>`. Then move the request file from `pending/` to `data/llm_queue/completed/`.

This is the ONLY LLM integration for Phase 3 onward. Do not implement direct Anthropic API calls yet.

### 12A.3 Post-v1 API mode

The architecture anticipates a future where Chorus calls Anthropic directly, for users without a Claude Code subscription or for unattended batch runs:

- Feature flag: `LLM_MODE` ∈ {`file_drop`, `api`}, **defaulting to `file_drop`**.
- In `api` mode, the same rendered prompt is sent to the Anthropic SDK and the response is ingested inline, skipping the `awaiting_response` state.
- Prompt rendering, schema validation, and job bookkeeping are identical across modes — only the transport differs.

This is architecturally anticipated only; the `api` path is not implemented in v1.

### 12A.4 Why this design

- **Cost alignment.** Ben already pays for Claude Code; adding per-call Anthropic charges during prompt iteration would double-bill.
- **Prompt iteration speed.** The `.md` files in `pending/` and `responses/` are human-readable artifacts — easy to inspect, re-run, or hand-fix without touching Chorus code.
- **Debuggability.** Every LLM interaction leaves a file-level audit trail in `completed/` plus the persisted response JSON.
- **Clean future switch.** Because the prompt is already rendered to a string and the response is already parsed from JSON, promoting to `api` mode is a transport swap, not a pipeline rewrite.

---

## 13. Cost & Time Estimation

### 13.1 Upfront Estimator

Before any LLM-driven pass, Chorus shows:

```
┌─────────────────────────────────────────┐
│ Estimated Production                    │
├─────────────────────────────────────────┤
│ Book length:   298,000 words            │
│ Chapters:      73                       │
│ Est. characters: ~30 speaking           │
│                                         │
│ LLM calls:     ~85 passes               │
│ API cost est:  $14.20 (Sonnet+Opus mix) │
│                                         │
│ Audio chunks:  ~6,400 segments          │
│ Gen time est:  ~3h 40m                  │
│                                         │
│ Disk usage:    ~380 MB                  │
│                                         │
│ [ Start ]  [ Cancel ]                   │
└─────────────────────────────────────────┘
```

### 13.2 Live Tracking
- Job queue shows per-job ETA
- Running cost counter on the project view
- macOS notification on completion or failure

### 13.3 Cost Guardrails
- Per-project budget cap (default $25)
- Warning at 80% of cap
- Hard stop at 120% of cap with resume option

### 13.4 Claude Code Dev Mode
For development iteration, Chorus supports a "Claude Code" mode where NLP passes are stubbed out and the user pastes in Claude Code outputs manually. This lets Ben iterate without burning API credits during initial development.

---

## 13A. Audio File Layout (Assembly Inputs)

Per-segment TTS output lives under the project's data directory in two parallel
trees:

- `data/projects/<project_id>/audio/raw/<chapter_id>/segment_<segment_id>.<ext>` — canonical raw output. Every successful generation writes here.
- `data/projects/<project_id>/audio/approved/<chapter_id>/segment_<segment_id>.<ext>` — the operator-approved subset used by assembly. Populated by the Approve action (copies raw → approved; raw is preserved so Reject/Regenerate can fall back without re-running TTS).

Phase 8 (assembly) prefers `approved/` and falls back to `raw/` **only when
explicitly configured**. Default behavior is "approved or nothing" so
unreviewed segments don't sneak into the final mix.

`<ext>` is sniffed from Voicebox's `Content-Type` response header
(`audio/wav` → `.wav`, `audio/mpeg` → `.mp3`, `audio/flac` → `.flac`,
`audio/ogg` → `.ogg`). Unknown Content-Types fall back to `.wav` with a
warning log. See `docs/GENERATION-GUIDE.md` for operator-level detail and
`backend/audio/paths.py` for the path helper.

---

## 14. Cover Art Generation

One image per project, generated from the book's setting and theme.

### 14.1 Flow
1. Claude generates an art prompt from book metadata + opening chapter
2. User reviews/edits prompt (or skips the gate if they trust it)
3. Image model produces cover
4. Stored at `data/projects/<slug>/cover.png`
5. Embedded in M4B metadata for in-player display

### 14.2 Image Model Options
- DALL-E 3 (via OpenAI API) — default for reliability
- Flux (via Replicate) — richer output
- Stability AI SDXL (via Replicate)

### 14.3 Prompt Seed Template
```
A book cover illustration for "{title}" by {author}. 
Genre: {genre}. Setting: {setting_summary}. 
Mood: {tonal_descriptors}. 
Style: painterly, atmospheric, no text. 2:3 aspect ratio.
```

---

## 15. UI / UX

Mobile-first, dark-mode primary, responsive down to 375px width (iPhone SE baseline).

### 15.1 View Map

| View | Route | Purpose |
|---|---|---|
| Library | `/` | Grid of projects |
| Project | `/project/:id` | Overview, actions, progress |
| Casting | `/project/:id/cast` | Cast with voice assignments |
| Voice Library | `/voices` | Browse, add, edit voices |
| Review | `/project/:id/chapter/:num` | Per-chapter attribution review gate |
| Player | `/project/:id/player` | Audiobook playback |
| Settings | `/settings` | API keys, default engine, paths |

### 15.2 Mobile-First Patterns
- Bottom navigation bar (Library / Player / Voices / Settings)
- Pull-to-refresh on library
- Large tap targets (min 44×44px)
- Swipe gestures: swipe between chapters in player, swipe to dismiss in review
- Inline media controls that don't require precise targeting

### 15.3 The Library
- Grid of cards: cover art, title, author, completion bar, last-played chapter
- Tap card → Project view
- "+ New Project" floating action button
- Sort: recently listened / recently completed / alphabetical
- Filter: completed / in progress / draft

### 15.4 The Project View
- Hero: cover art + title/author
- Status banner ("Generating... 23/73 chapters")
- Quick actions: Continue Listening, Open in Casting, Open in Review, Re-run Attribution
- Chapter list with per-chapter status
- Total runtime + file size

### 15.5 The Casting View
Two-pane on desktop, stacked on mobile:
- Pane A: Character cards (name, description, key traits, line count)
- Pane B: Currently selected character's voice assignment
  - Current voice with "Preview line" button
  - "Change voice" opens voice library modal
  - Engine override dropdown
  - Notes field for director intent

### 15.6 The Review View
Scrollable chapter with inline editing:
- Each segment is a tap-to-expand card
- Color-coded left border by character
- Confidence badge (red <70, yellow 70–84, green 85+ — production feedback showed many chapters hover in the 85–89 band with correct attribution; tightening the "green" threshold to 90 flagged too much as medium-confidence and added review noise. The implementation single-sources this in `frontend/src/lib/constants.ts::CONFIDENCE`.)
- Expand: speaker dropdown, emotion tag chips, render mode selector, "Generate preview"
- Bulk action: "Approve all segments above 90% confidence" (deferred to Phase 5 — needs TTS to have anything to approve for)

### 15.7 The Player
- Cover art at top (tap for full-screen)
- Title / Author / Current chapter
- Scrub bar with chapter markers visible
- Play/pause, skip 30s, chapter prev/next
- Speed: 0.75x / 1x / 1.25x / 1.5x / 2x
- Sleep timer: 5 / 15 / 30 / 60 min / end of chapter
- "Jump to transcript" opens transcript pane with current segment highlighted
- Offline export: "Send to Files" / "Share M4B"

### 15.8 Design Tokens

| Role | Value |
|---|---|
| Background | `#0A0A0B` |
| Surface | `#141416` |
| Border | `#2A2A2E` |
| Primary | `#FAFAFA` |
| Secondary | `#9A9AA0` |
| Accent (Chorus teal) | `#4EC8BE` |
| Warn | `#F59E0B` |
| Error | `#EF4444` |
| Success | `#10B981` |

Type: **Playfair Display** (titles, cover-art), **Inter** (UI), **JetBrains Mono** (technical/debug).

---

## 16. API Surface

All JSON, prefixed `/api`. Progress updates via SSE at `/api/events`.

### Projects
- `GET /projects`
- `POST /projects` (upload)
- `GET /projects/{id}`
- `DELETE /projects/{id}`
- `PATCH /projects/{id}` (settings: POV toggle, ambient toggle)
- `POST /projects/{id}/pause` — pauses any long-running generation job
- `POST /projects/{id}/resume`
- `GET /projects/{id}/cost`

### Ingestion
- `POST /projects/{id}/ingest` (multipart)
- `POST /projects/{id}/detect-chapters`

### Characters
- `POST /projects/{id}/extract-cast`
- `GET /projects/{id}/characters`
- `PATCH /characters/{id}`
- `POST /characters/{id}/preview`
- `POST /projects/{id}/auto-cast`

### Voices
- `GET /voices`
- `POST /voices`
- `PATCH /voices/{id}`
- `DELETE /voices/{id}`
- `POST /voices/{id}/sample`

### Chapters & Segments
- `GET /projects/{id}/chapters`
- `POST /chapters/{id}/attribute`
- `GET /chapters/{id}/segments`
- `PATCH /segments/{id}`
- `POST /chapters/{id}/generate`
- `POST /chapters/{id}/assemble`

### Export
- `POST /projects/{id}/export` (M4B)
- `GET /projects/{id}/export/{chapter}/mp3`
- `GET /projects/{id}/cover`
- `POST /projects/{id}/cover/generate`

### Playback
- `GET /projects/{id}/audio/manifest`
- `GET /projects/{id}/chapter/{num}/stream`
- `POST /projects/{id}/playback-state`

### Jobs
- `GET /jobs/{id}`
- `GET /projects/{id}/jobs`
- `POST /jobs/{id}/cancel`

### System
- `GET /health`
- `GET /voicebox/status`
- `GET /settings`
- `PATCH /settings`

---

## 17. Build Phases

Each phase has a hard exit criterion. Do not advance until it's met.

### Phase 0 — Foundation (Day 1)
- Repo init, venv, Vite scaffold, Tailwind setup
- FastAPI skeleton with health check
- SQLite schema migration system
- Voicebox API verification script
- Anthropic API verification script
- `scripts/run.sh` starts backend + frontend dev, opens browser, advertises mDNS

**Exit:** `http://chorus.local:8765/api/health` returns OK from phone on same WiFi.

### Phase 1 — Ingestion + Library (Days 2–3)
- TXT upload + naive chapter detection
- EPUB upload via `ebooklib`
- Claude-based chapter detection fallback for unclear cases
- Library view, project creation flow
- Project view shell

**Exit:** Drop AGoT EPUB, see it parsed into 73 chapters with correct titles.

### Phase 2 — Voice Library (Days 4–5)
- Voice library CRUD
- Metadata schema + migrations
- Voicebox profile creation integration (clone from mic or upload)
- Voice library UI (grid, filter by pool, preview, edit)

**Exit:** Add 5 voices via UI (including one from mic), confirm they persist and preview plays from phone.

### Phase 3 — Cast Extraction + Auto-Casting (Days 6–7)
- `extract_cast.md` prompt, tuned on AGoT chapter 1–3
- `auto_cast_voices.md` prompt
- Cast view UI
- Auto-casting flow with review/override

**Exit:** Extract AGoT cast via file-drop LLM integration (§12A), auto-cast from voice library, manually inspect assignments are sensible.

### Phase 4 — Attribution + Special Content (Days 8–10)
- `attribute_chapter.md` prompt (with render_mode + emotion tags)
- `detect_special_content.md` prompt
- Review UI with inline editing
- Confidence-based highlighting
- Pronunciation override UI

**Exit:** Attribute a full AGoT chapter; spot-check shows ≥95% correct attribution after review.

### Phase 5 — Audio Generation (Days 11–13)
- Segment generator with engine routing
- Emotion tag injection
- Pronunciation substitution
- Parallel worker pool with ETA estimator
- SSE progress events

**Exit:** Generate audio for one full AGoT chapter with full theatrical treatment. **Status: met for Windows dev** — UI is operable end-to-end; the generation path is fully built and disabled behind the `VOICEBOX_ENABLED` flag. Mac + live Voicebox validation (the "real" exit) is pending the first Mac run — the flip is env-only, no code changes. See `docs/GENERATION-GUIDE.md` and `docs/VOICEBOX-WIRING.md`.

### Phase 6 — Assembly + Ambient + Player (Days 14–16)
- FFmpeg assembly pipeline
- Loudness normalization
- Ambient soundscape mixing with pydub
- POV narrator switching
- M4B export with chapter markers
- In-app player UI (mobile-first)
- Playback state tracking

**Exit:** Playable M4B of a full AGoT chapter, works on phone via LAN. **Status: met for Windows dev** — assembly pipeline (ffmpeg concat + transcode + SHA-256 cache), full Player UI (desktop 3-column + mobile single-column with synced-text bottom sheet), persistent mini-player, Continue Listening, playback state persistence, and auto-advance are all operable end-to-end against silent placeholder audio (`scripts/generate_placeholder_audio.py`). Loudness normalization, ambient soundscape mixing, POV narrator switching, and M4B export ride with Mac + live-Voicebox validation (the "real" exit). See `docs/PLAYER-GUIDE.md` and `docs/ASSEMBLY-NOTES.md`.

### Phase 7 — Cover Art + Polish (Days 17–18)
- Cover art generation
- End-to-end review-gated workflow polish (clear stage transitions, skip-gate affordance, resume across restarts)
- Cost estimator + live tracking
- Notifications on completion
- Error recovery (retry failed segments/chapters)

**Exit:** Drop in a short book, walk it through every review gate (cast → casting → pronunciation → attribution → generation → assembly), return a finished audiobook with cover art.

### Phase 8 — Full Book Run + Bug Bash (Days 19–20+)
- Run full AGoT end-to-end
- Triage and fix every issue encountered
- Performance tuning
- README + setup docs for eventual open-source

**Exit:** A listenable AGoT audiobook exists on the phone.

---

## 18. Open Decisions

Items marked for discussion before or during implementation:

1. **Final project name.** Chorus is working; Bard, Dotrice, Prologue in contention.
2. **Image model.** DALL-E 3 is most reliable; Flux produces richer cover art. Try both during Phase 7.
3. **Ambient track licensing.** Ship with CC0 starter pack vs. user-supplied only. Starter pack is friendlier for open-source distribution.
4. **Claude Code fallback mechanism.** Probably a textarea + parse button is enough.
5. **Voice cloning consent flow.** One-time acknowledgment on first clone vs. per-voice checkbox.
6. **Thought/internal monologue default.** Narrator voice with subtle filter OR character voice? Likely a setting with narrator default.
7. **Mobile PWA offline caching.** How aggressive for on-the-go listening off home WiFi.
8. **Sound effects beyond ambient.** Scope-creep trap. Defer to post-v1 unless Phase 6 comes in ahead.

---

## 19. Success Criteria for v1

1. **The AGoT test:** Drop *A Game of Thrones* EPUB into Chorus and walk it through every review gate (cast → casting → pronunciation → attribution → generation → assembly). Return a finished M4B with cover art, ambient beds, distinct character voices, and theatrical delivery. Cost < $25. Time < 8 hours of active + wait time.
2. **The phone test:** Listen to a chapter on the phone over LAN, scrub, speed up to 1.5x, resume next day at the same position.
3. **The quality test:** 10 random minutes of audio listened to with eyes closed. Character voices distinguishable. No mispronunciations of major names. Emotional beats land. Ambient layer enhances, doesn't distract.
4. **The director test:** At the casting gate, reassign 3 voices and continue. At the attribution gate on one chapter, fix 5 low-confidence segments and continue. Output reflects both changes.
5. **The polish test:** An engineer friend opens the app, uses it without hand-holding, produces something listenable. No crashes, no cryptic errors.

---

## 20. Post-v1 Roadmap (Architecturally Anticipated)

- **Translation:** Source book in Japanese → translated to English → voiced in English. New pipeline stage between ingestion and attribution.
- **Per-beat sound effects:** Door slam, sword clash, thunder. Claude pass identifies moments + SFX library.
- **Multi-book series:** Persistent cast across books with voice continuity.
- **Community voice library:** Shared voices with metadata, user-moderated, attribution-respecting.
- **Segment-level regeneration:** Post-hoc fix of single lines.
- **Native iOS app via PWA → Capacitor:** Truly offline listening.
- **Adaptive pacing:** Tense scenes faster, contemplative slower, auto-detected.
- **Character voice evolution:** Same character at age 10 vs. 40 → automatic pitch/timbre drift.
- **Podcast / fanfic / screenplay import:** New ingesters.

---

## 21. Development Workflow

### Startup
1. `scripts/setup.sh` — venv, pip install, npm install, DB migrate
2. Ensure Voicebox is running separately (Chorus checks on startup)
3. `scripts/run.sh` — Starts FastAPI on `0.0.0.0:8765`, Vite dev on `:5174` proxied through FastAPI, advertises mDNS as `chorus.local`, opens browser
4. Keep-awake helper runs in background if generation jobs are active

### Dual-Claude Workflow
- **This spec** lives at repo root as `CHORUS-SPEC.md`; source of truth
- **claude.ai (here)** — design decisions, prompt iteration, architecture debates
- **Claude Code** — implementation phase-by-phase, reference this spec by section
- Prompts in `backend/nlp/prompts/` are versioned; update spec when they change materially

### Claude Code Notes
- Each phase in §17 becomes a plan in Claude Code
- Write tests for Claude-based outputs (mock JSON responses) so you can iterate prompts without API cost
- The `claude-mem` plugin helps with session continuity across phases
- Use `/compact` at natural break points

### Commit Hygiene
- Commit after each phase exit criterion is met
- Tag phase completions (`v0.1-phase3` etc.)
- Prompt changes get their own commits for easy revert

---

## 22. Appendix

### A. Useful References
- Voicebox: `https://github.com/jamiepine/voicebox`
- Voicebox landing: `https://voicebox.sh`
- Chatterbox Turbo paralinguistic tags: `[laugh] [chuckle] [gasp] [cough] [sigh] [groan] [sniff] [shush] [clear_throat]`
- Project Gutenberg (test books): `https://www.gutenberg.org`
- LibriVox (public-domain voice sources): `https://librivox.org`
- Freesound (ambient tracks): `https://freesound.org`
- FFmpeg M4B chapter format: `https://ffmpeg.org/ffmpeg-formats.html#Metadata-1`
- `ebooklib`: `https://pypi.org/project/EbookLib/`
- Anthropic API docs: `https://docs.claude.com`

### B. Glossary
- **Pass:** One Claude-driven operation with a structured prompt and a structured output. In v1 this is a file-drop exchange (§12A); in a future `api` mode it is a direct Anthropic SDK call.
- **Segment:** Smallest audio generation unit — one speaker, one utterance
- **Render mode:** How a segment is treated stylistically (prose / dialogue / epigraph / etc.)
- **Pool:** Voice library grouping (main / background / narrator)
- **POV Narrator:** Narration in a chapter uses the voice of the chapter's point-of-view character
- **Review gate:** An explicit stage in the workflow (cast, casting, pronunciation, attribution, generation) where Chorus pauses and the user confirms before advancing.
- **File-drop integration:** Chorus's v1 LLM transport — prompts rendered to `data/llm_queue/pending/`, responses read from `data/llm_queue/responses/` (§12A).

---

## 23. Revision History

- **v0.3 (2026-04-18)** — Removed Automated Mode; added file-drop LLM integration (§12A). Driven by personal-use scope and Claude Code subscription alignment.
  - Section 3 rewritten as "Review-Gated Workflow" (single flow, no mode switching).
  - `projects.mode` column dropped (§9.1 migration note).
  - Added `awaiting_response` status to `jobs.status` (§9.8).
  - New §12A — file-drop LLM integration mechanism, Claude Code companion instruction, future `LLM_MODE=api` flag.
  - `data/llm_queue/{pending,responses,completed}/` added to §5.4 directory layout.
  - `POST /projects/{id}/start` removed from §16; pause/resume retained for long-running generation jobs.
  - §13.1 estimator reframed: triggered before any LLM-driven pass (not before an "Automated Mode run").
  - §17 Phase 3 exit references file-drop explicitly; Phase 7 rewritten around review gates.
  - §19 success criteria 1 and 4 rewritten to reflect the single review-gated flow.
  - §22 glossary: removed Director/Automated Mode; added Review gate + File-drop integration.
- **v0.2 (2026-04-16)** — Vision-alignment pass. Superseded by v0.3.
- **v0.1** — Initial spec draft.

---

*End of spec v0.3. Update as implementation reveals constraints.*
