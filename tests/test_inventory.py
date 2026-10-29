"""Tests hors ligne : règles d'exemple + faux lecteur Jira (aucun appel réseau)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import inventory
from src.anomalies import MASK, mask_secrets
from src.config import Settings
from src.describe import RefData, describe_rule, references
from src.report import diff, write_all
from src.rules import classify_scope, load_rules_file
from src.usage import Event, match_events, signature

FIXTURE = Path(__file__).parent / "fixtures" / "sample_rules.json"
CLOUD = "02f93c22-4123-4e29-a35e-435c1aab8e00"
ARI = f"ari:cloud:jira:{CLOUD}:project/10000"
ROBOT = "557058:f58131cb-b67d-43c7-b30d-6b58d40bd077"
ME = "712020:8777d6b4-c2a9-4061-a486-1b3397184747"

SETTINGS = Settings(site_url="https://cloudi-fi.atlassian.net", cloud_id=CLOUD, email="x", token="y",
                    projects={"CFIT": "10000"}, usage_window_days=90, use_internal_api=False)
CTX = RefData(
    statuses={"10000": "À faire", "10001": "En cours", "10002": "To Test", "10003": "Terminé(e)",
              "10569": "Qualification"},
    fields={"issuetype": "Type de ticket", "assignee": "Responsable", "customfield_10544": "Tests"},
    users={ME: {"name": "Ilyaas", "active": True, "type": "atlassian"},
           ROBOT: {"name": "Automation for Jira", "active": True, "type": "app"}},
)


def rules_by_uuid():
    return {r["uuid"]: r for r in load_rules_file(FIXTURE, SETTINGS, "10000")}


def test_scope_filtering():
    assert classify_scope([ARI], ARI) == "Projet"
    assert classify_scope([ARI, f"ari:cloud:jira:{CLOUD}:project/2"], ARI) == "Multi-projets"
    assert classify_scope([], ARI) == "Global"
    assert classify_scope([f"ari:cloud:jira::site/{CLOUD}"], ARI) == "Global"
    assert classify_scope([f"ari:cloud:jira:{CLOUD}:project/99999"], ARI) is None
    assert "demo-other" not in rules_by_uuid()


def test_describe_in_french():
    rules = rules_by_uuid()
    role = describe_rule(rules["demo-0002"], CTX)["role"]
    assert "change de statut vers « En cours »" in role and "« Tests »" in role
    role = describe_rule(rules["demo-0003"], CTX)["role"]
    assert "lance à la main" in role and "« To Test »" in role and "commentaire" in role


def test_internal_api_format():
    """Format de l'API interne (copiée de l'interface) : idUuid, actor.value, ruleScope, dates en ms."""
    from src.rules import normalize_internal
    from src.usage import rule_actor
    rule = normalize_internal({
        "id": 1, "idUuid": "u-1", "name": "Triage", "state": "ENABLED", "created": 1770215687256,
        "actor": {"type": "ACCOUNT_ID", "value": ROBOT}, "ruleScope": {"resources": [ARI]},
        "trigger": {"component": "TRIGGER", "type": "jira.issue.event.trigger:created", "conditions": [
            {"component": "CONDITION", "type": "jira.issue.condition",
             "value": {"selectedField": {"type": "ID", "value": "issuetype"}, "comparison": "ONE_OF",
                       "compareValue": {"type": "ID", "value": '["10006","10430"]', "multiValue": True}}}]},
        "components": [{"component": "ACTION", "type": "jira.issue.outgoing.email",
                        "value": {"to": [{"type": "FREE", "value": "sabrina@cloudi-fi.com"}]}}],
    })
    assert rule["uuid"] == "u-1" and rule["ruleScopeARIs"] == [ARI] and rule_actor(rule) == ROBOT
    ctx = RefData(issue_types={"10006": "Bug", "10430": "Customer Bug"})
    role = describe_rule(rule, ctx)["role"]
    assert "« Bug », « Customer Bug »" in role and "sabrina@cloudi-fi.com" in role
    assert references(rule)["emails"] == {"sabrina@cloudi-fi.com"}


def test_unknown_component_does_not_crash():
    rule = {"uuid": "x", "trigger": {"type": "vendor.weird.trigger"},
            "components": [{"component": "ACTION", "type": "vendor.weird.action", "value": 3}]}
    d = describe_rule(rule, CTX)
    assert "vendor.weird.trigger" in d["role"] and "vendor.weird.action" in d["role"]


def test_references_detect_broken_items():
    refs = references(rules_by_uuid()["demo-0004"])
    assert "QA" in refs["statuses"] and "customfield_99999" in refs["fields"]


def test_secrets_are_masked():
    rule = rules_by_uuid()["demo-0005"]
    masked, n = mask_secrets(rule)
    text = json.dumps(masked)
    assert "FAKESECRET" not in text and n >= 1
    _, n = mask_secrets({"headers": [{"name": "Authorization", "value": "Basic abc"}], "x": "Bearer zzz"})
    assert n == 2
    assert mask_secrets({"authorAccountId": ME})[0]["authorAccountId"] == ME  # pas un secret


def test_usage_matching_strong_vs_shared():
    rules = rules_by_uuid()
    now = datetime.now(timezone.utc)
    selected = [rules["demo-0001"], rules["demo-0002"]]
    sigs = {r["uuid"]: signature(r, CTX) for r in selected}
    events = [
        Event("field", {"assignee"}, ROBOT, now, "CFIT-1"),
        Event("field", {"customfield_10544", "tests"}, ROBOT, now, "CFIT-2"),
        Event("field", {"assignee"}, ME, now, "CFIT-3"),  # fait par un humain : ignoré
    ]
    ev = match_events(selected, sigs, events)
    assert ev["demo-0001"].strong == 1 and ev["demo-0001"].issues == ["CFIT-1"]
    assert ev["demo-0002"].strong == 1

    # Deux règles de même signature : la preuve n'est que « moyenne » pour chacune.
    twin = dict(rules["demo-0001"], uuid="twin")
    sigs["twin"] = signature(twin, CTX)
    ev = match_events(selected + [twin], sigs, events[:1])
    assert ev["demo-0001"].medium == 1 and ev["twin"].medium == 1 and ev["demo-0001"].strong == 0


class FakeJira:
    def __init__(self, client, s):
        pass

    def statuses(self):
        return CTX.statuses

    def fields(self):
        return CTX.fields

    def issue_types(self):
        return {}

    def users(self, ids):
        return {i: CTX.users[i] for i in ids if i in CTX.users}

    def search(self, jql, fields, limit):
        now = datetime.now(timezone.utc).isoformat()
        return [{"id": "1", "key": "CFIT-1", "fields": {"created": now, "reporter": {"displayName": "Alice"}}}]

    def changelogs(self, ids):
        return {"1": [{"author": {"accountId": ROBOT}, "created": datetime.now(timezone.utc).isoformat(),
                       "items": [{"fieldId": "assignee", "field": "assignee"}]}]}

    def jql_has_results(self, jql):
        return False


def test_full_run_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(inventory, "JiraReader", FakeJira)
    data = inventory.run(None, SETTINGS, "CFIT", "10000", inventory.Options(rules_file=FIXTURE), log=lambda *_: None)
    by_name = {r["name"]: r for r in data["rules"]}
    assert len(data["rules"]) == 6

    assign = by_name["[DÉMO] Assigner les nouveaux bugs"]
    assert assign["verdict"] == "Active (prouvée)" and "Alice" in assign["people_touched"]

    old = by_name["[DÉMO] Ancienne règle QA"]
    assert old["verdict"] == "Morte"
    assert any("QA" in m for m in old["remarks"]) and any("inactif ou introuvable" in m for m in old["remarks"])

    slack = by_name["[DÉMO] Alerte Slack bugs en qualification"]
    assert any("Doublon" in m for m in slack["remarks"])
    assert slack["verdict"] == "Morte"  # la JQL planifiée ne renvoie rien (FakeJira)
    assert "FAKESECRET" not in json.dumps(data) and "FAKE\"" not in json.dumps(data)

    paths = write_all(data, tmp_path)
    assert all(p.exists() for p in paths.values())
    assert "[DÉMO] Ancienne règle QA" in paths["html"].read_text(encoding="utf-8")


class FakeAuditClient:
    """Journal d'audit paginé comme le vrai : 50 lignes max à partir de `offset`."""
    def __init__(self, entries):
        self.entries, self.bodies = entries, []

    def search(self, url, body):
        assert url.endswith("/10000/auditlog")
        self.bodies.append(body)
        page = self.entries[body["offset"]:body["offset"] + 50]

        class R:
            ok, status_code = True, 200

            def json(self_inner):
                return {"items": {"items": page}}
        return R()


def _entry(rule_uuid, category, days_ago, now):
    ms = int((now.timestamp() - days_ago * 86400) * 1000)
    return {"ruleIdUuid": rule_uuid, "ruleId": "1", "category": category, "startTime": str(ms)}


def test_audit_log_and_verdicts():
    from src.usage import audit_log, Signature, Evidence, verdict
    now = datetime.now(timezone.utc)
    page1 = [_entry("active", "SUCCESS", 3, now)] + [_entry("never", "NO_ACTIONS_PERFORMED", d, now) for d in range(49)]
    page2 = [_entry("old", "SUCCESS", 100, now), _entry("old", "NO_ACTIONS_PERFORMED", 2, now),
             _entry("active", "CONFIG_CHANGE", 1, now), _entry("active", "SOME_ERRORS", 5, now)]
    client = FakeAuditClient(page1 + page2)
    log = audit_log(client, SETTINGS, "10000", 365, 90, now, lambda *_: None)
    assert [b["offset"] for b in client.bodies] == [0, 50, 54]  # pagination jusqu'à la page vide

    def v(uuid, state="ENABLED"):
        return verdict({"uuid": uuid, "state": state}, Evidence(), log.for_rule({"uuid": uuid}), Signature(),
                       [], 90, now, log.oldest)[0]

    active = log.for_rule({"uuid": "active"})
    assert active.runs == 2 and active.acted == 2 and active.errors == 1  # CONFIG_CHANGE ignoré
    assert v("active") == "Active (prouvée)"
    assert v("never") == "Morte"        # se déclenche mais n'agit jamais
    assert v("old") == "Douteuse"       # dernière action hors fenêtre
    assert v("absent") == "Morte"       # aucune exécution
    assert v("active", "DISABLED") == "Active (prouvée)"  # désactivée récemment mais a agi dans la fenêtre


def test_diff_between_reports():
    prev = {"rules": [{"uuid": "a", "name": "A", "state": "Activée", "verdict": "Probable"},
                      {"uuid": "b", "name": "B", "state": "Activée", "verdict": "Morte"}]}
    cur = {"rules": [{"uuid": "a", "name": "A", "state": "Désactivée", "verdict": "Probable"},
                     {"uuid": "c", "name": "C", "state": "Activée", "verdict": "Douteuse"}]}
    types = {c["type"] for c in diff(prev, cur)}
    assert types == {"Nouvelle règle", "Règle disparue", "Statut changé"}
    assert diff(None, cur) == []


@pytest.mark.parametrize("value,expected", [
    ("2026-10-01T10:00:00.000+0200", "2026-10-01"),
    (1759312800000, "2025-10-01"),
    ("pas une date", ""),
])
def test_parse_date(value, expected):
    from src.util import fmt_date, parse_date
    assert fmt_date(parse_date(value)) == expected
