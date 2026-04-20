from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    mode: str = "proxy"  # "proxy" or "tracker"
    device_name: str = "default"
    tracker_url: str | None = None  # central tracker URL (proxy mode only)

    ollama_host: str = "http://localhost:11435"
    proxy_port: int = 11434
    db_path: str = "~/.ollama-tracker/usage.db"

    @property
    def resolved_db_path(self) -> Path:
        return Path(self.db_path).expanduser()


settings = Settings()
