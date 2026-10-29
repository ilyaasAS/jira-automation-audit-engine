"""Remarques automatiques sur chaque règle, et masquage des secrets de configuration."""
import re
from collections import defaultdict
from datetime import datetime

from .describe import CUSTOM_FIELD_RE, RefData, action_category, component_kind, walk
from .usage import rule_actor
from .util import days_since, parse_date

MASK = "***masqué***"
SECRET_KEY_RE = re.compile(r"(authori[sz]ation|token|password|passwd|secret|api[-_]?key|cookie|credential|"
                           r"^headers?$|webhook|url$)", re.I)  # les URL de webhook contiennent souvent une clé
SECRET_VALUE_RE = re.compile(r"^(basic|bearer)\s+\S+", re.I)


def mask_secrets(obj):
    """Copie du JSON avec les valeurs sensibles masquées (AUTO-2211). Renvoie (copie, nb masqués)."""
    count = 0

    def _mask(o):
        nonlocal count
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if SECRET_KEY_RE.search(str(k)) and v not in (None, "", [], {}):
                    out[k] = MASK
                    count += 1
                else:
                    out[k] = _mask(v)
            return out
        if isinstance(o, list):
            return [_mask(v) for v in o]
        if isinstance(o, str) and SECRET_VALUE_RE.match(o):
            count += 1
            return MASK
        return o

    return _mask(obj), count


def _logic_key(rule: dict) -> tuple:
    """Empreinte de la logique (déclencheur + types et valeurs des composants) pour trouver les doublons."""
    trigger = rule.get("trigger") or {}
    parts = [str(trigger.get("type")), repr(trigger.get("value"))]
    for _, comp in [*walk(trigger.get("conditions")), *walk(rule.get("components"))]:
        parts.append(f"{comp.get('type')}={comp.get('value')!r}")
    return tuple(parts)


def duplicates(rules: list[dict]) -> dict[str, list[str]]:
    """uuid -> remarques de doublon (même nom ou même logique)."""
    by_name, by_logic = defaultdict(list), defaultdict(list)
    for r in rules:
        by_name[(r.get("name") or "").strip().lower()].append(r)
        by_logic[_logic_key(r)].append(r)
    out = defaultdict(list)
    for group, label in ((by_name, "même nom"), (by_logic, "même logique")):
        for same in group.values():
            if len(same) > 1:
                for r in same:
                    others = [o.get("name", "?") for o in same if o is not r]
                    out[r["uuid"]].append(f"Doublon possible ({label}) avec : {', '.join(others)}")
    return out


def broken_references(refs: dict, ctx: RefData) -> list[str]:
    out = []
    if ctx.statuses:
        names = {n.lower() for n in ctx.statuses.values()}
        for s in sorted(refs["statuses"]):
            missing = s not in ctx.statuses if s.isdigit() else s.lower() not in names
            if missing and s.upper() not in ("ANY", "ALL", "NONE"):
                out.append(f"Statut introuvable : « {s} »")
    if ctx.fields:
        for f in sorted(refs["fields"]):
            if CUSTOM_FIELD_RE.match(f) and f not in ctx.fields:
                out.append(f"Champ supprimé ou introuvable : {f}")
    for aid in sorted(refs["account_ids"]):
        u = ctx.users.get(aid)
        if u is None:
            out.append(f"Utilisateur référencé introuvable ({aid[-6:]})")
        elif not u["active"]:
            out.append(f"Utilisateur référencé inactif : {u['name']}")
    return out


def find_anomalies(rule: dict, refs: dict, ctx: RefData, secrets_masked: int, now: datetime,
                   stale_days: int = 365) -> list[str]:
    out = []
    enabled = str(rule.get("state", "")).upper() == "ENABLED"
    updated = parse_date(rule.get("updated"))

    if not (rule.get("description") or "").strip():
        out.append("Pas de description")

    author = ctx.users.get(rule.get("authorAccountId"))
    if rule.get("authorAccountId") and (author is None or not author["active"]):
        out.append("Auteur / propriétaire inactif ou introuvable (personne partie ?)")

    actor_id = rule_actor(rule)
    actor = ctx.users.get(actor_id) if actor_id else None
    if actor and actor["type"] == "atlassian":
        out.append(f"La règle agit au nom d'une personne ({actor['name']}) et non de « Automation for Jira »")
    if actor_id and (actor is None or not actor["active"]):
        out.append("Acteur (identité d'exécution) inactif ou introuvable : la règle risque d'échouer")

    age = days_since(updated, now)
    if not enabled:
        out.append(f"Désactivée (dernière modification il y a {age} jours)" if age is not None else "Désactivée")
    elif age is not None and age > stale_days:
        out.append(f"Pas modifiée depuis plus d'un an ({age} jours)")

    scope = rule.get("_scope")
    if scope in ("Global", "Multi-projets"):
        label = "globale" if scope == "Global" else "multi-projets"
        out.append(f"Portée {label} : la règle touche aussi d'autres projets")

    notify = rule.get("notifyOnError")
    if notify is False or str(notify).upper() in ("NEVER", "FALSE"):
        out.append("Pas de notification en cas d'erreur (notifyOnError désactivé)")

    if any(action_category(c) == "delete" for _, c in walk(rule.get("components"))
           if component_kind(c) == "ACTION"):
        out.append("Contient une action de SUPPRESSION de tickets")

    out += broken_references(refs, ctx)

    if secrets_masked or rule.get("_connections"):
        out.append("Contient des secrets ou connexions (masqués dans ce rapport)")
    return out
