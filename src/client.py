"""Client HTTP Atlassian STRICTEMENT en lecture seule.

Toute requête passe par `check_allowed` :
- uniquement en HTTPS, vers le site Jira ou api.atlassian.com ;
- GET autorisé ;
- POST autorisé seulement sur des endpoints de RECHERCHE listés ci-dessous ;
- tout le reste (PUT, PATCH, DELETE, autre POST) lève ReadOnlyViolation.
Le client n'expose volontairement aucune méthode put/delete.
"""
import re
import time
from urllib.parse import urlparse

import requests

# POST autorisés : endpoints de recherche, sans aucun effet de bord.
ALLOWED_POST_PATHS = [
    re.compile(r"^/automation/public/jira/[^/]+/rest/v1/rule/summary$"),
    re.compile(r"^/gateway/api/automation/internal-api/jira/[^/]+/pro/rest/[^/]+/auditlog/search$"),
    re.compile(r"^/rest/api/3/search/jql$"),
    re.compile(r"^/rest/api/3/changelog/bulkfetch$"),
]

# POST de recherche dont le corps est AUSSI contrôlé : l'URL seule ne suffit pas à garantir
# la lecture seule, donc seuls ces champs de filtre/pagination sont acceptés.
# Liste des règles d'un space (API interne, copiée de l'interface Jira) :
INTERNAL_RULES_LIST = re.compile(r"^/gateway/api/automation/internal-api/jira/[^/]+/pro/rest/[^/]+/rules$")
INTERNAL_RULES_LIST_KEYS = {
    "offset", "limit", "filter", "actionTypes", "triggerTypes", "orchestrationTypes",
    "sortKey", "sortOrder", "systemLabelId", "labels", "ownerAccountIds", "states",
}
# Journal d'audit (exécutions) d'un space (API interne, copiée de l'interface Jira) :
INTERNAL_AUDIT_LOG = re.compile(r"^/gateway/api/automation/internal-api/jira/[^/]+/pro/rest/[^/]+/auditlog$")
INTERNAL_AUDIT_LOG_KEYS = {
    "fromTime", "toTime", "offset", "limit", "actionTypes", "triggerTypes", "orchestrationTypes",
    "ruleIds", "ruleIdUuids", "categories", "states",
}
ALLOWED_POST_WITH_BODY = [
    (INTERNAL_RULES_LIST, INTERNAL_RULES_LIST_KEYS),
    (INTERNAL_AUDIT_LOG, INTERNAL_AUDIT_LOG_KEYS),
]

RETRY_STATUSES = {429, 502, 503, 504}


class ReadOnlyViolation(RuntimeError):
    """Tentative d'appel susceptible de modifier des données Atlassian."""


class AtlassianClient:
    def __init__(self, site_url: str, email: str, token: str, timeout: int = 30, max_retries: int = 5):
        self.allowed_hosts = {"api.atlassian.com", urlparse(site_url).hostname}
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.auth = (email, token)
        self._session.headers.update({"Accept": "application/json"})

    def check_allowed(self, method: str, url: str, body: dict | None = None) -> None:
        method = method.upper()
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_hosts:
            raise ReadOnlyViolation(f"Hôte non autorisé : {url}")
        if ".." in parsed.path:
            raise ReadOnlyViolation(f"Chemin suspect : {parsed.path}")
        if method == "GET":
            return
        if method == "POST" and any(p.match(parsed.path) for p in ALLOWED_POST_PATHS):
            return
        if method == "POST":
            for pattern, keys in ALLOWED_POST_WITH_BODY:
                if pattern.match(parsed.path):
                    extra = set(body or {}) - keys
                    if not isinstance(body, dict) or extra:
                        raise ReadOnlyViolation(f"Corps refusé pour {parsed.path} : champs {sorted(extra)}")
                    return
        raise ReadOnlyViolation(f"Appel interdit (lecture seule) : {method} {parsed.path}")

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        self.check_allowed(method, url, kwargs.get("json"))
        resp = None
        for attempt in range(self.max_retries):
            # Pas de redirection automatique : elle pourrait mener hors liste blanche.
            resp = self._session.request(method, url, timeout=self.timeout, allow_redirects=False, **kwargs)
            if resp.status_code not in RETRY_STATUSES:
                return resp
            time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
        return resp

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        return self._request("GET", url, params=params)

    def search(self, url: str, body: dict) -> requests.Response:
        """POST de recherche (lecture seule, endpoints listés dans ALLOWED_POST_PATHS)."""
        return self._request("POST", url, json=body)
