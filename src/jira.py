"""Lectures dans l'API Jira (plateforme v3) : utilisateurs, statuts, champs, tickets, historiques."""
from .client import AtlassianClient
from .config import Settings


class JiraError(RuntimeError):
    pass


class JiraReader:
    def __init__(self, client: AtlassianClient, settings: Settings):
        self.client = client
        self.api = settings.jira_api

    @staticmethod
    def _json(resp, what: str):
        if not resp.ok:
            raise JiraError(f"{what} : HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()

    def statuses(self) -> dict[str, str]:
        """id -> nom de tous les statuts du site."""
        data = self._json(self.client.get(f"{self.api}/status"), "Liste des statuts")
        return {str(s["id"]): s.get("name", "") for s in data}

    def fields(self) -> dict[str, str]:
        """id -> nom de tous les champs (système et personnalisés)."""
        data = self._json(self.client.get(f"{self.api}/field"), "Liste des champs")
        return {str(f["id"]): f.get("name", "") for f in data}

    def issue_types(self) -> dict[str, str]:
        """id -> nom des types de ticket."""
        data = self._json(self.client.get(f"{self.api}/issuetype"), "Types de ticket")
        return {str(t["id"]): t.get("name", "") for t in data}

    def users(self, account_ids) -> dict[str, dict]:
        """accountId -> {name, active, type}. Les comptes introuvables sont absents du résultat."""
        ids = sorted(set(filter(None, account_ids)))
        out = {}
        for i in range(0, len(ids), 90):
            chunk = ids[i:i + 90]
            data = self._json(
                self.client.get(f"{self.api}/user/bulk", params={"accountId": chunk, "maxResults": 100}),
                "Utilisateurs",
            )
            for u in data.get("values", []):
                if not u or not u.get("accountId"):  # compte supprimé : entrée vide
                    continue
                out[u["accountId"]] = {
                    "name": u.get("displayName", ""),
                    "active": bool(u.get("active")),
                    "type": u.get("accountType", ""),  # "atlassian" = personne, "app" = robot
                }
        return out

    def search(self, jql: str, fields: list[str], limit: int) -> list[dict]:
        """Recherche JQL (POST /search/jql, lecture seule), paginée par jeton."""
        issues, token = [], None
        while len(issues) < limit:
            body = {"jql": jql, "fields": fields, "maxResults": min(100, limit - len(issues))}
            if token:
                body["nextPageToken"] = token
            data = self._json(self.client.search(f"{self.api}/search/jql", body), f"Recherche JQL « {jql} »")
            issues += data.get("issues", [])
            token = data.get("nextPageToken")
            if not token or data.get("isLast"):
                break
        return issues

    def jql_has_results(self, jql: str) -> bool | None:
        """True / False selon que la JQL renvoie des tickets ; None si la JQL est invalide."""
        resp = self.client.search(f"{self.api}/search/jql", {"jql": jql, "fields": ["id"], "maxResults": 1})
        if resp.status_code == 400:
            return None
        return bool(self._json(resp, "Test JQL").get("issues"))

    def changelogs(self, issue_ids: list[str]) -> dict[str, list[dict]]:
        """issueId -> historiques de modification (POST /changelog/bulkfetch, lecture seule)."""
        out: dict[str, list[dict]] = {}
        for i in range(0, len(issue_ids), 1000):
            token = None
            while True:
                body = {"issueIdsOrKeys": issue_ids[i:i + 1000], "maxResults": 1000}
                if token:
                    body["nextPageToken"] = token
                data = self._json(self.client.search(f"{self.api}/changelog/bulkfetch", body), "Historiques")
                for log in data.get("issueChangeLogs", []):
                    out.setdefault(str(log.get("issueId")), []).extend(log.get("changeHistories", []))
                token = data.get("nextPageToken")
                if not token:
                    break
        return out
