import pytest

from src.client import AtlassianClient, ReadOnlyViolation

SITE = "https://cloudi-fi.atlassian.net"
CLOUD = "02f93c22-4123-4e29-a35e-435c1aab8e00"
PUBLIC = f"https://api.atlassian.com/automation/public/jira/{CLOUD}/rest/v1"
INTERNAL = f"{SITE}/gateway/api/automation/internal-api/jira/{CLOUD}/pro/rest"


@pytest.fixture
def client():
    return AtlassianClient(SITE, "test@example.com", "fake-token")


@pytest.mark.parametrize("url", [
    f"{PUBLIC}/rule/summary",
    f"{PUBLIC}/rule/abc-123",
    f"{INTERNAL}/GLOBAL/rules/42/executions",
    f"{SITE}/rest/api/3/myself",
])
def test_get_allowed(client, url):
    client.check_allowed("GET", url)


@pytest.mark.parametrize("url", [
    f"{PUBLIC}/rule/summary",
    f"{INTERNAL}/GLOBAL/auditlog/search",
    f"{SITE}/rest/api/3/search/jql",
    f"{SITE}/rest/api/3/changelog/bulkfetch",
])
def test_search_post_allowed(client, url):
    client.check_allowed("POST", url)


@pytest.mark.parametrize("method,url", [
    ("POST", f"{PUBLIC}/rule"),                        # création de règle
    ("PUT", f"{PUBLIC}/rule/abc-123"),                 # modification
    ("PUT", f"{PUBLIC}/rule/abc-123/state"),           # activer / désactiver
    ("PUT", f"{PUBLIC}/rule/abc-123/rule-scope"),
    ("DELETE", f"{PUBLIC}/rule/abc-123"),
    ("POST", f"{SITE}/rest/api/3/issue"),              # création de ticket
    ("PUT", f"{SITE}/rest/api/3/issue/CFIT-1"),
    ("POST", f"{SITE}/rest/api/3/issue/CFIT-1/comment"),
    ("POST", f"{SITE}/rest/api/3/issue/CFIT-1/transitions"),
    ("PATCH", f"{SITE}/rest/api/3/myself"),
    ("POST", f"{PUBLIC}/rule/summary/../../rule"),     # contournement par chemin
])
def test_writes_forbidden(client, method, url):
    with pytest.raises(ReadOnlyViolation):
        client.check_allowed(method, url)


@pytest.mark.parametrize("url", [
    "https://evil.example.com/rest/api/3/myself",
    "http://cloudi-fi.atlassian.net/rest/api/3/myself",
])
def test_foreign_or_plain_http_forbidden(client, url):
    with pytest.raises(ReadOnlyViolation):
        client.check_allowed("GET", url)


LIST_BODY = {"offset": 0, "limit": 20, "filter": "", "actionTypes": [], "triggerTypes": [],
             "orchestrationTypes": [], "sortKey": "NAME", "sortOrder": "ASC", "systemLabelId": "CONTAINER"}


def test_internal_rule_list_allowed_with_search_body_only(client):
    client.check_allowed("POST", f"{INTERNAL}/10000/rules", LIST_BODY)
    for bad in ({**LIST_BODY, "trigger": {}}, {"name": "x", "components": []}, None):
        with pytest.raises(ReadOnlyViolation):
            client.check_allowed("POST", f"{INTERNAL}/10000/rules", bad)
    with pytest.raises(ReadOnlyViolation):  # création de règle (singulier) : toujours interdite
        client.check_allowed("POST", f"{INTERNAL}/10000/rule", LIST_BODY)


def test_internal_audit_log_allowed_with_search_body_only(client):
    body = {"fromTime": "2026-09-19T07:18:59.907Z", "offset": 0, "limit": 50,
            "actionTypes": [], "triggerTypes": [], "orchestrationTypes": []}
    client.check_allowed("POST", f"{INTERNAL}/10000/auditlog", body)
    with pytest.raises(ReadOnlyViolation):
        client.check_allowed("POST", f"{INTERNAL}/10000/auditlog", {**body, "delete": True})


def test_client_has_no_write_methods(client):
    for name in ("put", "patch", "delete", "post"):
        assert not hasattr(client, name)
