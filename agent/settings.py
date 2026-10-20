from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = f"sqlite:///{ROOT / 'data' / 'agent.db'}"
    model_writer: str = "claude-sonnet-5-5"
    model_scorer: str = "claude-haiku-5-5"
    score_notify_threshold: int = 60

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    freelancehunt_token: str = ""
    freelancer_token: str = ""

    config_dir: Path = ROOT / "config"
    profiles_dir: Path = ROOT / "profiles"


@lru_cache
def get_settings() -> Settings:
    return Settings()
