# Voicebox Wiring Checklist

Phase 2 of Chorus was built on Windows, where Voicebox isn't installed. Every
TTS call-site is stubbed — `VoiceboxClient` raises `VoiceboxNotEnabled` when
`VOICEBOX_ENABLED=false`. This doc is the punch-list for future you (or anyone)
who wires it up.

Before writing any client code: **run Voicebox, hit `/docs`, and verify each
endpoint's actual request/response shape matches what's assumed below.**
§12.2 of `CHORUS-SPEC.md` explicitly flags these endpoints as tentative.

## Config surface

`.env`:

```
VOICEBOX_BASE_URL=http://localhost:5173    # Voicebox dev default
VOICEBOX_ENABLED=true
```

When `VOICEBOX_ENABLED=true` but the server is down, startup still succeeds —
the preflight logs a warning and `/api/voices/voicebox/status` reports
`{enabled: true, reachable: false}`. The UI surfaces this via
`VoiceboxStatusBanner.tsx`.

## Wiring checklist

All stubs live in `backend/voices/voicebox_client.py`. Each method has a
`TODO(voicebox)` comment in the source with the endpoint and expected shapes
duplicated; this table is the same info in checklist form.

### 1. Probe (already live)

- **Method**: `backend/voices/voicebox_client.py:probe()`
- **Endpoint**: `GET {VOICEBOX_BASE_URL}/`
- **Purpose**: Lightweight reachability check. Returns `VoiceboxStatus`; never raises.
- **Wiring status**: **LIVE**. If Voicebox's root path is not reachable by GET,
  swap this to their real health endpoint (`/api/health` if one exists).

### 2. `list_profiles`

- **Method**: `backend/voices/voicebox_client.py:VoiceboxClient.list_profiles`
- **Endpoint**: `GET /api/profiles`
- **Request**: no body.
- **Expected response**: JSON array of profile objects. Per-profile shape:
  ```json
  {
    "id": "vb_abc123",
    "display_name": "Grizzled Northern Lord",
    "engine": "chatterbox_turbo",
    "created_at": "2026-04-17T20:15:00Z",
    "sample_url": "https://.../sample.wav"   // nullable
  }
  ```
- **Used by**: not wired into any Chorus flow yet. Exists for debugging and a
  future admin "reconcile with Voicebox" view.

### 3. `create_profile` — **MAIN WIRING POINT**

- **Method**: `backend/voices/voicebox_client.py:VoiceboxClient.create_profile`
- **Endpoint**: `POST /api/profiles` (multipart/form-data)
- **Request fields**:
  - `audio` — file part; WAV/MP3/FLAC/M4A/OGG; ≤ 25 MB.
  - `display_name` — string.
  - `metadata` — optional JSON string; we pass the §7.2 metadata dict so
    Voicebox can attach engine preferences to the clone.
- **Expected response**:
  ```json
  {
    "id": "vb_xyz456",          // <-- persist this on voices.voicebox_profile_id
    "display_name": "Grizzled Northern Lord",
    "engine": "chatterbox_turbo",
    "sample_url": "https://.../sample.wav",
    "created_at": "2026-04-17T20:15:00Z"
  }
  ```
- **Callers to wire**: two `TODO(voicebox)` comments in `backend/api/voices.py`:
  1. `POST /api/voices` — if audio was included in the multipart, call
     `create_profile` after the DB insert and `update_voice(id,
     {"voicebox_profile_id": profile["id"]})`.
  2. `POST /api/voices/{id}/sample` — when the reference audio is replaced on
     an existing voice, call `create_profile` again and overwrite
     `voicebox_profile_id`.

  Both call-sites already handle audio persistence; the wiring is "after the
  audio is on disk, call Voicebox with that path."

### 4. `generate`

- **Method**: `backend/voices/voicebox_client.py:VoiceboxClient.generate`
- **Endpoint**: `POST /api/generate`
- **Request body (JSON)**:
  ```json
  {
    "text": "Winter is coming.",
    "profile_id": "vb_xyz456",
    "engine": "chatterbox_turbo",    // optional; null = use profile default
    "effects": {                      // optional; render-mode-derived
      "reverb": 0.15,
      "pre_silence_ms": 500,
      "post_silence_ms": 1000,
      "paper_filter": true
    }
  }
  ```
- **Expected response**:
  ```json
  {
    "generation_id": "gen_789",
    "status": "queued" | "running" | "done" | "error",
    "progress": 0.0,
    "audio_url": null            // populated once status == "done"
  }
  ```
- **Callers to wire (Phase 5+)**:
  - Per-segment audio rendering in `backend/audio/renderer.py` (doesn't exist yet).
  - Voice-preview endpoint in voices API (`POST /api/voices/{id}/preview`
    taking `sample_text` and returning a short clip). Not yet implemented —
    current "preview" streams the reference audio instead.

### 5. `get_generation`

- **Method**: `backend/voices/voicebox_client.py:VoiceboxClient.get_generation`
- **Endpoint**: `GET /api/generations/{generation_id}`
- **Request**: no body.
- **Expected response**: same shape as `generate`'s response plus a possible
  `error` field when `status == "error"`.
- **Callers to wire (Phase 5)**: polling loop in `backend/jobs/queue.py`.

### 6. `download_generation_audio`

- **Method**: `backend/voices/voicebox_client.py:VoiceboxClient.download_generation_audio`
- **Endpoint**: `GET /api/generations/{generation_id}/audio`
- **Request**: no body.
- **Expected response**: binary audio (Content-Type: `audio/wav` or
  `audio/mpeg` — inspect the response header). Chorus writes this to
  `data/projects/<slug>/segments/<segment_id>.<ext>`.
- **Callers to wire (Phase 5)**: `backend/audio/renderer.py`.

## Verification on first real wire-up

1. Set `VOICEBOX_ENABLED=true` and point `VOICEBOX_BASE_URL` at the running
   Voicebox dev server.
2. `curl http://localhost:8765/api/voices/voicebox/status` → expect
   `reachable: true`.
3. Create a new voice via the UI with a reference audio file. Confirm:
   - `voices.voicebox_profile_id` is populated (check SQLite directly).
   - Voicebox's own admin lists the new profile.
4. If any field name or type above differs from reality, **update this doc
   first** before changing the client — it stays the source of truth for
   wiring expectations.

## If the endpoints differ from §12.2

Spec §12.2 is the design-time guess. If the real API uses different paths or
bodies:

1. Update `CHORUS-SPEC.md §12.2` with the verified shapes.
2. Update the `TODO(voicebox)` comments in `voicebox_client.py`.
3. Update this doc.
4. Only then rewrite the client methods — the comments should stop being
   "TODO" and become just docstrings.
