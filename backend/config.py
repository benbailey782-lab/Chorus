from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    # Empty default = unconfigured. Voicebox v0.4.0 picks a runtime port on
    # launch (printed in its own UI + /health), so hardcoding a guess was
    # wrong — the operator sets the URL via VOICEBOX_BASE_URL env var OR
    # via the Settings UI (which persists to data/voicebox_config.json and
    # takes precedence at read time, see voicebox_config_store.get_effective).
    voicebox_base_url: str = ""
    voicebox_enabled: bool = False
    voicebox_timeout_seconds: int = 120
    voicebox_default_wps: float = 2.5  # words per second for time estimates
    voicebox_output_sample_rate: int = 44100
    # Forward-compat: Phase 5 runs serial; when Voicebox proves stable on Mac we can bump to 2+.
    voicebox_max_concurrent_generations: int = 1

    host: str = "0.0.0.0"
    port: int = 8765

    data_dir: str = "./data"
    db_path: str = "./data/chorus.db"

    mdns_name: str = "chorus"

    log_level: str = "INFO"

    claude_model_opus: str = "claude-opus-4-7"
    claude_model_sonnet: str = "claude-sonnet-4-6"

    max_voice_sample_mb: int = 25

    # Phase 3 — file-drop LLM integration (§12A).
    # Hard-cap on book-text substituted into extract_cast.md before truncation
    # kicks in; truncation surfaces as a warning in the extract-cast API
    # response and in the UI confirmation modal.
    extract_cast_char_limit: int = 300_000

    @property
    def voicebox_configured(self) -> bool:
        """True iff a non-empty base URL has been provided via env.

        NOTE: this reflects env-only state. For the *effective* URL (which
        also considers the runtime-writable ``data/voicebox_config.json``
        override), call ``voicebox_config_store.get_effective()`` instead.
        """
        return bool(self.voicebox_base_url.strip())

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).resolve()

    @property
    def projects_path(self) -> Path:
        return self.data_path / "projects"

    @property
    def voice_library_path(self) -> Path:
        return self.data_path / "voice_library"

    @property
    def voice_samples_path(self) -> Path:
        return self.voice_library_path / "samples"

    @property
    def max_voice_sample_bytes(self) -> int:
        return self.max_voice_sample_mb * 1024 * 1024

    @property
    def llm_queue_path(self) -> Path:
        return self.data_path / "llm_queue"

    @property
    def llm_queue_pending_path(self) -> Path:
        return self.llm_queue_path / "pending"

    @property
    def llm_queue_responses_path(self) -> Path:
        return self.llm_queue_path / "responses"

    @property
    def llm_queue_completed_path(self) -> Path:
        return self.llm_queue_path / "completed"

    def ensure_dirs(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.projects_path.mkdir(parents=True, exist_ok=True)
        self.voice_library_path.mkdir(parents=True, exist_ok=True)
        self.voice_samples_path.mkdir(parents=True, exist_ok=True)
        self.llm_queue_pending_path.mkdir(parents=True, exist_ok=True)
        self.llm_queue_responses_path.mkdir(parents=True, exist_ok=True)
        self.llm_queue_completed_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
