"""Deterministic, versioned diagnostic rules (FC22-006, docs/engineering/DIAGNOSTIC_AND_QOE.md).

A rule is a PURE function: JSON-able inputs in, a finding out. No clock, no database, no network, no randomness, no LLM, and nothing
here can write to equipment. That is what makes a stored run reproducible: the same inputs under the same (rule, version) always give the
same finding. Rules are never edited in place; a behaviour change is a NEW version, and old versions stay registered so old runs replay.

Finding status (never a score, never an invented value):
- observed: facts measured from the data we have (counts), nothing concluded beyond them
- inferred: a hypothesis derived from observed facts; always `requires_human_confirmation`
- unknown: the data is too old or absent to say anything; nothing is claimed
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

MIN_DROPPED = 5      # fewer than this many simultaneous drops is not a PON event (one customer down is not a PON event)
OPEN_RATIO = 0.8     # share of the PON's ACTIVE population (online + recently dropped) that dropped


@dataclass(frozen=True)
class RuleResult:
    """What the incident correlator needs (matched, suspected_cause) next to the finding that is shown and stored."""
    matched: bool
    suspected_cause: str
    finding: dict


def suspected_cause(los: int, dying_gasp: int, n: int) -> str:
    """A hint, not a diagnosis: the dominant drop signal among the recently dropped ONUs."""
    return "fiber_or_los" if los >= n / 2 else ("power" if dying_gasp >= n / 2 else "unknown")


def r_d001_v1(i: dict) -> RuleResult:
    """R-D001 v1: several ONUs of the same PON DROPPED together (online -> down inside the lookback), on fresh data.

    Extracted unchanged from the incident correlator (ADR-0018): chronically offline ONUs are in neither the numerator nor the denominator;
    the active population is online + recently dropped; it matches at >= MIN_DROPPED drops and >= OPEN_RATIO of that population.
    Inputs: pon_path, online, recent_drops, los, dying_gasp, chronic, observed, fresh_data(bool)."""
    online, drops = int(i["online"]), int(i["recent_drops"])
    population = online + drops
    ratio = drops / population if population else 0.0
    evidence = {"pon_path": i["pon_path"], "onus_observed": int(i["observed"]), "onus_down_recent": drops, "online": online,
                "los": int(i["los"]), "dying_gasp": int(i["dying_gasp"]), "chronic_offline": int(i["chronic"]), "ratio": round(ratio, 3)}
    if not i["fresh_data"] or int(i["observed"]) == 0:
        why = "no ONU known for this PON" if int(i["observed"]) == 0 else "the newest observation of this PON is too old"
        f = {"status": "unknown", "hypothesis": None, "reason": why, "evidence": evidence, "requires_human_confirmation": False,
             "next_read_action": "wait for the next collection of this OLT"}
        return RuleResult(False, "unknown", f)
    if drops >= MIN_DROPPED and ratio >= OPEN_RATIO:
        cause = suspected_cause(int(i["los"]), int(i["dying_gasp"]), drops)
        f = {"status": "inferred", "hypothesis": "suspected collective access failure on this PON", "suspected_cause": cause,
             "evidence": evidence, "requires_human_confirmation": True,
             "next_read_action": "confirm with the open incident, field events and the behaviour of neighbouring ONUs"}
        return RuleResult(True, cause, f)
    f = {"status": "observed", "hypothesis": None, "reason": "recent drops do not reach the collective-failure pattern",
         "evidence": evidence, "requires_human_confirmation": False, "next_read_action": "re-read after the next collection"}
    return RuleResult(False, "unknown", f)


CONNECTED = frozenset({"Connected", "Up"})   # TR-098 WANxxxConnection / TR-181 PPP interface
DOWN = frozenset({"Disconnected", "Unconfigured", "Down", "NotPresent", "LowerLayerDown", "Error"})  # not established, and not on its way


def r_d002_v1(i: dict) -> RuleResult:
    """R-D002 v1: what the CPE ITSELF reports about its WAN (link and connection state read from the ACS cache; ADR-0027).

    Inputs: links and connections (lists of {"state", "fresh"}, one per reading, sorted); newest_age_seconds and oldest_age_seconds of the
    WAN readings (int|None); onu_link ("confirmed"|"none"), onu_status (str|None), onu_fresh (bool). The link is "Up" or "Down" only when
    EVERY link reading is recent and says so (links that disagree, any old reading and other states are indeterminate: no link is picked).
    Freshness is per reading, not per CPE: the cache keeps the last row of every connection, so a recent reading of one connection must
    never vouch for an old reading of another. An established connection that is fresh wins; any connection last read too long ago could
    still be established, so the rule says nothing then. A connection counts as down only when EVERY reported connection is fresh and in
    DOWN: a transitional or unknown state (Connecting, Dormant, Unknown...) never becomes a claim. The ONU only adds context and never
    changes the verdict."""
    conns = [{"state": str(c["state"]), "fresh": bool(c["fresh"])} for c in i["connections"]]
    links = [{"state": str(c["state"]), "fresh": bool(c["fresh"])} for c in i["links"]]
    recent_links = {c["state"] for c in links if c["fresh"]}
    # the link is known only if EVERY link reading is recent and they agree; an old reading may be a link that is still up (or down)
    link = next(iter(recent_links)) if len(recent_links) == 1 and all(c["fresh"] for c in links) else None
    onu = {"link": i["onu_link"], "status": i["onu_status"], "fresh": bool(i["onu_fresh"])}
    evidence = {"links": links, "connections": conns,
                "newest_age_seconds": i["newest_age_seconds"], "oldest_age_seconds": i["oldest_age_seconds"], "onu": onu}
    refresh = "request a read-only refresh of this CPE (job refresh, R0) when a fresh read is wanted"

    def unknown(why: str) -> RuleResult:
        f = {"status": "unknown", "hypothesis": None, "reason": why, "evidence": evidence, "requires_human_confirmation": False,
             "next_read_action": refresh}
        return RuleResult(False, "unknown", f)

    def observed(why: str) -> RuleResult:
        f = {"status": "observed", "hypothesis": None, "reason": why, "evidence": evidence, "requires_human_confirmation": False,
             "next_read_action": "re-read after the next collection"}
        return RuleResult(False, "unknown", f)

    if not links and not conns:
        return unknown("no WAN observation of this CPE")
    if any(c["fresh"] and c["state"] in CONNECTED for c in conns):
        return observed("the CPE reports an established WAN connection")
    if any(not c["fresh"] for c in conns):
        return unknown("a WAN connection of this CPE was last read too long ago to rule out that it is established")
    if not conns:  # only a link reading
        return unknown("the newest WAN observation of this CPE is too old") if not recent_links else observed(
            "only the WAN link was read: not enough for a claim about the connection")
    if all(c["state"] in DOWN for c in conns):
        # only RECENT readings that all say Up (or all Down) say something about the link; anything else claims nothing about it
        cause = {"Down": "wan_link_down", "Up": "wan_session_down"}.get(link, "wan_connection_down")
        what = {"wan_link_down": "the CPE reports no WAN link",
                "wan_session_down": "the CPE reports its WAN link without an established connection (session or provisioning)",
                "wan_connection_down": "the CPE reports no established WAN connection (its link state says nothing about the link)"}[cause]
        if i["onu_link"] == "confirmed" and onu["fresh"]:
            context = ("the linked ONU appears online on the OLT" if i["onu_status"] == "online"
                       else "the linked ONU does not appear online on the OLT")
        else:
            context = "no fresh confirmed ONU link: the ONU was not considered"
        f = {"status": "inferred", "hypothesis": what, "suspected_cause": cause, "context": context, "evidence": evidence,
             "requires_human_confirmation": True,
             "next_read_action": "confirm on the CPE and in the authentication logs; do not change anything from here"}
        return RuleResult(True, cause, f)
    return observed("the reported WAN state is transitional or not conclusive")


def r_d003_v1(i: dict) -> RuleResult:
    """R-D003 v1: the collector (Edge) of these OLTs went silent, so ONU data that looks like dozens of outages may only be OLD data.

    A silent Edge is a fact about the collection infrastructure, not about the network: its ONUs are not current and must not be read
    as ONU outages (ADR-0018 suppresses their incidents the same way). Inputs: heartbeat_age_seconds (int|None), silent (bool, STORED: the
    rule has no clock), revoked (bool), olts, onus_total, onus_not_fresh (counts of the OLTs this Edge collects)."""
    evidence = {"heartbeat_age_seconds": i["heartbeat_age_seconds"], "silent": bool(i["silent"]), "olts": int(i["olts"]),
                "onus_total": int(i["onus_total"]), "onus_not_fresh": int(i["onus_not_fresh"])}

    def done(status: str, why: str) -> RuleResult:
        f = {"status": status, "hypothesis": None, "reason": why, "evidence": evidence, "requires_human_confirmation": False,
             "next_read_action": "re-read after the next heartbeat of this Edge"}
        return RuleResult(False, "unknown", f)

    if i["revoked"]:
        return done("unknown", "this Edge was revoked: it is not expected to report")
    if i["heartbeat_age_seconds"] is None:
        return done("unknown", "this Edge never sent a heartbeat: nothing is known about its collection")
    if not i["silent"]:
        # a heartbeat proves the Edge process is alive, NOT that its OLT readings are current: say only what the counts show
        if int(i["onus_total"]) == 0:
            return done("observed", "the Edge is reporting (recent heartbeat); no ONU is known for its OLTs, so nothing is said about their data")
        if int(i["onus_not_fresh"]) > 0:
            return done("observed", f"the Edge is reporting (recent heartbeat), but {int(i['onus_not_fresh'])} of {int(i['onus_total'])} "
                                    "ONU readings are old: read them as old data, not as outages")
        return done("observed", "the Edge is reporting (recent heartbeat) and every known ONU reading is recent")
    total, stale = int(i["onus_total"]), int(i["onus_not_fresh"])
    if total == 0:
        data = "no ONU is known for its OLTs"
    elif stale == total:
        data = f"all {total} known ONU readings are old"
    elif stale > 0:
        data = f"{stale} of {total} known ONU readings are old and the rest will age without a new collection"
    else:
        data = f"the {total} known ONU readings are still recent but will age without a new collection"
    f = {"status": "inferred", "hypothesis": "this Edge stopped reporting: its OLT readings will not be renewed, so an ONU that looks offline may only be old data",
         "suspected_cause": "edge_unreachable", "context": data, "evidence": evidence, "requires_human_confirmation": True,
         "next_read_action": "check the Edge host and its link to the cloud; do not treat the ONUs of its OLTs as offline from here"}
    return RuleResult(True, "edge_unreachable", f)


def r_d004_v1(i: dict) -> RuleResult:
    """R-D004 v1: the ONU is ONLINE on the OLT but its CPE has not informed the ACS recently.

    This is NOT a claim that the subscriber has no internet: it points at the ACS session (NAT, reachability, periodic inform, controller
    coverage) rather than at the access network. It applies only to a confirmed ONU link, a fresh ONU reading and an ONU that is online;
    anything else claims nothing. Inputs: onu_link ("confirmed"|"none"), onu_status (str|None), onu_fresh (bool), inform_age_seconds
    (int|None) and inform_fresh (bool), plus snapshot_fresh (bool): whether the CPE snapshot that carried the Inform time is itself recent.
    All STORED: the rule has no clock. An old snapshot may hold an old Inform while the ACS already has newer ones, so it claims nothing."""
    evidence = {"onu": {"link": i["onu_link"], "status": i["onu_status"], "fresh": bool(i["onu_fresh"])},
                "inform_age_seconds": i["inform_age_seconds"], "inform_fresh": bool(i["inform_fresh"]),
                "snapshot_fresh": bool(i["snapshot_fresh"])}

    def done(status: str, why: str, nxt: str = "re-read after the next collection") -> RuleResult:
        f = {"status": status, "hypothesis": None, "reason": why, "evidence": evidence, "requires_human_confirmation": False,
             "next_read_action": nxt}
        return RuleResult(False, "unknown", f)

    if i["onu_link"] != "confirmed":
        return done("unknown", "no confirmed ONU link: the OLT and the ACS cannot be compared for this CPE")
    if not i["onu_fresh"]:
        return done("unknown", "the ONU reading is too old to compare with the ACS", "wait for the next collection of this OLT")
    if i["onu_status"] != "online":
        return done("observed", "the linked ONU is not online on the OLT: this rule applies only to an online ONU")
    if i["inform_age_seconds"] is None:
        return done("unknown", "no Inform time is known for this CPE", "request a read-only refresh of this CPE (job refresh, R0)")
    if not i["snapshot_fresh"]:
        return done("unknown", "the CPE snapshot that carried the Inform time is itself old: the ACS may already have a newer one",
                    "wait for the next collection of the ACS")
    if i["inform_fresh"]:
        return done("observed", "the CPE informed the ACS recently")
    f = {"status": "inferred", "hypothesis": "the ONU is online on the OLT but its CPE has not informed the ACS recently",
         "suspected_cause": "acs_session_stale", "evidence": evidence, "requires_human_confirmation": True,
         "next_read_action": "check the ACS session, NAT and controller coverage; this does not mean the subscriber has no internet"}
    return RuleResult(True, "acs_session_stale", f)


@dataclass(frozen=True)
class Rule:
    id: str
    version: int
    title: str
    description: str
    subject: str                              # what one input row describes
    evaluate: Callable[[dict], RuleResult]


RULES: dict[tuple[str, int], Rule] = {
    ("R-D001", 1): Rule(
        "R-D001", 1, "Queda coletiva de acesso na PON",
        "Várias ONUs da mesma PON caíram juntas (online -> fora) em dado recente; ONUs cronicamente offline não contam.",
        "pon", r_d001_v1),
    ("R-D002", 1): Rule(
        "R-D002", 1, "Estado da WAN informado pelo CPE",
        "O que o CPE informa da sua WAN (enlace e conexão) em leitura recente do cache do ACS; sem leitura recente, nada é afirmado.",
        "cpe", r_d002_v1),
    ("R-D003", 1): Rule(
        "R-D003", 1, "Coletor (Edge) sem sinal",
        "O Edge que coleta estas OLTs parou de reportar: os dados de ONU dele estão velhos e não provam queda de ONU.",
        "edge", r_d003_v1),
    ("R-D004", 1): Rule(
        "R-D004", 1, "ONU online e CPE sem Inform recente",
        "A ONU está online na OLT, mas o CPE não informou o ACS recentemente: aponta a sessão com o ACS, não a rede de acesso.",
        "cpe", r_d004_v1),
}


def latest(rule_id: str) -> Rule | None:
    versions = [v for (r, v) in RULES if r == rule_id]
    return RULES[(rule_id, max(versions))] if versions else None


def run(rule: Rule, inputs: list[dict]) -> list[dict]:
    """Findings for each input row, in input order. Deterministic: same inputs and rule version, same output."""
    out = []
    for row in inputs:
        f = dict(rule.evaluate(row).finding)
        f.update({"finding_id": f"{rule.id}/v{rule.version}/{row['subject_id']}", "rule_id": rule.id, "rule_version": rule.version,
                  "evidence_refs": [{"type": rule.subject, "id": row["subject_id"]}]})
        out.append(f)
    return out
