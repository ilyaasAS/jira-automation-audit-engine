"""Assemble l'inventaire d'un projet : une fiche complète par règle."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .anomalies import duplicates, find_anomalies, mask_secrets
from .client import AtlassianClient
from .config import Settings
from .describe import RefData, describe_rule, ref_values, references, ROLE_TOKENS
from .jira import JiraReader
from .rules import fetch_rules, load_rules_file
from .usage import Evidence, audit_log, collect_events, match_events, rule_actor, signature, verdict
from .util import fmt_date, is_smart_value, parse_date


@dataclass
class Options:
    rules_file: Path | None = None   # mode démo : règles lues dans un JSON local
    use_internal_api: bool = True    # journal d'audit (API interne)
    audit_log_days: int = 365        # profondeur demandée (Jira n'en conserve qu'une partie)
    max_issues: int = 3000


def _collaborators(rule: dict) -> list[str]:
    return [v for v in ref_values(rule.get("collaborators")) if v]


def _scheduled_jql_problem(rule: dict, jira: JiraReader) -> str | None:
    trigger = rule.get("trigger") or {}
    value = trigger.get("value") if isinstance(trigger.get("value"), dict) else {}
    jql = value.get("jql") or value.get("jqlQuery")
    if "schedule" not in str(trigger.get("type", "")).lower() or not isinstance(jql, str) or not jql.strip():
        return None
    if is_smart_value(jql) or str(rule.get("state", "")).upper() != "ENABLED":
        return None
    has = jira.jql_has_results(jql)
    if has is None:
        return "La JQL du déclencheur planifié est invalide"
    if not has:
        return "La JQL du déclencheur planifié ne renvoie aucun ticket aujourd'hui"
    return None


def run(client: AtlassianClient, s: Settings, project_key: str, project_id: str, opts: Options, log=print) -> dict:
    now = datetime.now(timezone.utc)
    jira = JiraReader(client, s)

    if opts.rules_file:
        log(f"  Mode démo : règles lues dans {opts.rules_file}")
        rules = load_rules_file(opts.rules_file, s, project_id)
    else:
        rules = fetch_rules(client, s, project_id, log)
    log(f"  {len(rules)} règle(s) concernent {project_key}")

    log("  Lecture des statuts, champs et utilisateurs...")
    ctx = RefData(statuses=jira.statuses(), fields=jira.fields(), issue_types=jira.issue_types())
    refs = {r["uuid"]: references(r) for r in rules}
    account_ids = set()
    for r in rules:
        account_ids |= {r.get("authorAccountId"), rule_actor(r), *_collaborators(r)}
        account_ids |= refs[r["uuid"]]["account_ids"]
    ctx.users = jira.users(account_ids - {None})

    sigs = {r["uuid"]: signature(r, ctx) for r in rules}
    actor_ids = {rule_actor(r) for r in rules} - {None}
    events, issue_info = [], {}
    if actor_ids:
        log(f"  Analyse des tickets {project_key} des {s.usage_window_days} derniers jours...")
        events, issue_info = collect_events(jira, project_key, s.usage_window_days, actor_ids, opts.max_issues, now)
        log(f"  {len(events)} action(s) d'automation trouvée(s) dans l'historique")
    evidence = match_events(rules, sigs, events)

    audit = None
    if opts.use_internal_api and not opts.rules_file:
        log("  Lecture du journal d'audit...")
        audit = audit_log(client, s, project_id, max(opts.audit_log_days, s.usage_window_days),
                          s.usage_window_days, now, log)

    dups = duplicates(rules)
    records = []
    for r in rules:
        uuid = r["uuid"]
        desc = describe_rule(r, ctx)
        # Les connexions (identifiants de services externes) ne sont jamais recopiées, seulement comptées.
        masked, n_secrets = mask_secrets({k: v for k, v in r.items() if k != "_connections"})
        masked["_connections"] = len(r.get("_connections") or [])
        dead = [p for p in [_scheduled_jql_problem(r, jira)] if p]
        remarks = find_anomalies(r, refs[uuid], ctx, n_secrets, now) + dups.get(uuid, []) + dead
        ev = evidence.get(uuid, Evidence())
        dead_reasons = dead + [x for x in remarks if "introuvable" in x or "supprimé" in x]
        stats = audit.for_rule(r) if audit else None
        v, why = verdict(r, ev, stats, sigs[uuid], dead_reasons, s.usage_window_days, now,
                         audit.oldest if audit else None)
        if stats:
            if stats.errors:
                remarks.append(f"{stats.errors} exécution(s) en erreur, dernière le {fmt_date(stats.last_error)}")
            if stats.runs and not stats.acted:
                remarks.append("Se déclenche mais n'agit jamais : conditions à revoir ou règle inutile")
        elif v == "Douteuse" and str(r.get("state", "")).upper() == "ENABLED":
            remarks.append("Activée mais aucune trace d'exécution prouvée")

        rr = refs[uuid]
        people_config = ([ROLE_TOKENS[x] for x in sorted(rr["roles"])]
                         + [ctx.user_name(a) for a in sorted(rr["account_ids"])]
                         + sorted(rr["emails"])
                         + [f"groupe {g}" for g in sorted(rr["groups"])])
        robots = {u["name"] for u in ctx.users.values() if u.get("type") == "app"} | {"Automation for Jira"}
        touched = []
        for key in ev.issues:
            for who in (issue_info.get(key, {}).get("reporter"), issue_info.get(key, {}).get("assignee")):
                if who and who not in touched and who not in robots:
                    touched.append(who)

        author_id = r.get("authorAccountId")
        actor_id = rule_actor(r)
        records.append({
            "uuid": uuid,
            "name": r.get("name", ""),
            "state": "Activée" if str(r.get("state", "")).upper() == "ENABLED" else "Désactivée",
            "scope": r.get("_scope", ""),
            "labels": [str(l) for l in (r.get("labels") or [])],
            "description": (r.get("description") or "").strip(),
            "role": desc["role"],
            "trigger": desc["trigger"],
            "steps": [{"type": t, "depth": d, "text": txt} for t, d, txt in desc["steps"]],
            "author": ctx.user_name(author_id) if author_id else "",
            "owner": ctx.user_name(author_id) if author_id else "",
            "actor": ctx.user_name(actor_id) if actor_id else "",
            "collaborators": [ctx.user_name(c) for c in _collaborators(r)],
            "created": fmt_date(parse_date(r.get("created"))),
            "updated": fmt_date(parse_date(r.get("updated"))),
            "people_config": people_config,
            "people_touched": touched[:15],
            "verdict": v,
            "evidence": why,
            "last_seen": fmt_date(max(filter(None, [ev.last_seen, stats and stats.last_acted]), default=None)),
            "last_run": fmt_date(stats.last_run) if stats else "",
            "runs_window": stats.runs_window if stats else None,
            "acted_window": stats.acted_window if stats else None,
            "errors": stats.errors if stats else None,
            "evidence_issues": ev.issues[:10],
            "remarks": remarks,
            "config": masked,
        })

    records.sort(key=lambda rec: (rec["state"] != "Activée", rec["name"].lower()))
    return {
        "project": project_key,
        "generated_at": now.isoformat(timespec="seconds"),
        "window_days": s.usage_window_days,
        "sources": {
            "rules": "fichier démo" if opts.rules_file else
                     (rules[0].get("_source") if rules else None) or "API Automation publique",
            "internal_api": audit is not None,
            "audit_since": fmt_date(audit.oldest) if audit else "",
            "issues_analyzed": len(issue_info),
            "automation_events": len(events),
        },
        "rules": records,
    }
