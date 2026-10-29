"""Petites fonctions partagées : dates, texte, parcours de JSON."""
import re
from datetime import datetime, timezone

# Identifiants de compte Atlassian : ancien format (24 hexa) ou "557058:<uuid>".
ACCOUNT_ID_RE = re.compile(r"^(?:[0-9a-f]{24}|\d{6}:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$")
_TZ_RE = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_date(value) -> datetime | None:
    """ISO 8601 (avec ou sans ':' dans le fuseau) ou timestamp en ms -> datetime UTC-aware."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
    text = _TZ_RE.sub(r"\1:\2", str(value).strip())
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def fmt_date(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def days_since(d: datetime | None, now: datetime) -> int | None:
    return (now - d).days if d else None


def adf_text(node) -> str:
    """Texte brut d'un document ADF (format des commentaires Jira v3) ou d'une chaîne."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(filter(None, (adf_text(n) for n in node)))
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return adf_text(node.get("content", []))
    return ""


def iter_items(obj, path=()):
    """Parcourt récursivement un JSON et renvoie (clé, valeur, chemin) pour chaque entrée de dict."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v, path
            yield from iter_items(v, path + (k,))
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_items(v, path)


def iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v)


def is_smart_value(text: str) -> bool:
    return "{{" in text
