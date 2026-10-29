"""Étape 0 : vérifie les droits et sonde les API (lecture seule).

Usage : python check_access.py

Affiche pour chaque appel le code HTTP et les clés reçues (jamais les valeurs,
qui peuvent contenir des secrets). Les réponses brutes sont enregistrées dans
output/probe/ (dossier ignoré par git) pour construire la suite du script.
"""
import json
import sys

from src.client import AtlassianClient
from src.config import ROOT_DIR, load_settings

PROBE_DIR = ROOT_DIR / "output" / "probe"


def keys_of(data) -> str:
    if isinstance(data, dict):
        return ", ".join(sorted(data.keys())) or "(objet vide)"
    if isinstance(data, list):
        first = data[0] if data else None
        inner = f" ; clés du 1er élément : {keys_of(first)}" if isinstance(first, dict) else ""
        return f"liste de {len(data)} élément(s){inner}"
    return type(data).__name__


def probe(client, name, method, url, params=None, body=None):
    """Appelle un endpoint, affiche un résumé, enregistre la réponse. Renvoie le JSON ou None."""
    try:
        resp = client.get(url, params=params) if method == "GET" else client.search(url, body or {})
    except Exception as exc:  # réseau, liste blanche...
        print(f"  [ERREUR] {name} : {exc}")
        return None

    try:
        data = resp.json()
    except ValueError:
        data = None

    status = "OK " if resp.ok else "KO "
    print(f"  [{status}{resp.status_code}] {name}")
    if data is not None:
        print(f"         clés : {keys_of(data)}")
        (PROBE_DIR / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    elif not resp.ok:
        print(f"         réponse : {resp.text[:200]!r}")
    return data if resp.ok else None


def main() -> int:
    s = load_settings()
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    client = AtlassianClient(s.site_url, s.email, s.token)
    project_key, project_id = next(iter(s.projects.items()))
    project_ari = f"ari:cloud:jira:{s.cloud_id}:project/{project_id}"

    print("\n1. Identité et droits Jira")
    me = probe(client, "01_myself", "GET", f"{s.jira_api}/myself")
    if me is None:
        print("  -> Authentification refusée : vérifier JIRA_EMAIL / JIRA_API_TOKEN dans .env")
        return 1
    print(f"         connecté : {me.get('displayName')} (actif={me.get('active')})")

    perms = probe(client, "02_mypermissions", "GET", f"{s.jira_api}/mypermissions",
                  params={"projectKey": project_key,
                          "permissions": "ADMINISTER,BROWSE_PROJECTS,USER_PICKER"})
    if perms:
        for key, p in perms.get("permissions", {}).items():
            print(f"         {key:16} : {'OUI' if p.get('havePermission') else 'NON'}")

    print("\n2. API publique Automation")
    summary = probe(client, "03_public_rule_summary", "GET",
                    f"{s.automation_public_api}/rule/summary", params={"limit": 100})
    rules = (summary or {}).get("data", [])
    in_project = [r for r in rules if project_ari in (r.get("ruleScopeARIs") or [])]
    global_rules = [r for r in rules if not r.get("ruleScopeARIs")]
    if summary is not None:
        print(f"         {len(rules)} règle(s) sur la 1re page, dont {len(in_project)} dans {project_key}, "
              f"{len(global_rules)} sans scope projet (globales ?)")
        print(f"         pagination : {keys_of(summary.get('links', {}))}")

    sample = (in_project or rules or [None])[0]
    if sample:
        detail = probe(client, "04_public_rule_detail", "GET", f"{s.automation_public_api}/rule/{sample['uuid']}")
        if detail:
            rule = detail.get("rule", detail)
            print(f"         clés de 'rule' : {keys_of(rule)}")
            print(f"         type du déclencheur : {(rule.get('trigger') or {}).get('type')}")

    print("\n3. API interne (non documentée)")
    internal = s.automation_internal_api
    uuid = sample["uuid"] if sample else None
    probe(client, "05_internal_rules_list", "GET", f"{internal}/GLOBAL/rules")
    probe(client, "06_internal_rule_summary", "GET", f"{internal}/GLOBAL/rule/summary")
    if uuid:
        probe(client, "07_internal_rule_by_uuid", "GET", f"{internal}/GLOBAL/rule/{uuid}")
        probe(client, "08_internal_executions_by_uuid", "GET",
              f"{internal}/GLOBAL/rules/{uuid}/executions", params={"sortOrder": "DESC", "limit": 1})
    probe(client, "09_internal_auditlog_search", "POST", f"{internal}/GLOBAL/auditlog/search",
          body={"offset": 0, "limit": 5})

    print(f"\nRéponses enregistrées dans {PROBE_DIR}")
    print("Copie-colle cette sortie console (elle ne contient aucun secret) pour la suite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
