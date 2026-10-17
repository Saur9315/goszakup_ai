import re
import unicodedata

_CYRILLIC = re.compile(r"[а-яёәғқңөұүһі]", re.IGNORECASE)
_LATIN_TO_CYRILLIC = str.maketrans(
    "aceopxyiAВCEHKMOPTXIB",
    "асеорхуіАВСЕНКМОРТХІВ",
)
_QUOTES = re.compile(r"[«»\"'“”„`´]")
_LOT_NUMBER = re.compile(r"\bлот\s*№?\s*\d+\b|№\s*\d+", re.IGNORECASE)
_LEADING_VERB = re.compile(
    r"^(поставка|приобретение|закупка|закуп|покупка|государственная закупка)\b[\s:,-]*"
)
_SEPARATORS = re.compile(r"[\s,;:.\-–—_/\\|]+")


def _fix_homoglyphs(token: str) -> str:
    return token.translate(_LATIN_TO_CYRILLIC) if _CYRILLIC.search(token) else token


def clean_name(value: str | None) -> str | None:
    if not value:
        return None
    # before NFKC, which turns "№" into "No"
    text = _LOT_NUMBER.sub(" ", value)
    text = unicodedata.normalize("NFKC", text)
    text = " ".join(_fix_homoglyphs(t) for t in text.split())
    text = text.lower()
    text = _QUOTES.sub(" ", text)
    text = _SEPARATORS.sub(" ", text).strip()
    text = _LEADING_VERB.sub("", text).strip()
    return text or None


def desc_text_sql(column: str) -> str:
    return rf"left(lower(regexp_replace(btrim({column}), '\s+', ' ', 'g')), 200)"
