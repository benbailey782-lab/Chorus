# scripts/

Utility scripts shipped alongside the Chorus backend. Run from the repo root
with the project venv active (see the top-level `CLAUDE.md`).

| Script                         | Purpose                                                                                       |
|---|---|
| `run.sh` / `run.bat`           | One-shot dev launcher: installs deps, runs the FastAPI backend + Vite frontend.               |
| `verify_anthropic.py`          | Confirms `ANTHROPIC_API_KEY` is set and a basic Messages call works.                          |
| `verify_voicebox.py`           | Pings Voicebox at `VOICEBOX_BASE_URL` — warns (does not fail) when absent.                    |
| `generate_placeholder_audio.py`| **Dev aid, Windows-only workflow.** Writes silent WAVs per segment so the Phase 6 player works without Voicebox. See `docs/GENERATION-GUIDE.md`. |
