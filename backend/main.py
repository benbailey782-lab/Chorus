import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import mdns
from backend.api import health, projects, voices
from backend.config import get_settings
from backend.db import init_db
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

    log.info("Chorus backend ready on %s:%d", settings.host, settings.port)
    try:
        yield
    finally:
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
