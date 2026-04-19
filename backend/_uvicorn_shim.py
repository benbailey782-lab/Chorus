"""Windows compatibility shim for uvicorn's event-loop selection.

Upstream uvicorn (0.44.x) forces `SelectorEventLoop` whenever `use_subprocess`
is True (i.e. `reload=True` or `workers > 1`). On Windows this breaks
`asyncio.create_subprocess_exec`, which the Phase 6 ffmpeg-based chapter
assembly relies on.

`ProactorConfig` inherits from `uvicorn.config.Config` and overrides
`get_loop_factory()` to always return `asyncio.ProactorEventLoop` on Windows,
regardless of the reload setting. Instances pickle correctly into the
multiprocessing-spawned child so the override survives the parent→child
transition used by uvicorn's reload supervisor.

Used by `scripts/serve.py`. Mac/Linux are unaffected — the override falls
through to the upstream factory.
"""
from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

from uvicorn.config import Config


class ProactorConfig(Config):
    """Config that forces ProactorEventLoop on Windows.

    Required because `asyncio.create_subprocess_exec` (used by
    `backend/audio/assembly.py`) is unimplemented on SelectorEventLoop, which
    is what uvicorn would otherwise pick when `reload=True`.
    """

    def get_loop_factory(self) -> Callable[[], asyncio.AbstractEventLoop] | None:  # type: ignore[override]
        if sys.platform == "win32":
            return asyncio.ProactorEventLoop
        return super().get_loop_factory()
