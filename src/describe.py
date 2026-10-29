"""Traduction d'une règle (déclencheur, conditions, actions) en français simple,
et extraction de ce qu'elle référence (personnes, statuts, champs, JQL).

Les types de composants Atlassian (ex. "jira.issue.event.trigger:transitioned")
sont reconnus par mots-clés : un type inconnu est affiché tel quel, sans erreur.
"""
import json
import re
from dataclasses import dataclass, field

from .util import ACCOUNT_ID_RE, is_smart_value, iter_items, iter_strings

CUSTOM_FIELD_RE = re.compile(r"^customfield_\d+$")
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


@dataclass
class RefData:
    """Données de référence Jira pour traduire les identifiants en noms."""
    statuses: dict[str, str] = field(default_factory=dict)  # id -> nom
    fields: dict[str, str] = field(default_factory=dict)    # id -> nom
    users: dict[str, dict] = field(default_factory=dict)    # accountId -> {name, active, type}
    issue_types: dict[str, str] = field(default_factory=dict)  # id -> nom

    def status_name(self, ref: str) -> str:
        return self.statuses.get(ref, ref)

    def issue_type_name(self, ref: str) -> str:
        return self.issue_types.get(ref, ref)

    def field_name(self, ref: str) -> str:
        return self.fields.get(ref, ref)

    def user_name(self, account_id: str) -> str:
        u = self.users.get(account_id)
        return u["name"] if u else f"compte inconnu ({account_id[-6:]})"


ROLE_TOKENS = {
    "ASSIGNEE": "le responsable du ticket",
    "REPORTER": "le rapporteur",
    "WATCHERS": "les observateurs",
    "CREATOR": "le créateur du ticket",
    "INITIATOR": "la personne qui a déclenché la règle",
    "CURRENT_USER": "la personne qui a déclenché la règle",
    "PROJECT_LEAD": "le responsable du projet",
    "COMPONENT_LEAD": "le responsable du composant",
}

TRIGGERS = [
    # DevOps en premier : "devops.branch.event.trigger:created" contient aussi "trigger:created".
    ("devops.branch", "une branche Git est créée"),
    ("pullrequest", "une pull request est créée ou modifiée"),
    ("pull.request", "une pull request est créée ou modifiée"),
    ("devops.commit", "un commit est poussé"),
    ("devops.build", "un build se termine"),
    ("deployment", "un déploiement a lieu"),
    ("multiple.issue.event", "un ticket subit un des événements suivants"),
    ("trigger:moved", "un ticket est déplacé (autre projet ou autre type)"),
    ("transitioned", "un ticket change de statut"),
    ("trigger:created", "un ticket est créé"),
    ("commented", "un commentaire est ajouté"),
    ("assigned", "un ticket est assigné"),
    ("trigger:deleted", "un ticket est supprimé"),
    ("trigger:updated", "un ticket est modifié"),
    ("field.changed", "un champ change de valeur"),
    ("scheduled", "à intervalle régulier (planifié)"),
    ("manual", "un utilisateur la lance à la main"),
    ("incoming.webhook", "un appel web entrant est reçu"),
    ("link", "un lien entre tickets est créé ou supprimé"),
    ("sprint", "un événement de sprint a lieu"),
    ("version", "un événement de version a lieu"),
    ("worklog", "du temps est saisi"),
    ("sla", "un SLA atteint un seuil"),
    ("approval", "une approbation est demandée ou donnée"),
]

CONDITIONS = [
    ("container.block", "selon le cas (si / sinon)"),
    ("if.block", "cas « si / sinon »"),
    ("jql", "le ticket correspond à une JQL"),
    ("related", "condition sur les tickets liés"),
    ("user", "condition sur un utilisateur"),
    ("comparator", "comparaison de deux valeurs"),
    ("issue.condition", "condition sur un champ du ticket"),
]

# (mot-clé, libellé, catégorie). Catégorie utilisée pour la preuve d'utilisation :
# transition / edit / assign / comment / create / link laissent une trace dans les tickets,
# notify / internal / delete n'en laissent pas (ou plus).
ACTIONS = [
    ("transition", "change le statut", "transition"),
    ("assign", "assigne le ticket", "assign"),
    ("variable", "crée une variable", "internal"),
    ("subtask", "crée des sous-tâches", "create"),
    ("sub-task", "crée des sous-tâches", "create"),
    ("clone", "clone le ticket", "create"),
    ("issue.create", "crée un ticket", "create"),
    ("create.issue", "crée un ticket", "create"),
    ("comment", "ajoute un commentaire", "comment"),
    ("email", "envoie un email", "notify"),
    ("slack", "envoie un message Slack", "notify"),
    ("teams", "envoie un message Microsoft Teams", "notify"),
    ("webhook", "envoie une requête web (webhook)", "notify"),
    ("watcher", "ajoute des observateurs", "notify"),
    ("issue.delete", "supprime le ticket", "delete"),
    ("link", "lie des tickets", "link"),
    ("lookup", "recherche des tickets (lookup)", "internal"),
    ("worklog", "saisit du temps", "edit"),
    ("log", "écrit dans le journal d'audit", "internal"),
    ("edit", "modifie des champs", "edit"),
]

COMPARISONS = {
    "EQUALS": "est", "NOT_EQUALS": "n'est pas", "ONE_OF": "est parmi", "NOT_ONE_OF": "n'est pas parmi",
    "IS_EMPTY": "est vide", "IS_NOT_EMPTY": "n'est pas vide", "EMPTY": "est vide", "NOT_EMPTY": "n'est pas vide",
    "CONTAINS": "contient",
    "NOT_CONTAINS": "ne contient pas", "GREATER_THAN": "est supérieur à", "LESS_THAN": "est inférieur à",
}

RELATED_TYPES = {
    "sub-tasks": "ses sous-tâches", "subtasks": "ses sous-tâches", "parent": "son ticket parent",
    "epic": "son epic", "stories": "les tickets de l'epic", "linked": "les tickets liés",
    "jql": "les tickets d'une JQL", "created": "le ticket créé", "cloned": "le ticket cloné",
    "lookup": "les tickets trouvés",
}

KIND_FR = {"TRIGGER": "Déclencheur", "CONDITION": "Condition", "ACTION": "Action", "BRANCH": "Branche"}


# --- utilitaires -----------------------------------------------------------------

def ref_values(value) -> list[str]:
    """Valeurs d'une référence Atlassian : "x", {"type": "ID", "value": "x"}, {"id": ...}, listes..."""
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
        try:  # valeurs multiples encodées en texte JSON : '["10006","10430"]'
            return ref_values(json.loads(value))
        except ValueError:
            pass
    if isinstance(value, (str, int)):
        return [str(value)]
    if isinstance(value, list):
        return [v for item in value for v in ref_values(item)]
    if isinstance(value, dict):
        for key in ("value", "id", "name", "accountId"):
            if isinstance(value.get(key), (str, int)) and not isinstance(value.get(key), bool):
                return ref_values(str(value[key]))
        if isinstance(value.get("value"), (dict, list)):
            return ref_values(value["value"])
    return []


def quoted(values) -> str:
    return ", ".join(f"« {v} »" for v in values)


def match_label(type_: str, table):
    t = (type_ or "").lower()
    for row in table:
        if row[0] in t:
            return row
    return None


def component_kind(comp: dict) -> str:
    kind = (comp.get("component") or "").upper()
    if kind in KIND_FR:
        return kind
    t = (comp.get("type") or "").lower()
    if "trigger" in t:
        return "TRIGGER"
    if "condition" in t:
        return "CONDITION"
    if "branch" in t or t.endswith(".related"):
        return "BRANCH"
    return "ACTION"


def action_category(comp: dict) -> str:
    row = match_label(comp.get("type"), ACTIONS)
    return row[2] if row else "unknown"


def walk(components, depth: int = 0):
    """Parcourt les composants en profondeur : (profondeur, composant)."""
    for comp in components or []:
        if not isinstance(comp, dict):
            continue
        yield depth, comp
        yield from walk(comp.get("conditions"), depth + 1)
        yield from walk(comp.get("children"), depth + 1)


def recipients(value, ctx: RefData) -> list[str]:
    roles = [ROLE_TOKENS[s] for s in iter_strings(value) if s in ROLE_TOKENS]
    users = [ctx.user_name(s) for s in iter_strings(value) if ACCOUNT_ID_RE.match(s)]
    emails = [s for s in iter_strings(value) if EMAIL_RE.match(s)]
    return list(dict.fromkeys(roles + users + emails))


def operation_value(value: dict, field_id: str):
    """Valeur fixée pour un champ dans les "operations" d'une action (création / modification)."""
    for op in value.get("operations") or []:
        if isinstance(op, dict) and field_id in ref_values(op.get("field")):
            return op.get("value")
    return None


def required_issue_types(rule: dict) -> set[str]:
    """Types de ticket (ids) exigés par une condition « Type de ticket est / est parmi »."""
    trigger = rule.get("trigger") or {}
    top_conditions = [c for c in rule.get("components") or [] if component_kind(c) == "CONDITION"]
    out = set()
    for comp in [*(trigger.get("conditions") or []), *top_conditions]:
        value = comp.get("value") if isinstance(comp, dict) and isinstance(comp.get("value"), dict) else {}
        if "issue.condition" not in str(comp.get("type")) or not value:
            continue
        if ref_values(value.get("selectedField"))[:1] == ["issuetype"] and \
                str(value.get("comparison", "")).upper() in ("EQUALS", "ONE_OF"):
            out |= set(ref_values(value.get("compareValue")))
    return out


def created_summary(value: dict) -> str:
    summary = operation_value(value, "summary")
    return static_text(summary, 50) if isinstance(summary, str) else ""


def static_text(text: str, length: int = 60) -> str:
    """Début du texte fixe (sans smart values {{...}})."""
    return re.sub(r"\s+", " ", re.split(r"\{\{", text or "", maxsplit=1)[0]).strip()[:length]


def edited_fields(value: dict) -> list[str]:
    ops = value.get("operations") or []
    refs = [r for op in ops if isinstance(op, dict) for r in ref_values(op.get("field") or op.get("fieldId"))]
    if not refs and isinstance(value.get("fields"), dict):
        refs = list(value["fields"].keys())
    return refs


def transition_targets(value: dict) -> list[str]:
    return ref_values(value.get("destinationStatus") or value.get("toStatus") or value.get("status"))


def comment_text(value: dict) -> str:
    c = value.get("comment") or value.get("body") or ""
    return c if isinstance(c, str) else " ".join(iter_strings(c))


# --- descriptions ----------------------------------------------------------------

def describe_trigger(trigger: dict, ctx: RefData) -> str:
    type_ = trigger.get("type") or ""
    row = match_label(type_, TRIGGERS)
    text = row[1] if row else f"déclencheur « {type_ or 'inconnu'} »"
    value = trigger.get("value") or {}
    if not isinstance(value, dict):
        return text
    to = [ctx.status_name(v) for v in ref_values(value.get("toStatus"))]
    frm = [ctx.status_name(v) for v in ref_values(value.get("fromStatus"))]
    if frm:
        text += f" depuis {quoted(frm)}"
    if to:
        text += f" vers {quoted(to)}"
    if "field.changed" in type_ or "fields" in value:
        names = [ctx.field_name(v) for v in ref_values(value.get("fields"))]
        if names:
            text += f" ({quoted(names)})"
    if isinstance(value.get("events"), list):
        labels = [str(e.get("labelKey") or e.get("event") or "").rsplit(".", 1)[-1]
                  for e in value["events"] if isinstance(e, dict)]
        fr = {"updated": "modifié", "transitioned": "changement de statut", "created": "créé",
              "commented": "commenté", "assigned": "assigné", "deleted": "supprimé"}
        text += f" : {', '.join(fr.get(l, l) for l in labels if l)}"
    jql = value.get("jql") or value.get("jqlQuery")
    if isinstance(jql, str) and jql.strip():
        text += f", sur les tickets « {jql.strip()} »"
    return text


def describe_condition(comp: dict, ctx: RefData) -> str:
    type_ = comp.get("type") or ""
    raw = comp.get("value")
    value = raw if isinstance(raw, dict) else {}
    if "issue.condition" in type_ and value:
        fields = ref_values(value.get("selectedField") or value.get("field"))
        op = COMPARISONS.get(str(value.get("comparison", "")).upper(), str(value.get("comparison", "")).lower())
        vals = ref_values(value.get("compareValue") or value.get("values"))
        kind = fields[0].lower() if fields else ""
        if kind == "status":
            vals = [ctx.status_name(v) for v in vals]
        elif kind == "issuetype":
            vals = [ctx.issue_type_name(v) for v in vals]
        elif kind in ("assignee", "reporter"):
            vals = [ctx.user_name(v) if ACCOUNT_ID_RE.match(v) else v for v in vals]
        name = ctx.field_name(fields[0]) if fields else "un champ"
        return f"le champ « {name} » {op} {quoted(vals)}".strip()
    if "jql" in type_.lower():
        jql = raw if isinstance(raw, str) else value.get("jql") or value.get("query") or ""
        return f"le ticket correspond à « {jql} »" if jql else "le ticket correspond à une JQL"
    row = match_label(type_, CONDITIONS)
    return row[1] if row else f"condition « {type_} »"


def describe_action(comp: dict, ctx: RefData) -> str:
    type_ = comp.get("type") or ""
    value = comp.get("value") if isinstance(comp.get("value"), dict) else {}
    row = match_label(type_, ACTIONS)
    if not row:
        return f"action « {type_} »"
    text, cat = row[1], row[2]
    if cat == "transition":
        targets = [ctx.status_name(v) for v in transition_targets(value)]
        if targets:
            text += f" vers {quoted(targets)}"
    elif cat == "edit" and "worklog" not in type_:
        names = [ctx.field_name(f) for f in edited_fields(value)]
        if names:
            text = f"modifie {quoted(names)}"
    elif cat == "assign":
        who = recipients(value, ctx)
        if who:
            text += f" ({', '.join(who)})"
    elif cat == "create":
        summary = created_summary(value)
        itype = ref_values(operation_value(value, "issuetype"))
        if summary:
            text += f" « {summary}… »"
        if itype:
            text += f" (type {ctx.issue_type_name(itype[0])})"
    elif cat == "comment":
        snippet = static_text(comment_text(value))
        if snippet:
            text += f" (« {snippet}… »)"
    elif cat == "notify" and "webhook" not in type_:
        who = recipients(value, ctx)
        if who:
            text += f" (destinataires : {', '.join(who)})"
    elif "webhook" in type_:
        url = value.get("url") or ""
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url) if isinstance(url, str) else ""
        if host and not is_smart_value(host):
            text += f" vers {host}"
    return text


def describe_branch(comp: dict) -> str:
    value = comp.get("value") if isinstance(comp.get("value"), dict) else {}
    rel = str(value.get("relatedType") or value.get("type") or "").lower()
    return f"pour {RELATED_TYPES.get(rel, f'les tickets « {rel} »' if rel else 'des tickets liés')}"


def describe_component(comp: dict, ctx: RefData) -> str:
    kind = component_kind(comp)
    if kind == "TRIGGER":
        return describe_trigger(comp, ctx)
    if kind == "CONDITION":
        return describe_condition(comp, ctx)
    if kind == "BRANCH":
        return describe_branch(comp)
    return describe_action(comp, ctx)


def _action_label(comp: dict) -> str:
    row = match_label(comp.get("type"), ACTIONS)
    return row[1] if row else str(comp.get("type"))


def _nested_actions(comp: dict, ctx: RefData) -> list[str]:
    return [describe_action(c, ctx) for _, c in walk(comp.get("children")) if component_kind(c) == "ACTION"]


def describe_rule(rule: dict, ctx: RefData) -> dict:
    """{"trigger": phrase, "role": résumé en une phrase, "steps": [(type, profondeur, texte)]}."""
    trigger = rule.get("trigger") or {}
    trig_text = describe_trigger(trigger, ctx)
    top = rule.get("components") or []

    steps = [(KIND_FR["TRIGGER"], 0, trig_text)]
    for depth, comp in walk(trigger.get("conditions")):
        steps.append((KIND_FR[component_kind(comp)], depth + 1, describe_component(comp, ctx)))
    for depth, comp in walk(top):
        steps.append((KIND_FR[component_kind(comp)], depth, describe_component(comp, ctx)))

    conds = [describe_condition(c, ctx) for c in trigger.get("conditions") or []
             if isinstance(c, dict) and "block" not in (c.get("type") or "")]
    acts = []
    plain = [c for c in top if component_kind(c) == "ACTION"]
    repeated = {lbl for lbl in (_action_label(c) for c in plain) if sum(_action_label(x) == lbl for x in plain) > 3}
    grouped = set()
    for comp in top:
        kind = component_kind(comp)
        if kind == "ACTION" and _action_label(comp) in repeated:
            # Ex. 23 créations de sous-tâches : une seule ligne résumée dans le rôle.
            lbl = _action_label(comp)
            if lbl not in grouped:
                grouped.add(lbl)
                same = [c for c in plain if _action_label(c) == lbl]
                examples = [created_summary(c.get("value") or {}) for c in same[:3]]
                ex = f" (ex. {quoted([e for e in examples if e])}…)" if any(examples) else ""
                acts.append(f"{lbl} ×{len(same)}{ex}")
        elif kind == "ACTION":
            acts.append(describe_action(comp, ctx))
        elif kind == "BRANCH":
            inner = _nested_actions(comp, ctx)
            if inner:
                acts.append(f"{describe_branch(comp)} : {', '.join(inner)}")
        elif "block" in (comp.get("type") or ""):
            inner = list(dict.fromkeys(_nested_actions(comp, ctx)))
            if inner:
                acts.append(f"selon le cas : {' / '.join(inner)}")
        else:
            conds.append(describe_condition(comp, ctx))

    role = f"Quand {trig_text}"
    if conds:
        role += f", si {' et '.join(conds)}"
    role += f", la règle {', puis '.join(acts)}." if acts else " : aucune action définie."
    return {"trigger": trig_text, "role": role[0].upper() + role[1:], "steps": steps}


# --- références ------------------------------------------------------------------

def references(rule: dict) -> dict:
    """Ce que la configuration de la règle référence (hors auteur / acteur)."""
    config = {"trigger": rule.get("trigger"), "components": rule.get("components")}
    refs = {"account_ids": set(), "roles": set(), "groups": set(), "statuses": set(),
            "fields": set(), "jqls": [], "emails": set()}
    for s in iter_strings(config):
        if ACCOUNT_ID_RE.match(s):
            refs["account_ids"].add(s)
        elif EMAIL_RE.match(s):
            refs["emails"].add(s)
        elif s in ROLE_TOKENS:
            refs["roles"].add(s)
        elif CUSTOM_FIELD_RE.match(s):
            refs["fields"].add(s)
    for key, value, _ in iter_items(config):
        k = key.lower()
        if "status" in k and "category" not in k:
            refs["statuses"] |= {v for v in ref_values(value) if not is_smart_value(v)}
        elif k in ("field", "fieldid", "selectedfield"):
            refs["fields"] |= {v for v in ref_values(value) if not is_smart_value(v)}
        elif "group" in k:
            refs["groups"] |= {v for v in ref_values(value) if not is_smart_value(v)}
        if "jql" in k and isinstance(value, str) and value.strip():
            refs["jqls"].append(value.strip())
    return refs
