"""Грубое определение языка заказа: en / pl / ru / ua."""
import re

_UA_ONLY = set("іїєґІЇЄҐ")
_RU_ONLY = set("ыэъёЫЭЪЁ")
_PL_ONLY = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_CYR = re.compile(r"[а-яА-ЯіїєґІЇЄҐёЁ]")
_LAT = re.compile(r"[a-zA-Z]")
_PL_WORDS = re.compile(r"\b(jest|się|oraz|dla|który|która|pracy|praca|potrzebuję|szukam|nie|jak|do|na|w|z|że|wyniki)\b", re.I)


def detect_language(text: str) -> str:
    cyr = len(_CYR.findall(text))
    lat = len(_LAT.findall(text))
    if cyr > lat:
        ua = sum(ch in _UA_ONLY for ch in text)
        ru = sum(ch in _RU_ONLY for ch in text)
        return "ua" if ua > ru else "ru"
    pl_chars = sum(ch in _PL_ONLY for ch in text)
    if pl_chars + len(_PL_WORDS.findall(text)) >= 3 and pl_chars >= 1:
        return "pl"
    return "en"
