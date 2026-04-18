from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    voicebox_base_url: str = "http://localhost:5173"
    voicebox_enabled: bool = False

    host: str = "0.0.0.0"
    port: int = 8080

    data_dir: str = "./data"
    db_path: str = "./data/chorus.db"

    mdns_name: str = "chorus"

    log_level: str = "INFO"

    claude_model_opus: str = "claude-opus-4-7"
    claude_model_sonnet: str = "claude-sonnet-4-6"

    max_voice_sample_mb: int = 25

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

    def ensure_dirs(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.projects_path.mkdir(parents=True, exist_ok=True)
        self.voice_library_path.mkdir(parents=True, exist_ok=True)
        self.voice_samples_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
