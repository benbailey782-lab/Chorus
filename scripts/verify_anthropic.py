import os
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    from anthropic import Anthropic
except ImportError:
    print("anthropic package not installed. run: pip install -r requirements.txt")
    sys.exit(1)

key = os.environ.get("ANTHROPIC_API_KEY", "")
if not key:
    print("ANTHROPIC_API_KEY not set in .env")
    sys.exit(1)

model = os.environ.get("CLAUDE_MODEL_SONNET", "claude-sonnet-4-6")
client = Anthropic(api_key=key)

try:
    resp = client.messages.create(
        model=model,
        max_tokens=16,
        messages=[{"role": "user", "content": "Reply with the single word: READY"}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    print(f"[ok] anthropic {model}: {text.strip()}")
except Exception as e:
    print(f"[fail] anthropic call failed: {e}")
    sys.exit(1)
