"""QoS-001 (ADR-0039): the quality read of one ONT, built ONLY from data the product already holds. Pure: no clock, no database, no network, no equipment.

A metric always says what it is, where it came from, which scope it describes, when it was collected and how old that is. A value exists only for `valid` and
`stale` metrics; every other state carries `null`, never 0. Nothing here judges a number without a homologated profile (no generic dBm limit), nothing computes a
quality "score", and the global state is never "perfect": it is attention, no anomalies observed, or insufficient data. Hypotheses are declarative rules over the
metrics, each with its evidence, a recommended check and its caveats; with no rule satisfied the answer is "not enough evidence", not a guess."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1
MODES = ("quick", "full")
STATUSES = ("valid", "stale", "not_supported", "not_available", "not_applicable", "failed", "inconclusive")
SOURCES = ("TR069_READ", "TR069_ACTIVE", "OLT_ADAPTER", "SD001", "ACS_CACHE")
GROUPS = ("WAN", "OPTICAL", "ETHERNET", "WIFI", "CPE", "CORE", "INTERNET")
SCOPES = ("SERVICE_WAN", "MGMT_WAN", "WAN_UNCLASSIFIED", "LAN", "PON", "WIFI", "CPE")
# how long a reading is still shown as current. The OLT is collected every 15 min and a round takes up to ~3 min, hence 20 min for the optical group;
# adjust to the real collection, never by adding polling (ADR-0039 item 1).
TTL_S = {"WAN": 900, "OPTICAL": 1200, "ETHERNET": 900, "WIFI": 300, "CPE": 900}
DEGRADED_RATIO = 0.5   # a comparable result below this fraction of its reference is "degraded" for the path rules (explicit, so it can be argued with)
MIN_PING_SAMPLE = 3

LINK_BAD = frozenset({"Down", "Unavailable"})
CONN_BAD = frozenset({"Disconnected", "Unconfigured", "Down", "LowerLayerDown", "NotPresent", "Error"})


@dataclass(frozen=True)
class StateRow:
    """One `cpe_state` row (the ACS cache as the Edge reported it)."""
    metric: str
    scope: str
    value: Any
    captured_at: datetime


@dataclass(frozen=True)
class OnuFact:
    status: str | None
    rx_dbm: float | None
    observed_at: datetime | None


@dataclass(frozen=True)
class SpeedFact:
    """A finished SD-001 result, referenced (never recomputed). `direction` download|upload, `target_kind` CORE|INTERNET."""
    run_id: str
    group_id: str
    direction: str
    target_kind: str
    outcome: str | None
    mbps: float | None
    created_at: datetime


@dataclass(frozen=True)
class Facts:
    now: datetime
    cpe_state: tuple[StateRow, ...] = ()
    onu: OnuFact | None = None
    speed: tuple[SpeedFact, ...] = ()
    optical_profile: tuple[float, float] | None = None   # (min, max) dBm of a HOMOLOGATED profile for this ONU class; None = no judgement is made
    wifi_profile: tuple[float, float] | None = None      # (weakest acceptable RSSI dBm, highest acceptable retry %) of a homologated profile; None = no judgement
    plan_mbps: float | None = None                       # only from an already integrated source; None = no comparison is made
    extra: tuple[dict, ...] = ()                         # metrics from active tests / later readings, already in the contract's shape


def _age(now: datetime, at: datetime | None) -> int | None:
    return None if at is None else max(0, int((now - at).total_seconds()))


def metric(mid: str, group: str, status: str, *, value: Any = None, unit: str | None = None, source: str, scope: str, now: datetime,
           collected_at: datetime | None = None, instance: str | None = None, details: dict | None = None, evidence_ref: str | None = None) -> dict:
    """The contract of one measurement. A value is kept ONLY for valid/stale: absence is never turned into a number."""
    assert status in STATUSES and group in GROUPS and source in SOURCES and scope in SCOPES
    if status not in ("valid", "stale"):
        value = None
    return {
        "id": mid, "group": group, "status": status, "value": value, "unit": unit, "source": source, "scope": scope, "instance": instance,
        "collected_at": collected_at.isoformat() if collected_at else None, "freshness_s": _age(now, collected_at),
        "evidence_ref": evidence_ref, "details": details or {},
    }


def _fresh_status(now: datetime, at: datetime, group: str) -> str:
    return "valid" if (now - at).total_seconds() <= TTL_S[group] else "stale"


def build_metrics(f: Facts) -> list[dict]:
    out: list[dict] = []
    by: dict[str, list[StateRow]] = {}
    for r in f.cpe_state:
        by.setdefault(r.metric, []).append(r)

    def from_state(name: str, mid: str, group: str, scope: str, unit: str | None = None, absent: str = "not_available", why: str = "no_reading") -> None:
        rows = sorted(by.get(name, []), key=lambda r: r.scope)
        if not rows:
            out.append(metric(mid, group, absent, source="ACS_CACHE", scope=scope, now=f.now, details={"reason": why}))
            return
        for r in rows:
            out.append(metric(mid, group, _fresh_status(f.now, r.captured_at, group), value=r.value, unit=unit, source="ACS_CACHE", scope=scope,
                              now=f.now, collected_at=r.captured_at, instance=r.scope))

    # The cache says which WAN object answered, never whether it is the subscriber's service WAN or the management one: the scope says so (Q03). A reading
    # of an unclassified WAN is shown, but it is not sold as a measurement of the subscriber's connection.
    from_state("wan_link_status", "wan.link_status", "WAN", "WAN_UNCLASSIFIED")
    from_state("wan_connection_status", "wan.connection_status", "WAN", "WAN_UNCLASSIFIED")
    from_state("uptime_seconds", "cpe.uptime_s", "CPE", "CPE", unit="s")
    # an absent Wi-Fi reading is "not available", never "not applicable": the cache cannot tell a bridge without a radio from a radio nobody read yet
    from_state("wifi_radio_enabled", "wifi.radio_enabled", "WIFI", "WIFI")
    from_state("wifi_channel", "wifi.channel", "WIFI", "WIFI")

    # Optical and ONU state come from the OLT (never `TR069`), and an ONU without a confirmed link to this CPE has nothing to say about it.
    if f.onu is None:
        out.append(metric("optical.rx_dbm", "OPTICAL", "not_available", source="OLT_ADAPTER", scope="PON", now=f.now, details={"reason": "no_linked_onu"}))
        out.append(metric("onu.status", "OPTICAL", "not_available", source="OLT_ADAPTER", scope="PON", now=f.now, details={"reason": "no_linked_onu"}))
    else:
        o = f.onu
        st = "not_available" if o.observed_at is None else _fresh_status(f.now, o.observed_at, "OPTICAL")
        out.append(metric("onu.status", "OPTICAL", st if o.status else "not_available", value=o.status, source="OLT_ADAPTER", scope="PON", now=f.now,
                          collected_at=o.observed_at, details={} if o.status else {"reason": "no_reading"}))
        rx_st = "not_available" if o.rx_dbm is None or o.observed_at is None else st
        out.append(metric("optical.rx_dbm", "OPTICAL", rx_st, value=o.rx_dbm, unit="dBm", source="OLT_ADAPTER", scope="PON", now=f.now,
                          collected_at=o.observed_at,
                          details={"judged": f.optical_profile is not None} if rx_st in ("valid", "stale") else {"reason": "no_reading"}))
    out.extend(f.extra)
    for s in f.speed:   # COMPLETO: SD-001 is REFERENCED (same run ids), never re-run or recomputed here
        mid = f"speed.{s.direction}_mbps"
        group = "CORE" if s.target_kind == "CORE" else "INTERNET"
        ok = s.outcome == "completed" and s.mbps is not None
        status = "valid" if ok else ("inconclusive" if s.outcome in ("partial", "inconclusive") else "failed" if s.outcome == "error" else "not_available")
        out.append(metric(mid, group, status, value=s.mbps if ok else None, unit="Mbit/s", source="SD001", scope="WAN_UNCLASSIFIED",
                          now=f.now, collected_at=s.created_at, evidence_ref=f"speed-run:{s.run_id}", details={"group_id": s.group_id, "outcome": s.outcome}))
    return out


def _m(metrics: list[dict], mid: str, *, valid_only: bool = True) -> list[dict]:
    return [m for m in metrics if m["id"] == mid and (m["status"] == "valid" or not valid_only)]


def observations(metrics: list[dict]) -> list[dict]:
    """Facts that are already abnormal in the data (not hypotheses). Only CURRENT readings count: a stale one is history."""
    obs = []
    for m in _m(metrics, "wan.link_status"):
        if m["value"] in LINK_BAD:
            obs.append({"code": "WAN_LINK_DOWN", "metric_ids": [m["id"]], "scope": m["scope"], "instance": m["instance"]})
    for m in _m(metrics, "wan.connection_status"):
        if m["value"] in CONN_BAD:
            obs.append({"code": "WAN_CONNECTION_NOT_UP", "metric_ids": [m["id"]], "scope": m["scope"], "instance": m["instance"]})
    for m in _m(metrics, "onu.status"):
        if m["value"] not in ("online", "unknown", None):
            obs.append({"code": "ONU_NOT_ONLINE", "metric_ids": [m["id"]], "scope": m["scope"], "instance": None})
    return obs


def hypotheses(metrics: list[dict], f: Facts) -> list[dict]:
    """Declarative rules (ADR-0039 item 7). Each needs its MINIMUM evidence; none fires on a missing, stale or inconclusive input."""
    out: list[dict] = []

    def add(code: str, label: str, ids: list[str], check: str, caveats: list[str], confidence: str = "low") -> None:
        out.append({"code": code, "label": label, "confidence": confidence, "evidence_metric_ids": ids, "recommended_check": check, "caveats": caveats})

    eth = _m(metrics, "eth.link_speed_mbps")
    if eth and any(m["value"] == 100 for m in eth) and f.plan_mbps and f.plan_mbps > 100:
        add("LAN_LINK_100M", "A porta LAN pode limitar a conexão deste dispositivo; verificar cabeamento e equipamento", ["eth.link_speed_mbps"],
            "Testar com cabo/porta de 1 Gbit/s", ["Link de 100 Mbit/s limita aquela porta; não prova que o plano não chega à ONT"], "medium")
    opt = _m(metrics, "optical.rx_dbm")
    if opt and f.optical_profile is not None and not (f.optical_profile[0] <= opt[0]["value"] <= f.optical_profile[1]):
        add("OPTICAL_ATTENTION", "Indícios de problema no enlace óptico; validar a OLT e a conectorização", ["optical.rx_dbm"],
            "Conferir a leitura na OLT e a conectorização da CTO/ONU",
            ["Uma única amostra de RX não prova rompimento", "A faixa vem do perfil homologado desta classe de ONU"])
    rssi, retry = _m(metrics, "wifi.rssi_dbm"), _m(metrics, "wifi.retry_pct")
    if rssi and retry and f.wifi_profile is not None and rssi[0]["value"] < f.wifi_profile[0] and retry[0]["value"] > f.wifi_profile[1]:
        add("WIFI_POTENTIAL", "Possível limitação de Wi-Fi; testar com um dispositivo cabeado", ["wifi.rssi_dbm", "wifi.retry_pct"],
            "Repetir o teste com um aparelho cabeado", ["Taxa PHY e RSSI não são velocidade útil"])
    core = [m for m in metrics if m["group"] == "CORE" and m["status"] == "valid" and m["id"] == "speed.download_mbps"]
    net = [m for m in metrics if m["group"] == "INTERNET" and m["status"] == "valid" and m["id"] == "speed.download_mbps"]
    if core and net:
        c, n = core[0]["value"], net[0]["value"]
        degraded = lambda v, ref: ref > 0 and v < DEGRADED_RATIO * ref  # noqa: E731
        ids = [core[0]["id"], net[0]["id"]]
        if f.plan_mbps and degraded(c, f.plan_mbps) and degraded(n, f.plan_mbps):
            add("ACCESS_PATH_POTENTIAL", "Possível gargalo no acesso (BNG, CPE ou PON); investigar policer, CPU e PON", ids,
                "Comparar com outro CPE na mesma PON", ["Teste isolado não prova descumprimento de plano", "A CPU alta durante o teste pode ser consequência da carga"])
        elif degraded(n, c):
            add("EXTERNAL_PATH_POTENTIAL", "Possível gargalo em trânsito, rota ou destino; validar o caminho externo", ids,
                "Repetir contra outro destino externo e em outro horário", ["Um destino externo ruim não prova problema de trânsito (servidor sobrecarregado?)"])
    ping = _m(metrics, "ip.loss_pct")
    if ping and ping[0]["details"].get("sample_size", 0) >= MIN_PING_SAMPLE and ping[0]["value"] > 0:
        add("PACKET_LOSS", "Perda observada para o destino medido; comparar com outro alvo", ["ip.loss_pct"], "Repetir para um segundo destino",
            ["Medida originada na ONT; amostra pequena"])
    dns = _m(metrics, "dns.lookup_ok")
    if dns and dns[0]["value"] is False and _m(metrics, "ip.rtt_avg_ms"):
        add("DNS_POTENTIAL", "Possível falha de resolução DNS; testar outros resolvedores", ["dns.lookup_ok", "ip.rtt_avg_ms"],
            "Testar a resolução por outro resolvedor", ["O ping por IP respondeu no mesmo período"])
    return out


def summarize(metrics: list[dict], hyps: list[dict]) -> dict:
    """Four indicators and one honest global state. Never "OK": at most "no anomalies observed", and only with enough current data."""
    obs = observations(metrics)

    def ind(groups: tuple[str, ...]) -> dict:
        ms = [m for m in metrics if m["group"] in groups]
        ids = sorted({m["id"] for m in ms})
        bad = {c for o in obs for c in o["metric_ids"]} & set(ids)
        if bad:
            state = "attention"
        elif any(m["status"] == "valid" for m in ms):
            state = "ok"
        elif any(m["status"] == "stale" for m in ms):
            state = "stale"
        else:
            state = "unknown"
        return {"state": state, "metric_ids": ids}

    indicators = {"wan": ind(("WAN",)), "optical": ind(("OPTICAL",)), "wifi": ind(("WIFI",)), "cpe": ind(("CPE",))}
    current_groups = sum(1 for k in ("wan", "optical", "cpe") if indicators[k]["state"] in ("ok", "attention"))
    if obs or hyps:
        state = "attention"
    elif current_groups >= 2:
        state = "no_anomalies_observed"
    else:
        state = "insufficient_data"
    return {"state": state, "observations": obs, "indicators": indicators,
            "note": "sem evidência suficiente para localizar um gargalo" if not hyps else None}


def run_state(metrics: list[dict]) -> str:
    """`completed` only when nothing that was asked for is missing; otherwise `partial` (a partial run keeps every valid component)."""
    return "completed" if all(m["status"] in ("valid", "not_applicable") for m in metrics) else "partial"
