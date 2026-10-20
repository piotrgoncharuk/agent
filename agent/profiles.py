"""М1: генерация текстов профилей под каждую платформу из мастер-профиля."""
import yaml
from pydantic import BaseModel, Field

from .catalog import Catalog
from .llm import structured
from .proposals import LANG_NAMES

SYSTEM = """You write freelance marketplace profiles for a specialist in statistics, research methods,
scientific writing, editing and formatting (all research domains).

Rules:
- Use ONLY facts from the master profile. Fields in [square brackets] are unfilled: keep the bracketed
  placeholder in the text instead of inventing a value. Never invent publications, clients, reviews or numbers.
- Lead with client outcomes (accepted manuscripts, defended theses, clear results), then services, then tools.
- Use the platform's search vocabulary naturally (e.g. "biostatistics", "SPSS", "meta-analysis", "APA").
- Respect every character limit exactly; count characters, not words.
- Write in {language}."""


class ProfileField(BaseModel):
    field: str
    text: str


class ProfileTexts(BaseModel):
    fields: list[ProfileField] = Field(description="по одному элементу на каждое поле профиля")
    keywords: list[str] = Field(description="10-15 тегов/навыков для поля skills платформы")


def generate_profile(platform_id: str, language: str, catalog: Catalog, *, model: str, client=None) -> ProfileTexts:
    platform = catalog.platforms[platform_id]
    services = "\n".join(f"- {s.name.get(language, s.name['en'])}" for s in catalog.services.values())
    limits = "\n".join(f"- {name}: max {n} characters" for name, n in platform.profile_limits.items())
    prompt = (
        f"Platform: {platform_id}\nFields and limits:\n{limits}\n\n"
        f"Services offered:\n{services}\n\n"
        f"<master_profile>\n{yaml.safe_dump(catalog.profile, allow_unicode=True, sort_keys=False)}</master_profile>"
    )
    result = structured(model=model, system=SYSTEM.format(language=LANG_NAMES[language]), prompt=prompt,
                        output=ProfileTexts, effort="medium", client=client)
    for f in result.fields:
        limit = platform.profile_limits.get(f.field)
        if limit and len(f.text) > limit:
            f.text = f.text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return result
