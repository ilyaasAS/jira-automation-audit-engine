"""Récupération des règles d'automation (API publique) et filtrage par projet."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .client import AtlassianClient
from .config import Settings


class AutomationAccessDenied(RuntimeError):
    """L'API Automation refuse l'accès : le compte doit être administrateur Jira."""


def project_ari(cloud_id: str, project_id: str) -> str:
    return f"ari:cloud:jira:{cloud_id}:project/{project_id}"


def classify_scope(aris: list[str] | None, target_ari: str) -> str | None:
    """Portée de la règle vis-à-vis du projet, ou None si elle ne le concerne pas."""
    aris = aris or []
    if not aris:
        return "Global"
    if target_ari in aris:
        return "Projet" if len(aris) == 1 else "Multi-projets"
    if any(":project/" not in a for a in aris):  # site entier ou type de projet
        return "Global"
    return None


def list_summaries(client: AtlassianClient, s: Settings) -> list[dict]:
    url = f"{s.automation_public_api}/rule/summary"
    params = {"limit": 100}
    summaries = []
    while True:
        resp = client.get(url, params=params)
        if resp.status_code in (401, 403):
            raise AutomationAccessDenied(
                f"HTTP {resp.status_code} sur l'API Automation : le compte doit avoir la permission "
                "globale « Administer Jira » (admin de projet ne suffit pas)."
            )
        resp.raise_for_status()
        data = resp.json()
        summaries += data.get("data", [])
        nxt = (data.get("links") or {}).get("next")
        cursor = parse_qs(urlparse(nxt).query).get("cursor", [None])[0] if nxt else None
        if not cursor:
            return summaries
        params = {"limit": 100, "cursor": cursor}


def _keep_for_project(rules: list[dict], target_ari: str) -> list[dict]:
    kept = []
    for r in rules:
        scope = classify_scope(r.get("ruleScopeARIs"), target_ari)
        if scope:
            r["_scope"] = scope
            kept.append(r)
    return kept


def normalize_internal(rule: dict) -> dict:
    """Aligne une règle de l'API interne sur le format de l'API publique."""
    rule["uuid"] = rule.get("idUuid") or str(rule.get("id"))
    rule["ruleScopeARIs"] = (rule.get("ruleScope") or {}).get("resources") or []
    return rule


def fetch_rules_internal(client: AtlassianClient, s: Settings, project_id: str) -> list[dict]:
    """Règles complètes d'un space via l'API interne utilisée par l'interface Jira.

    Fonctionne avec les droits d'admin du space (pas besoin d'admin Jira).
    """
    url = f"{s.automation_internal_api}/{project_id}/rules"
    rules, offset = [], 0
    while True:
        body = {"offset": offset, "limit": 50, "filter": "", "actionTypes": [], "triggerTypes": [],
                "orchestrationTypes": [], "sortKey": "NAME", "sortOrder": "ASC", "systemLabelId": "CONTAINER"}
        resp = client.search(url, body)
        if resp.status_code in (401, 403):
            raise AutomationAccessDenied(f"HTTP {resp.status_code} sur la liste des règles du space {project_id}")
        resp.raise_for_status()
        data = resp.json()
        page = data.get("values", [])
        rules += page
        offset += len(page)
        if not page or offset >= int(data.get("total", 0)):
            break
    kept = _keep_for_project([normalize_internal(r) for r in rules], project_ari(s.cloud_id, project_id))
    for r in kept:
        r["_source"] = "API interne du space (droits d'admin du space)"
    return kept


def fetch_rules(client: AtlassianClient, s: Settings, project_id: str, log=print) -> list[dict]:
    """API publique si le compte est admin Jira, sinon API interne du space (admin du space)."""
    try:
        return fetch_rules_public(client, s, project_id)
    except AutomationAccessDenied:
        log("  API publique refusée (pas admin Jira) : lecture via l'API interne du space")
        return fetch_rules_internal(client, s, project_id)


def fetch_rules_public(client: AtlassianClient, s: Settings, project_id: str) -> list[dict]:
    """Règles complètes (déclencheur, conditions, actions) qui concernent le projet."""
    target = project_ari(s.cloud_id, project_id)
    rules = []
    for summary in _keep_for_project(list_summaries(client, s), target):
        resp = client.get(f"{s.automation_public_api}/rule/{summary['uuid']}")
        resp.raise_for_status()
        data = resp.json()
        rule = data.get("rule", data)
        rule.setdefault("uuid", summary["uuid"])
        rule["_scope"] = summary["_scope"]
        rule["_connections"] = data.get("connections") or []
        rules.append(rule)
    return rules


def load_rules_file(path: Path, s: Settings, project_id: str) -> list[dict]:
    """Charge des règles depuis un JSON local (mode démo / tests), même format que GET /rule/{uuid}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("rules", data) if isinstance(data, dict) else data
    rules = []
    for item in items:
        rule = item.get("rule", item)
        rule["_connections"] = item.get("connections") or rule.get("_connections") or []
        rules.append(rule)
    return _keep_for_project(rules, project_ari(s.cloud_id, project_id))
