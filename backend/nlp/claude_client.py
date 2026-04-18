from functools import lru_cache
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from backend.config import get_settings

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache
def get_client() -> Optional[Anthropic]:
    key = get_settings().anthropic_api_key
    if not key:
        return None
    return Anthropic(api_key=key)


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
