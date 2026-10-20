"""М2: общий интерфейс сборщиков заказов."""
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class JobIn(BaseModel):
    platform: str
    external_id: str
    title: str
    description: str = ""
    url: str = ""
    budget_min: float | None = None
    budget_max: float | None = None
    budget_type: str = "unknown"
    currency: str = "USD"
    client_info: dict = Field(default_factory=dict)
    posted_at: datetime | None = None


class Collector(Protocol):
    platform: str

    def fetch(self) -> list[JobIn]: ...
