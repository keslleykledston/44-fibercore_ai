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

    Inputs: wan_link (str|None) and wan_link_fresh (bool); connections (list of {"state", "fresh"}, sorted); newest_age_seconds and
    oldest_age_seconds of the WAN readings (int|None); onu_link ("confirmed"|"none"), onu_status (str|None), onu_fresh (bool).
    Freshness is per reading, not per CPE: the cache keeps the last row of every connection, so a recent reading of one connection must
    never vouch for an old reading of another. An established connection that is fresh wins; any connection last read too long ago could
    still be established, so the rule says nothing then. A connection counts as down only when EVERY reported connection is fresh and in
    DOWN: a transitional or unknown state (Connecting, Dormant, Unknown...) never becomes a claim. The ONU only adds context and never
    changes the verdict."""
    conns = [{"state": str(c["state"]), "fresh": bool(c["fresh"])} for c in i["connections"]]
    link_fresh = bool(i["wan_link_fresh"])
    onu = {"link": i["onu_link"], "status": i["onu_status"], "fresh": bool(i["onu_fresh"])}
    evidence = {"wan_link": i["wan_link"], "wan_link_fresh": link_fresh, "connections": conns,
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

    if i["wan_link"] is None and not conns:
        return unknown("no WAN observation of this CPE")
    if any(c["fresh"] and c["state"] in CONNECTED for c in conns):
        return observed("the CPE reports an established WAN connection")
    if any(not c["fresh"] for c in conns):
        return unknown("a WAN connection of this CPE was last read too long ago to rule out that it is established")
    if not conns:  # only a link reading
        return unknown("the newest WAN observation of this CPE is too old") if not link_fresh else observed(
            "only the WAN link was read: not enough for a claim about the connection")
    if all(c["state"] in DOWN for c in conns):
        # only a RECENT Up or Down says something about the link; Initializing/Unavailable, not read or old claim nothing about it
        link = i["wan_link"] if link_fresh else None
        cause = {"Down": "wan_link_down", "Up": "wan_session_down"}.get(link, "wan_connection_down")
        what = {"wan_link_down": "the CPE reports no WAN link",
                "wan_session_down": "the CPE reports its WAN link without an established connection (session or provisioning)",
                "wan_connection_down": "the CPE reports no established WAN connection (its link state says nothing about the link)"}[cause]
        if i["onu_link"] == "confirmed" and onu["fresh"]:
            context = ("the linked ONU is online on the OLT: the access layer is up" if i["onu_status"] == "online"
                       else "the linked ONU is not online on the OLT: the CPE state can be a consequence")
        else:
            context = "no fresh confirmed ONU link: the access layer was not considered"
        f = {"status": "inferred", "hypothesis": what, "suspected_cause": cause, "context": context, "evidence": evidence,
             "requires_human_confirmation": True,
             "next_read_action": "confirm on the CPE and in the authentication logs; do not change anything from here"}
        return RuleResult(True, cause, f)
    return observed("the reported WAN state is transitional or not conclusive")


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
