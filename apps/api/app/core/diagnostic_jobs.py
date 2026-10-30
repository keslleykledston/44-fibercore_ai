"""Assembly of a diagnostic job's evidence and findings (SD-001, ADR-0028). PURE: JSON-able inputs in, evidence/findings out.

No clock, no database, no network, nothing that can write to equipment, nothing invented: every finding cites the evidence it stands on,
a missing or old observation becomes `insufficient_evidence` (never a healthy verdict, never a zero) and a hypothesis from a rule stays a
hypothesis (`possible`/`likely`), never `confirmed`. Only a plain fact the OLT reports (the ONU is not online) is `confirmed`, and it
says nothing about the cause. Evidence ids are opaque and carry no serial."""
from __future__ import annotations

ONU_STATES = {"online", "offline", "los", "dying_gasp"}   # words of the contract's StateValue that the OLT snapshot can produce
DOWN_STATES = {"offline", "los", "dying_gasp"}
WAN_METRICS = {"wan_link_status", "wan_connection_status", "uptime_seconds"}   # evidence shown for the WAN
RULE_WAN_METRICS = {"wan_link_status", "wan_connection_status"}   # the ones R-D002 reads: only these may back a WAN finding
UNITS = {"uptime_seconds": "seconds", "pon_onus_online": "count", "pon_onus_recent_drops": "count"}
STATE_PT = {"offline": "fora do ar", "los": "sem sinal óptico (LOS)", "dying_gasp": "desligada por falta de energia (dying gasp)"}
CAUSE_PT = {
    "wan_link_down": "O CPE informa a WAN sem enlace; hipótese a confirmar no equipamento.",
    "wan_session_down": "O CPE informa o enlace da WAN ativo sem conexão estabelecida (sessão/provisionamento); hipótese a confirmar.",
    "wan_connection_down": "O CPE não informa conexão WAN estabelecida e o enlace não é conclusivo; hipótese a confirmar.",
}


def _span(seconds: int) -> str:
    return f"{seconds // 3600} h" if seconds % 3600 == 0 else (f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds} s")


def _slug(scope: str) -> str:
    return scope.replace("/", "-")


def _evidence(eid: str, source: str, status: str, metric: str, value, captured_at: str, received_at: str | None = None,
              method: str | None = None) -> dict:
    e = {"evidence_id": eid, "source_type": source, "status": status, "metric": metric, "value": value,
         "unit": UNITS.get(metric, "dBm" if metric == "rx_optical_power" else ""), "captured_at": captured_at, "confidence": "observed"}
    if received_at:
        e["received_at"] = received_at
    if method:
        e["method"] = method
    return e


def assemble(subjects: list[dict], domains: list[str], truncated: bool = False) -> dict:
    """subjects: one per ONU of the customer:
    {"n": int, "onu": {"status", "rx_dbm", "observed_at", "fresh"}, "pon_finding": dict | None,
     "pon": None | {"online": int, "recent_drops": int, "window_seconds": int, "reference_at": str | None, "fresh": bool},
                                                                                       (the aggregate R-D001 judged and its window)
     "cpe": None | {"states": [{"metric", "scope", "value", "captured_at", "received_at", "fresh"}], "finding": dict | None}}"""
    evidences: list[dict] = []
    findings: list[dict] = []
    seen: set[tuple] = set()

    def finding(category: str, certainty: str, ids: list[str], explanation: str) -> None:
        key = (category, certainty, tuple(sorted(ids)))
        if key not in seen:
            seen.add(key)
            findings.append({"category": category, "certainty": certainty, "evidence_ids": sorted(set(ids)), "explanation": explanation})

    for s in subjects:
        n, onu = s["n"], s["onu"]
        status_id = f"ev-onu{n}-status"
        if "pon" in domains:
            known = onu["status"] in ONU_STATES
            evidences.append(_evidence(status_id, "olt", "available" if onu["fresh"] and known else ("stale" if known else "inconclusive"),
                                       "onu_status", onu["status"] if known else None, onu["observed_at"]))
            if onu["rx_dbm"] is not None:
                evidences.append(_evidence(f"ev-onu{n}-rx", "olt", "available" if onu["fresh"] else "stale", "rx_optical_power",
                                           float(onu["rx_dbm"]), onu["observed_at"]))
            if not onu["fresh"] or not known:
                finding("INCONCLUSIVE", "insufficient_evidence", [status_id],
                        "A última observação da ONU na OLT é antiga ou inconclusiva; nada é afirmado sobre a PON.")
            else:
                if onu["status"] in DOWN_STATES:
                    finding("ONU_OFFLINE", "confirmed", [status_id],
                            f"A OLT informa a ONU {STATE_PT[onu['status']]}; isso não indica a causa.")
                pf, pon = s.get("pon_finding"), s.get("pon")
                if pf and pf["status"] == "inferred" and pon and pon["reference_at"]:
                    # the finding rests on the AGGREGATE the rule judged (ONUs online / recently dropped on the PON), so that is cited too
                    pid = [f"ev-pon{n}-online", f"ev-pon{n}-drops"]
                    pst = "available" if pon["fresh"] else "stale"
                    evidences.append(_evidence(pid[0], "olt", pst, "pon_onus_online", int(pon["online"]), pon["reference_at"]))
                    evidences.append(_evidence(pid[1], "olt", pst, "pon_onus_recent_drops", int(pon["recent_drops"]), pon["reference_at"]))
                    # the evidence schema has no field for the PON or the window, so the explanation states exactly what the cited evidence
                    # is: the aggregate of the PON of the customer's ONU (same n) over the rule's window, and which rule/version judged it
                    finding("PON_MASS_OUTAGE", "likely", [status_id, *pid],
                            f"Na PON da ONU do cliente (ev-onu{n}-status), {int(pon['recent_drops'])} ONUs caíram nos últimos "
                            f"{_span(int(pon['window_seconds']))} e {int(pon['online'])} seguem online "
                            f"(regra {pf['rule_id']} v{pf['rule_version']}); "
                            "hipótese de queda coletiva, a confirmar com o incidente e eventos de campo.")
                elif pf and pf["status"] == "unknown":
                    finding("INCONCLUSIVE", "insufficient_evidence", [status_id],
                            "Não há observação recente suficiente da PON para avaliar queda coletiva.")
        if "wan" in domains:
            cpe = s.get("cpe")
            if cpe is None:
                finding("INCONCLUSIVE", "insufficient_evidence", [],
                        "Não há CPE com vínculo confirmado a esta ONU; a WAN não foi avaliada.")
                continue
            ids = []  # what the rule actually read: only these back a finding (uptime is shown as evidence, not as support)
            for st in cpe["states"]:
                if st["metric"] not in WAN_METRICS:
                    continue
                eid = f"ev-cpe{n}-{st['metric']}-{_slug(st['scope'])}"
                if st["metric"] in RULE_WAN_METRICS:
                    ids.append(eid)
                evidences.append(_evidence(eid, "cpe_cwmp", "available" if st["fresh"] else "stale", st["metric"], st["value"],
                                           st["captured_at"], st["received_at"], "genieacs_nbi"))
            cf = cpe.get("finding")
            if cf is None:
                continue
            if cf["status"] == "inferred" and ids:  # a hypothesis without evidence to cite is not reported as one
                finding("WAN_LINK", "possible", ids, CAUSE_PT[cf["suspected_cause"]])
            elif cf["status"] == "inferred":
                finding("INCONCLUSIVE", "insufficient_evidence", [], "Não há leitura da WAN deste CPE; a WAN não foi avaliada.")
            elif cf["status"] == "unknown" and ids:
                finding("CPE_STALE_DATA", "insufficient_evidence", ids,
                        "A leitura da WAN do CPE é antiga demais para afirmar algo; uma nova leitura pode ser pedida.")
            elif cf["status"] == "unknown":
                finding("INCONCLUSIVE", "insufficient_evidence", [], "Não há leitura da WAN deste CPE; a WAN não foi avaliada.")
    if not subjects:
        finding("INCONCLUSIVE", "insufficient_evidence", [], "Não há ONU aprovada para este cliente; nada foi avaliado.")
    if truncated:
        finding("INCONCLUSIVE", "insufficient_evidence", [],
                "O cliente tem mais ONUs do que o limite avaliado; só as primeiras foram consideradas.")
    return {"status": _status(evidences, findings), "data_quality": _quality(evidences, findings),
            "evidences": evidences, "findings": findings}


def _quality(evidences: list[dict], findings: list[dict]) -> str:
    if not evidences:
        return "unsupported"
    if all(e["status"] != "available" for e in evidences):
        return "stale"
    if any(e["status"] != "available" for e in evidences) or any(f["certainty"] == "insufficient_evidence" for f in findings):
        return "partial"
    return "fresh"


def _status(evidences: list[dict], findings: list[dict]) -> str:
    q = _quality(evidences, findings)
    return {"fresh": "complete", "partial": "partial"}.get(q, "inconclusive")
