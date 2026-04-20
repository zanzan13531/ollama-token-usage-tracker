from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    mode: str = "proxy"  # "proxy" or "tracker"
    device_name: str = "default"
    tracker_url: str | None = None  # central tracker URL (proxy mode only)

    ollama_host: str = "http://localhost:11435"
    proxy_port: int = 11434
    db_path: str = "~/.ollama-tracker/usage.db"

    @model_validator(mode="after")
    def _normalize_urls(self) -> "Settings":
        """Auto-prefix http:// on URLs if missing."""
        if self.tracker_url and not self.tracker_url.startswith(("http://", "https://")):
            self.tracker_url = f"http://{self.tracker_url}"
        if self.tracker_url:
            self.tracker_url = self.tracker_url.rstrip("/")
        if not self.ollama_host.startswith(("http://", "https://")):
            self.ollama_host = f"http://{self.ollama_host}"
        return self

    @property
    def resolved_db_path(self) -> Path:
        return Path(self.db_path).expanduser()


settings = Settings()
