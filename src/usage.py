"""Preuves qu'une règle sert encore.

Trois sources, de la plus fiable à la moins fiable :
1. API interne « executions » (non documentée, optionnelle) : date exacte de dernière exécution.
2. Historique des tickets : modifications / commentaires / créations faits par l'acteur
   de la règle, rapprochés de la « signature » de ses actions.
3. Analyse statique (règle désactivée, JQL planifiée vide, références cassées...).
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .describe import (RefData, action_category, comment_text, component_kind, created_summary,
                       edited_fields, required_issue_types, static_text, transition_targets, walk)
from .util import ACCOUNT_ID_RE, adf_text, iter_strings, parse_date

TRACEABLE = {"transition", "edit", "assign", "comment", "create", "link"}


def rule_actor(rule: dict) -> str | None:
    actor = rule.get("actor")
    if isinstance(actor, dict):  # API publique : "actor", API interne : "value"
        return actor.get("actor") or actor.get("value") or actor.get("accountId") or rule.get("actorAccountId")
    return actor if isinstance(actor, str) else rule.get("actorAccountId")


@dataclass
class Signature:
    """Ce que les actions de la règle laissent comme trace dans les tickets."""
    fields: set = field(default_factory=set)      # ids et noms en minuscules
    statuses: set = field(default_factory=set)    # ids et noms en minuscules
    comment: bool = False
    snippets: list = field(default_factory=list)  # début de texte fixe des commentaires
    create: bool = False
    create_snippets: list = field(default_factory=list)  # début du titre des tickets créés
    assign_targets: set = field(default_factory=set)     # comptes à qui la règle assigne
    issue_types: set = field(default_factory=set)        # types de ticket exigés (ids et noms)
    link: bool = False
    categories: set = field(default_factory=set)

    @property
    def traceable(self) -> bool:
        return bool(self.categories & TRACEABLE)


def signature(rule: dict, ctx: RefData) -> Signature:
    sig = Signature()
    for t in required_issue_types(rule):
        sig.issue_types |= {t.lower(), ctx.issue_type_name(t).lower()}
    for _, comp in walk(rule.get("components")):
        if component_kind(comp) != "ACTION":
            continue
        cat = action_category(comp)
        sig.categories.add(cat)
        value = comp.get("value") if isinstance(comp.get("value"), dict) else {}
        if cat == "transition":
            for t in transition_targets(value):
                sig.statuses |= {t.lower(), ctx.status_name(t).lower()}
            if not transition_targets(value):
                sig.statuses.add("*")
        elif cat == "edit":
            for f in edited_fields(value):
                sig.fields |= {f.lower(), ctx.field_name(f).lower()}
        elif cat == "assign":
            sig.fields.add("assignee")
            sig.assign_targets |= {s.lower() for s in iter_strings(value.get("assignee")) if ACCOUNT_ID_RE.match(s)}
        elif cat == "comment":
            sig.comment = True
            snippet = static_text(comment_text(value), 40).lower()
            if len(snippet) >= 8:
                sig.snippets.append(snippet)
        elif cat == "create":
            sig.create = True
            snippet = created_summary(value).lower()
            if len(snippet) >= 5:
                sig.create_snippets.append(snippet)
        elif cat == "link":
            sig.link = True
    return sig


@dataclass
class Event:
    kind: str           # transition / field / comment / create / link
    values: set         # ids / noms en minuscules (statut, champ)
    author: str
    date: datetime
    issue_key: str
    text: str = ""      # texte du commentaire ou titre du ticket créé (minuscules)
    to: str = ""        # nouvelle valeur brute (ex. accountId du nouvel assigné)
    issue_type: set = field(default_factory=set)  # id et nom (minuscules) du type du ticket


def collect_events(jira, project_key: str, window_days: int, actor_ids: set[str], max_issues: int,
                   now: datetime) -> tuple[list[Event], dict[str, dict]]:
    """Lit les tickets récents du projet et renvoie les actions faites par les acteurs d'automation."""
    since = now - timedelta(days=window_days)
    issues = jira.search(
        f'project = "{project_key}" AND updated >= -{window_days}d ORDER BY updated DESC',
        ["summary", "created", "creator", "reporter", "assignee", "comment", "issuetype"],
        max_issues,
    )
    info, events = {}, []
    by_id, itypes = {}, {}
    for issue in issues:
        f = issue.get("fields") or {}
        key = issue.get("key", "")
        by_id[str(issue.get("id"))] = key
        it = f.get("issuetype") or {}
        itypes[key] = {str(it.get("id", "")).lower(), str(it.get("name", "")).lower()} - {""}
        info[key] = {
            "reporter": (f.get("reporter") or {}).get("displayName"),
            "assignee": (f.get("assignee") or {}).get("displayName"),
        }
        creator = (f.get("creator") or {}).get("accountId")
        created = parse_date(f.get("created"))
        if creator in actor_ids and created and created >= since:
            events.append(Event("create", set(), creator, created, key, text=(f.get("summary") or "").lower()))
        for c in ((f.get("comment") or {}).get("comments") or []):
            author = (c.get("author") or {}).get("accountId")
            date = parse_date(c.get("created"))
            if author in actor_ids and date and date >= since:
                events.append(Event("comment", set(), author, date, key, text=adf_text(c.get("body")).lower()))

    for issue_id, histories in jira.changelogs(list(by_id)).items():
        key = by_id.get(issue_id, issue_id)
        for h in histories:
            author = (h.get("author") or {}).get("accountId")
            date = parse_date(h.get("created"))
            if author not in actor_ids or not date or date < since:
                continue
            for item in h.get("items", []):
                fid = str(item.get("fieldId") or item.get("field") or "").lower()
                name = str(item.get("field") or "").lower()
                if fid == "status" or name == "status":
                    values = {str(item.get("to") or "").lower(), str(item.get("toString") or "").lower()}
                    events.append(Event("transition", values - {""}, author, date, key))
                elif name in ("link", "issuelinks") or fid == "issuelinks":
                    events.append(Event("link", set(), author, date, key))
                else:
                    events.append(Event("field", {fid, name} - {""}, author, date, key,
                                        to=str(item.get("to") or "").lower()))
    for ev in events:
        if ev.kind != "create":  # un ticket créé n'a pas le type du ticket déclencheur
            ev.issue_type = itypes.get(ev.issue_key, set())
    return events, info


@dataclass
class Evidence:
    strong: int = 0     # actions attribuables à cette seule règle
    medium: int = 0     # actions partagées avec d'autres règles de même signature
    last_seen: datetime | None = None
    issues: list = field(default_factory=list)

    def add(self, event: Event, unique: bool):
        if unique:
            self.strong += 1
        else:
            self.medium += 1
        if not self.last_seen or event.date > self.last_seen:
            self.last_seen = event.date
        if event.issue_key not in self.issues:
            self.issues.append(event.issue_key)


def _matches(sig: Signature, ev: Event) -> bool:
    if sig.issue_types and ev.issue_type and not (sig.issue_types & ev.issue_type):
        return False  # la règle ne vise pas ce type de ticket
    if ev.kind == "transition":
        return "*" in sig.statuses or bool(sig.statuses & ev.values)
    if ev.kind == "field":
        if "assignee" in ev.values and sig.assign_targets and ev.to:
            return ev.to in sig.assign_targets  # assignée à la bonne personne ?
        return bool(sig.fields & ev.values)
    if ev.kind == "comment":
        return sig.comment and (not sig.snippets or any(s in ev.text for s in sig.snippets))
    if ev.kind == "create":
        return sig.create and (not sig.create_snippets or any(s in ev.text for s in sig.create_snippets))
    if ev.kind == "link":
        return sig.link
    return False


def match_events(rules: list[dict], sigs: dict[str, Signature], events: list[Event]) -> dict[str, Evidence]:
    evidence = {r["uuid"]: Evidence() for r in rules}
    actors = {r["uuid"]: rule_actor(r) for r in rules}
    for ev in events:
        candidates = [u for u, sig in sigs.items() if actors.get(u) == ev.author and _matches(sig, ev)]
        # Un texte fixe (commentaire, titre du ticket créé) qui ne correspond qu'à une règle est une preuve forte.
        if len(candidates) > 1 and ev.kind in ("comment", "create"):
            attr = "snippets" if ev.kind == "comment" else "create_snippets"
            precise = [u for u in candidates if getattr(sigs[u], attr)]
            if len(precise) == 1:
                candidates = precise
        for u in candidates:
            evidence[u].add(ev, unique=len(candidates) == 1)
    return evidence


# --- Journal d'audit (API interne, copiée de l'onglet « Journal d'audit » de Jira) ---------

NOT_AN_EXECUTION = {"CONFIG_CHANGE"}           # modification de la règle, pas une exécution
ACTED = {"SUCCESS", "SOME_ERRORS"}             # la règle a réellement effectué des actions
ERROR_WORDS = ("ERROR", "FAIL", "ABORT", "THROTTL", "LOOP", "TIMEOUT")


@dataclass
class AuditStats:
    runs: int = 0               # déclenchements sur toute la période lue
    acted: int = 0              # dont exécutions ayant effectué des actions
    errors: int = 0
    runs_window: int = 0        # mêmes compteurs, limités à la fenêtre d'analyse
    acted_window: int = 0
    last_run: datetime | None = None
    last_acted: datetime | None = None
    last_error: datetime | None = None


@dataclass
class AuditLog:
    stats: dict                 # ruleIdUuid ou ruleId -> AuditStats
    oldest: datetime | None     # plus ancienne entrée conservée par Jira

    def for_rule(self, rule: dict) -> AuditStats:
        return self.stats.get(rule.get("uuid")) or self.stats.get(str(rule.get("id"))) or AuditStats()


def _latest(a, b):
    return b if a is None or (b and b > a) else a


def audit_log(client, s, project_id: str, days: int, window_days: int, now: datetime, log) -> AuditLog | None:
    """Lit le journal d'audit du space (POST .../{projectId}/auditlog, 50 lignes par page)."""
    url = f"{s.automation_internal_api}/{project_id}/auditlog"
    since = now - timedelta(days=window_days)
    from_time = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    stats, oldest, offset = {}, None, 0
    while True:
        body = {"fromTime": from_time, "offset": offset, "limit": 50,
                "actionTypes": [], "triggerTypes": [], "orchestrationTypes": []}
        resp = client.search(url, body)
        if not resp.ok:
            log(f"  Journal d'audit indisponible (HTTP {resp.status_code}) : preuve par l'historique seulement")
            return None
        page = (resp.json().get("items") or {}).get("items") or []
        for item in page:
            category = str(item.get("category", "")).upper()
            start = parse_date(int(item["startTime"])) if str(item.get("startTime", "")).isdigit() else None
            oldest = start if start and (oldest is None or start < oldest) else oldest
            if category in NOT_AN_EXECUTION:
                continue
            key = item.get("ruleIdUuid") or str(item.get("ruleId"))
            st = stats.setdefault(key, AuditStats())
            st.runs += 1
            st.last_run = _latest(st.last_run, start)
            in_window = bool(start and start >= since)
            st.runs_window += in_window
            if category in ACTED:
                st.acted += 1
                st.acted_window += in_window
                st.last_acted = _latest(st.last_acted, start)
            if any(w in category for w in ERROR_WORDS):
                st.errors += 1
                st.last_error = _latest(st.last_error, start)
        offset += len(page)
        if not page:
            break
    log(f"  Journal d'audit : {offset} entrée(s) lue(s)" + (f" depuis le {oldest:%Y-%m-%d}" if oldest else ""))
    return AuditLog(stats, oldest)

# --- verdict ------------------------------------------------------------------------

def _audit_verdict(enabled: bool, a: AuditStats, oldest: datetime | None, ev: Evidence,
                   window_days: int, now: datetime) -> tuple[str, str]:
    since = now - timedelta(days=window_days)
    depuis = f"depuis le {oldest:%Y-%m-%d}" if oldest else "dans le journal d'audit"
    examples = f" (ex. tickets {', '.join(ev.issues[:3])})" if ev.issues else ""
    if a.last_acted and a.last_acted >= since:
        return "Active (prouvée)", (f"{a.acted_window} exécution(s) avec actions sur {window_days} jours, "
                                    f"dernière le {a.last_acted:%Y-%m-%d} ; {a.runs_window} déclenchement(s) "
                                    f"au total (journal d'audit){examples}")
    if not enabled:
        last = f", dernière exécution le {a.last_run:%Y-%m-%d}" if a.last_run else ""
        return "Morte", f"Règle désactivée{last}"
    if a.runs == 0:
        return "Morte", f"Aucune exécution {depuis} (journal d'audit)"
    if a.acted == 0:
        return "Morte", (f"Se déclenche ({a.runs} fois {depuis}) mais n'a jamais effectué d'action : "
                         f"ses conditions ne sont jamais remplies")
    days = (now - a.last_acted).days
    return "Douteuse", (f"Se déclenche ({a.runs_window} fois sur {window_days} jours) mais sa dernière action "
                        f"réelle date du {a.last_acted:%Y-%m-%d} (il y a {days} jours)")


def verdict(rule: dict, ev: Evidence, audit: AuditStats | None, sig: Signature, dead_reasons: list[str],
            window_days: int, now: datetime, audit_oldest: datetime | None = None) -> tuple[str, str]:
    """(verdict, explication). Verdicts : Active (prouvée), Probable, Douteuse, Morte.

    `audit` vaut None si le journal d'audit n'a pas pu être lu : on se rabat alors sur l'historique des tickets.
    """
    enabled = str(rule.get("state", "")).upper() == "ENABLED"
    if audit is not None:
        return _audit_verdict(enabled, audit, audit_oldest, ev, window_days, now)

    if ev.strong:
        return "Active (prouvée)", (f"{ev.strong} action(s) retrouvée(s) dans les tickets, dernière le "
                                    f"{ev.last_seen:%Y-%m-%d} (ex. {', '.join(ev.issues[:3])})")
    if ev.medium:
        return "Probable", (f"{ev.medium} action(s) compatible(s) dans les tickets, mais partagée(s) avec "
                            f"d'autres règles ; dernière le {ev.last_seen:%Y-%m-%d} "
                            f"(ex. {', '.join(ev.issues[:3])})")
    if not enabled:
        return "Morte", "Règle désactivée, aucune trace sur la période"
    if dead_reasons:
        return "Morte", "; ".join(dead_reasons)
    if not sig.traceable:
        return "Douteuse", ("Ses actions (notifications, webhooks, variables...) ne laissent pas de trace "
                            "dans les tickets : utilisation impossible à prouver sans le journal d'audit")
    return "Douteuse", f"Activée mais aucune trace dans les tickets sur les {window_days} derniers jours"
