"""Backend entry point for development.

Canonical way to start the Chorus FastAPI server. On Windows this MUST be used
instead of `uvicorn backend.main:app --reload` because:

1. Uvicorn creates the asyncio event loop before `backend/main.py` is imported,
   so any policy switch inside that module arrives too late.
2. Uvicorn's `Config.use_subprocess` property forces `SelectorEventLoop`
   whenever `reload=True` — even in the child worker that actually runs the
   app. `SelectorEventLoop` on Windows doesn't support
   `asyncio.create_subprocess_exec`, which the ffmpeg-based chapter assembly
   pipeline relies on.

This script:
  1. Adds the project root to sys.path (and PYTHONPATH so multiprocessing-spawn
     children inherit it).
  2. Sets WindowsProactorEventLoopPolicy BEFORE uvicorn is imported.
  3. Uses `backend._uvicorn_shim.ProactorConfig` — a Config subclass that
     overrides `get_loop_factory()` to always return ProactorEventLoop on
     Windows. The subclass pickles cleanly into the reload child, so both
     parent and worker use Proactor.
  4. Runs the reload supervisor directly (`ChangeReload`) instead of
     `uvicorn.run()`, so we can inject our Config subclass.

Mac/Linux: the policy swap is skipped and `ProactorConfig.get_loop_factory()`
falls through to the upstream factory. Behavior is identical to stock uvicorn.

Note on Python 3.14+: `set_event_loop_policy` is deprecated (removal in 3.16).
Uvicorn 0.44 still uses the policy-driven loop creation, so this remains the
least-surprise shim. We suppress the DeprecationWarning for now.
"""

import os
import sys
from pathlib import Path

# 1. Make the project root importable by BOTH the parent serve.py process
#    and any multiprocessing-spawn children that uvicorn's reload supervisor
#    creates. Without this, child spawn processes fail with
#    `ModuleNotFoundError: No module named 'backend'` when unpickling the
#    ProactorConfig instance.
ROOT = Path(__file__).resolve().parent.parent
_root_str = str(ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)
_existing = os.environ.get("PYTHONPATH", "")
if _root_str not in _existing.split(os.pathsep):
    os.environ["PYTHONPATH"] = os.pathsep.join([_root_str, _existing]) if _existing else _root_str

import asyncio  # noqa: E402
import warnings  # noqa: E402

# 2. Windows: swap in Proactor loop policy so `asyncio.new_event_loop()` gives
#    a Proactor loop. Belt-and-braces: `ProactorConfig` also forces it via the
#    loop factory, but this covers other async code paths.
if sys.platform == "win32":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


if __name__ == "__main__":
    import uvicorn  # noqa: E402 — must come AFTER the policy switch above
    from backend._uvicorn_shim import ProactorConfig  # noqa: E402

    config = ProactorConfig(
        "backend.main:app",
        host="0.0.0.0",
        port=8765,
        reload=True,
        loop="asyncio",
    )

    server = uvicorn.Server(config)

    if config.should_reload:
        from uvicorn.supervisors import ChangeReload

        sockets = [config.bind_socket()]
        ChangeReload(config, target=server.run, sockets=sockets).run()
    else:
        server.run()
