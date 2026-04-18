import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

base = os.environ.get("VOICEBOX_BASE_URL", "http://localhost:5173")

try:
    r = httpx.get(base, timeout=5)
    print(f"[ok] voicebox reachable at {base} (status {r.status_code})")
except Exception as e:
    print(f"[warn] voicebox not reachable at {base}: {e}")
    print("      this is expected if voicebox is not running yet — needed from phase 5 onward.")
    sys.exit(0)
