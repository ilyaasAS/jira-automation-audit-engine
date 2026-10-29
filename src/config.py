"""Chargement de la configuration.

Les secrets viennent des variables d'environnement (fichier .env en local,
secrets GitHub plus tard). Le reste vient de config.yaml.
"""
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    site_url: str
    cloud_id: str
    email: str
    token: str
    projects: dict[str, str]
    usage_window_days: int
    use_internal_api: bool
    audit_log_days: int = 365
    max_issues: int = 3000

    @property
    def jira_api(self) -> str:
        return f"{self.site_url}/rest/api/3"

    @property
    def automation_public_api(self) -> str:
        return f"https://api.atlassian.com/automation/public/jira/{self.cloud_id}/rest/v1"

    @property
    def automation_internal_api(self) -> str:
        return f"{self.site_url}/gateway/api/automation/internal-api/jira/{self.cloud_id}/pro/rest"


def load_settings(config_path: Path = ROOT_DIR / "config.yaml") -> Settings:
    load_dotenv(ROOT_DIR / ".env")
    email = os.environ.get("JIRA_EMAIL", "").strip()
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if not email or not token:
        raise SystemExit(
            "JIRA_EMAIL et JIRA_API_TOKEN doivent être définis "
            "(copier .env.example en .env et le remplir)."
        )

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    return Settings(
        site_url=cfg["site_url"].rstrip("/"),
        cloud_id=cfg["cloud_id"],
        email=email,
        token=token,
        projects={str(k): str(v) for k, v in cfg["projects"].items()},
        usage_window_days=int(cfg.get("usage_window_days", 90)),
        use_internal_api=bool(cfg.get("use_internal_api", True)),
        audit_log_days=int(cfg.get("audit_log_days", 365)),
        max_issues=int(cfg.get("max_issues", 3000)),
    )
