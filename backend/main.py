import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import mdns
from backend.api import (
    assembly as assembly_api,
    characters,
    generation,
    health,
    jobs as jobs_api,
    playback as playback_api,
    projects,
    pronunciations,
    segments,
    voicebox,
    voices,
)
from backend.config import get_settings
from backend.db import init_db
from backend.jobs import worker as job_worker
# Import handlers so their @register_handler decorators fire before the worker starts.
from backend.audio import assembly as _audio_assembly  # noqa: F401
from backend.audio import generation as _audio_generation  # noqa: F401
from backend.nlp import attribute_chapter as _attribute_chapter  # noqa: F401
from backend.nlp import auto_cast as _auto_cast  # noqa: F401
from backend.nlp import extract_characters as _extract_characters  # noqa: F401
from backend.nlp import pronounce_unusual_handler as _pronounce_unusual  # noqa: F401
from backend.nlp import file_drop
from backend.voices.voicebox_client import probe as probe_voicebox

APP_VERSION = "0.1.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("chorus")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    try:
        mdns.advertise(settings.mdns_name, settings.port)
    except Exception as e:
        log.warning("mDNS advertisement failed: %s", e)

    # Voicebox preflight — never fails hard. Windows dev runs with
    # VOICEBOX_ENABLED=false; the UI surfaces the same note to users.
    try:
        vb_status = await probe_voicebox(settings)
        if vb_status.enabled and vb_status.reachable:
            log.info("Voicebox reachable at %s", vb_status.base_url)
        elif vb_status.enabled:
            log.warning(
                "Voicebox enabled but unreachable at %s — TTS calls will fail at runtime. %s",
                vb_status.base_url, vb_status.note,
            )
        else:
            log.info(
                "Voicebox not configured (VOICEBOX_ENABLED=false) — voice generation features disabled."
            )
    except Exception as e:  # noqa: BLE001 — preflight must never crash startup
        log.warning("Voicebox preflight raised unexpectedly: %s", e)

    # File-drop LLM queue preflight (§12A). Surfaces current queue state so
    # the operator knows whether there's work already sitting around.
    try:
        queue_state = await file_drop.scan_queue()
        log.info(
            "File-drop queue at %s (pending=%d, responses=%d, completed=%d). Handlers: %s",
            settings.llm_queue_path,
            len(queue_state["pending"]),
            len(queue_state["responses"]),
            len(queue_state["completed"]),
            ", ".join(job_worker.registered_kinds()) or "(none)",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("File-drop queue preflight failed: %s", e)

    # Start the response worker. It runs until shutdown.
    worker_handle = job_worker.start()

    log.info("Chorus backend ready on %s:%d", settings.host, settings.port)
    try:
        yield
    finally:
        await worker_handle.stop()
        mdns.stop()


app = FastAPI(title="Chorus", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(voices.router)
app.include_router(voicebox.router)
app.include_router(characters.router)
app.include_router(jobs_api.router)
app.include_router(segments.router)
app.include_router(pronunciations.router)
app.include_router(generation.router)
app.include_router(assembly_api.router)
app.include_router(playback_api.router)
