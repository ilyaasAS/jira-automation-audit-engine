"""Inventaire des règles d'automation Jira (lecture seule).

Usage :
    python main.py                       # tous les projets de config.yaml
    python main.py --project CFIT
    python main.py --project CFIT --rules-file tests/fixtures/sample_rules.json   # mode démo
    python main.py --no-internal         # sans le journal d'audit (preuve par l'historique seulement)

Résultats : output/<PROJET>/inventaire_<PROJET>_<date>.xlsx / .html / .json
"""
import argparse
import sys
from pathlib import Path

from src.client import AtlassianClient
from src.config import ROOT_DIR, load_settings
from src.inventory import Options, run
from src.jira import JiraError
from src.report import write_all
from src.rules import AutomationAccessDenied


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventaire des automations Jira (lecture seule)")
    parser.add_argument("--project", action="append", help="Clé du projet (répétable). Défaut : tous.")
    parser.add_argument("--rules-file", type=Path, help="Mode démo : lire les règles dans ce JSON local")
    parser.add_argument("--no-internal", action="store_true", help="Ne pas lire le journal d'audit")
    parser.add_argument("--out", type=Path, default=ROOT_DIR / "output", help="Dossier de sortie")
    args = parser.parse_args()

    s = load_settings()
    projects = s.projects
    if args.project:
        unknown = [p for p in args.project if p not in projects]
        if unknown:
            print(f"Projet(s) absent(s) de config.yaml : {', '.join(unknown)}")
            return 2
        projects = {p: projects[p] for p in args.project}

    client = AtlassianClient(s.site_url, s.email, s.token)
    opts = Options(
        rules_file=args.rules_file,
        use_internal_api=s.use_internal_api and not args.no_internal,
        audit_log_days=s.audit_log_days,
        max_issues=s.max_issues,
    )

    for key, project_id in projects.items():
        print(f"\n=== {key} ===")
        try:
            data = run(client, s, key, project_id, opts)
        except AutomationAccessDenied as exc:
            print(f"  ACCÈS REFUSÉ : {exc}")
            print("  -> Demander l'accès admin Jira, ou tester avec --rules-file (mode démo).")
            return 3
        except JiraError as exc:
            print(f"  ERREUR Jira : {exc}")
            return 4
        # Les rapports de démo sont rangés à part pour ne pas fausser la comparaison hebdomadaire.
        out_dir = args.out / "demo" if args.rules_file else args.out
        for kind, path in write_all(data, out_dir).items():
            print(f"  {kind:5} : {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
