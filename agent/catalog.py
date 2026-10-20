"""Загрузка каталога услуг, платформ и мастер-профиля из YAML."""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .settings import get_settings

LANGS = ("en", "pl", "ru", "ua")

# Примерные курсы к USD для сравнения бюджетов; обновляйте вручную.
FX_TO_USD = {"USD": 1.0, "EUR": 1.1, "GBP": 1.3, "PLN": 0.27, "UAH": 0.024, "CHF": 1.15, "CAD": 0.72, "AUD": 0.65, "INR": 0.012}


def to_usd(amount: float | None, currency: str) -> float | None:
    if amount is None:
        return None
    return amount * FX_TO_USD.get((currency or "USD").upper(), 1.0)


@dataclass(frozen=True)
class Service:
    id: str
    name: dict[str, str]
    keywords: dict[str, list[str]]
    price_min: float
    price_typical: float
    price_max: float
    unit: str

    def all_keywords(self) -> list[str]:
        return [k for lang in LANGS for k in self.keywords.get(lang, [])]


@dataclass(frozen=True)
class Platform:
    id: str
    priority: str
    languages: list[str]
    collector: str
    fee_pct: float
    profile_limits: dict[str, int] = field(default_factory=dict)
    proposal_limits: dict[str, int] = field(default_factory=dict)
    feeds: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Catalog:
    services: dict[str, Service]
    red_flags: list[str]
    platforms: dict[str, Platform]
    profile: dict


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_catalog(config_dir: Path, profiles_dir: Path) -> Catalog:
    raw = _load_yaml(config_dir / "services.yaml")
    services = {}
    for s in raw["services"]:
        p = s["price_usd"]
        services[s["id"]] = Service(
            id=s["id"],
            name=s["name"],
            keywords={lang: [k.lower() for k in kws] for lang, kws in s["keywords"].items()},
            price_min=p["min"],
            price_typical=p["typical"],
            price_max=p["max"],
            unit=p["unit"],
        )
    platforms = {
        pid: Platform(id=pid, **{k: v for k, v in p.items()})
        for pid, p in _load_yaml(config_dir / "platforms.yaml")["platforms"].items()
    }
    return Catalog(
        services=services,
        red_flags=[r.lower() for r in raw.get("red_flags", [])],
        platforms=platforms,
        profile=_load_yaml(profiles_dir / "master.yaml"),
    )


@lru_cache
def get_catalog() -> Catalog:
    s = get_settings()
    return load_catalog(s.config_dir, s.profiles_dir)
