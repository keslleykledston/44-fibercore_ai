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

    Inputs: wan_link (str|None), connections (sorted list of connection states), state_fresh (bool), state_age_seconds (int|None),
    onu_link ("confirmed"|"none"), onu_status (str|None), onu_fresh (bool).
    Nothing is concluded without a FRESH observation. A connection counts as down only when EVERY reported connection is in DOWN: a
    transitional or unknown state (Connecting, Dormant, Unknown...) never becomes a claim. The ONU state only adds context and never changes
    the verdict."""
    conns = [str(c) for c in i["connections"]]
    onu = {"link": i["onu_link"], "status": i["onu_status"], "fresh": bool(i["onu_fresh"])}
    evidence = {"wan_link": i["wan_link"], "connections": conns, "state_age_seconds": i["state_age_seconds"], "onu": onu}
    if i["wan_link"] is None and not conns:
        f = {"status": "unknown", "hypothesis": None, "reason": "no WAN observation of this CPE", "evidence": evidence,
             "requires_human_confirmation": False,
             "next_read_action": "request a read-only refresh of this CPE (job refresh, R0) when a fresh read is wanted"}
        return RuleResult(False, "unknown", f)
    if not i["state_fresh"]:
        f = {"status": "unknown", "hypothesis": None, "reason": "the newest WAN observation of this CPE is too old", "evidence": evidence,
             "requires_human_confirmation": False, "next_read_action": "request a read-only refresh of this CPE (job refresh, R0)"}
        return RuleResult(False, "unknown", f)
    if any(c in CONNECTED for c in conns):
        f = {"status": "observed", "hypothesis": None, "reason": "the CPE reports an established WAN connection", "evidence": evidence,
             "requires_human_confirmation": False, "next_read_action": "re-read after the next collection"}
        return RuleResult(False, "unknown", f)
    if conns and all(c in DOWN for c in conns):
        cause = "wan_link_down" if i["wan_link"] == "Down" else "wan_session_down"
        what = ("the CPE reports no WAN link" if cause == "wan_link_down"
                else "the CPE reports its WAN link without an established connection (session or provisioning)")
        if i["onu_link"] == "confirmed" and onu["fresh"]:
            context = ("the linked ONU is online on the OLT: the access layer is up" if i["onu_status"] == "online"
                       else "the linked ONU is not online on the OLT: the CPE state can be a consequence")
        else:
            context = "no fresh confirmed ONU link: the access layer was not considered"
        f = {"status": "inferred", "hypothesis": what, "suspected_cause": cause, "context": context, "evidence": evidence,
             "requires_human_confirmation": True,
             "next_read_action": "confirm on the CPE and in the authentication logs; do not change anything from here"}
        return RuleResult(True, cause, f)
    f = {"status": "observed", "hypothesis": None, "reason": "the reported WAN state is transitional or not conclusive",
         "evidence": evidence, "requires_human_confirmation": False, "next_read_action": "re-read after the next collection"}
    return RuleResult(False, "unknown", f)


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
