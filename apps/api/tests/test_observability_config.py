"""Observability as shipped in the repository (ADR-0042): compose profile, pinned images, loopback-only ports, no secret in a file, Prometheus rules, Grafana dashboards.
Pure file checks (plus promtool when it or the pinned image is available): nothing here starts a container of the stack."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.core import metrics as m

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "infra" / "compose" / "compose.yaml"
OBS = ROOT / "infra" / "observability"
PROM = OBS / "prometheus"
GRAFANA = OBS / "grafana"
OBS_SERVICES = {"fibercore-exporter", "nats-exporter", "prometheus", "grafana"}
# Metric names that are NOT ours: checked against the live exporters on 2026-11-11 (nats exporter 0.20.1) and Prometheus itself.
EXTERNAL_METRICS = {"up", "ALERTS", "ALERTS_FOR_STATE", "jetstream_consumer_num_pending", "jetstream_consumer_num_ack_pending"}
KNOWN = set(m.API_METRICS) | set(m.EXPORTER_METRICS) | EXTERNAL_METRICS


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text())


def _metric_names(expr: str) -> set[str]:
    names = set(re.findall(r"\b((?:fibercore|jetstream|gnatsd)_[a-z0-9_]+|ALERTS(?:_FOR_STATE)?|up)\b(?=\s*(?:\{|\[|\)|\s|,|$))", expr))
    return {re.sub(r"_(bucket|sum|count)$", "", n) if n.startswith("fibercore_http_request_duration_seconds") else n for n in names}


def _exprs_of_rules():
    out = []
    for g in yaml.safe_load((PROM / "rules" / "fibercore.rules.yml").read_text())["groups"]:
        for r in g["rules"]:
            out.append((r["alert"], r["expr"]))
    return out


# ---- compose -------------------------------------------------------------------------------------
def test_observability_services_exist_only_behind_the_profile(compose):
    services = compose["services"]
    assert OBS_SERVICES <= set(services)
    for name in OBS_SERVICES:
        assert services[name].get("profiles") == ["observability"], f"{name} would start by default"
    for name, svc in services.items():
        if name not in OBS_SERVICES:
            assert "observability" not in (svc.get("profiles") or [])


def test_host_ports_are_loopback_only_and_only_prometheus_and_grafana_publish_any(compose):
    for name in OBS_SERVICES:
        for p in compose["services"][name].get("ports", []):
            assert str(p).startswith("127.0.0.1:"), f"{name} publishes {p} beyond loopback"
    assert {n for n in OBS_SERVICES if compose["services"][n].get("ports")} == {"prometheus", "grafana"}   # exporters are reachable on the control network only


def test_third_party_images_are_pinned_by_tag_and_digest(compose):
    for name in ("nats-exporter", "prometheus", "grafana"):
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", compose["services"][name]["image"]), name
    assert "build" in compose["services"]["fibercore-exporter"]   # the exporter is our own image (the API image)


def test_no_secret_value_in_the_compose_file_or_the_observability_files(compose):
    for name in OBS_SERVICES:
        for k, v in (compose["services"][name].get("environment") or {}).items():
            if re.search(r"PASSWORD|TOKEN|SECRET|KEY|DSN|DATABASE_URL", k, re.I):
                assert k.endswith("__FILE") or "${" in str(v), f"{name}.{k} carries a literal"
    for sec in compose["secrets"].values():
        assert set(sec) == {"environment"}, "secrets come from the environment of the invocation, never from a path or a literal"
    raw = COMPOSE.read_text()
    assert "GF_SECURITY_ADMIN_PASSWORD:" not in raw   # only the __FILE form exists
    for f in [*OBS.rglob("*")]:
        if f.is_file() and f.suffix in {".yml", ".yaml", ".json"}:
            txt = f.read_text()
            assert not re.search(r"(?i)(password|passwd|secret|api[_-]?key)\"?\s*[:=]\s*\"?[A-Za-z0-9+/_-]{8,}", txt), f"possible literal secret in {f}"
            assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", txt), f"an IP address in {f}"


def test_grafana_is_locked_down_and_reads_its_password_from_a_file(compose):
    env = compose["services"]["grafana"]["environment"]
    assert env["GF_SECURITY_ADMIN_PASSWORD__FILE"] == "/run/secrets/grafana_admin_password"
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false" and env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert env["GF_ANALYTICS_REPORTING_ENABLED"] == "false" and env["GF_ANALYTICS_CHECK_FOR_UPDATES"] == "false"
    for name in OBS_SERVICES:
        svc = compose["services"][name]
        assert svc["security_opt"] == ["no-new-privileges:true"] and svc["cap_drop"] == ["ALL"]


def test_the_exporter_mounts_the_backup_directory_read_only_without_creating_it(compose):
    vol = compose["services"]["fibercore-exporter"]["volumes"][0]
    assert vol["read_only"] is True and vol["bind"]["create_host_path"] is False and vol["target"] == "/backups"
    assert (OBS / "no-backup-dir").is_dir()   # the default source exists (and is empty), so an unset variable does not make compose create a root-owned directory


def test_api_metrics_token_defaults_to_off(compose):
    assert compose["services"]["api-core"]["environment"]["METRICS_TOKEN"] == "${FIBERCORE_METRICS_TOKEN:-}"


def test_config_mounts_point_at_files_that_exist(compose):
    for name in ("prometheus", "grafana"):
        for v in compose["services"][name]["volumes"]:
            if isinstance(v, str) and v.startswith("../observability"):
                assert (COMPOSE.parent / v.split(":")[0]).resolve().exists(), v


def test_the_proxies_refuse_api_metrics_before_they_forward_api(compose):
    for name in ("Caddyfile.dev", "Caddyfile.upstream", "Caddyfile.example"):
        txt = (ROOT / "infra" / "deploy" / name).read_text()
        assert txt.index("@apimetrics path /api/metrics /api/metrics/*") < txt.index("@api path /api /api/*"), f"{name}: /api/metrics must be decided before /api/*"
    assert "location ~ ^/api/metrics(/|$) { return 404; }" in (ROOT / "infra" / "deploy" / "nginx" / "fibercore.devops.k3gsolutions.com.br.conf").read_text()
    assert "/api/metrics" in (ROOT / "scripts" / "test-proxy.sh").read_text()


# ---- prometheus ----------------------------------------------------------------------------------
def test_scrape_targets_match_compose_services_and_ports(compose):
    cfg = yaml.safe_load((PROM / "prometheus.yml").read_text())
    jobs = {j["job_name"]: j for j in cfg["scrape_configs"]}
    assert set(jobs) == {"prometheus", "fibercore-api", "fibercore-exporter", "nats"}
    assert jobs["fibercore-api"]["static_configs"][0]["targets"] == ["api-core:8000"]
    assert jobs["fibercore-exporter"]["static_configs"][0]["targets"] == ["fibercore-exporter:9101"]
    assert jobs["nats"]["static_configs"][0]["targets"] == ["nats-exporter:7777"]
    cmd = compose["services"]["nats-exporter"]["command"]
    assert cmd[cmd.index("-port") + 1] == "7777" and cmd[-1] == "http://nats:8222" and "-jsz=all" in cmd
    assert jobs["fibercore-api"]["authorization"]["credentials_file"] == "/run/secrets/fibercore_metrics_token"
    assert compose["services"]["prometheus"]["secrets"][0]["target"] == "fibercore_metrics_token"
    assert cfg["rule_files"] == ["/etc/prometheus/rules/*.yml"] and "alerting" not in cfg


def test_alert_rules_are_well_formed_and_only_use_metrics_that_exist():
    rules = _exprs_of_rules()
    names = [n for n, _ in rules]
    assert len(names) == len(set(names)) and len(names) >= 12
    for g in yaml.safe_load((PROM / "rules" / "fibercore.rules.yml").read_text())["groups"]:
        for r in g["rules"]:
            assert r["labels"]["severity"] in {"critical", "warning"} and r["for"] and r["annotations"]["summary"] and r["annotations"]["description"]
    required = {"FiberCoreEdgeSilent", "FiberCoreApi5xx", "FiberCoreOutboxBacklog", "FiberCoreDiskLow", "FiberCoreBackupStale", "FiberCoreApiDown"}
    assert required <= set(names)
    for n, e in rules:
        used = _metric_names(e)
        assert used, f"{n}: no metric found in the expression"
        assert used <= KNOWN, f"{n} uses unknown metrics {used - KNOWN}"


def test_every_exported_metric_is_used_on_a_dashboard_or_an_alert():
    used: set[str] = set()
    for _, e in _exprs_of_rules():
        used |= _metric_names(e)
    for f in (GRAFANA / "dashboards").glob("*.json"):
        for t in _targets(json.loads(f.read_text())):
            used |= _metric_names(t["expr"])
    unused = set(m.API_METRICS) | set(m.EXPORTER_METRICS)
    unused -= used
    assert not unused, f"exported but on no dashboard or alert: {sorted(unused)}"


def _targets(dash):
    for p in dash["panels"]:
        yield from p.get("targets", [])


# ---- grafana -------------------------------------------------------------------------------------
def test_dashboards_are_valid_provisioned_json_with_known_metrics():
    ds = yaml.safe_load((GRAFANA / "provisioning" / "datasources" / "prometheus.yml").read_text())["datasources"][0]
    prov = yaml.safe_load((GRAFANA / "provisioning" / "dashboards" / "fibercore.yml").read_text())["providers"][0]
    assert prov["options"]["path"] == "/var/lib/fibercore-dashboards" and ds["editable"] is False and ds["url"] == "http://prometheus:9090"
    files = sorted((GRAFANA / "dashboards").glob("*.json"))
    assert len(files) >= 2
    uids = set()
    for f in files:
        d = json.loads(f.read_text())
        assert d["uid"] not in uids and d["title"] and d["panels"]
        uids.add(d["uid"])
        ids = [p["id"] for p in d["panels"]]
        assert len(ids) == len(set(ids))
        for p in d["panels"]:
            if p["type"] == "row":
                continue
            assert p["datasource"]["uid"] == ds["uid"], f"{f.name}: panel {p['title']} not bound to the provisioned datasource"
            assert p["targets"], p["title"]
            for t in p["targets"]:
                assert t["datasource"]["uid"] == ds["uid"]
                used = _metric_names(t["expr"])
                assert used and used <= KNOWN, f"{f.name}/{p['title']}: unknown metrics {used - KNOWN}"
        assert "http://" not in f.read_text() and "https://" not in f.read_text()   # nothing external, no link out


def test_dashboards_never_group_by_an_identifier_label():
    banned = re.compile(r"by\s*\([^)]*\b(tenant|tenant_id|edge|edge_id|olt|olt_id|ip|serial|user|email|customer)\b", re.I)
    for f in (GRAFANA / "dashboards").glob("*.json"):
        assert not banned.search(f.read_text())
    for _, e in _exprs_of_rules():
        assert not banned.search(e)


# ---- promtool ------------------------------------------------------------------------------------
def test_promtool_accepts_the_config_the_rules_and_passes_the_rule_unit_tests():
    has_promtool = shutil.which("promtool") is not None
    image = re.search(r"prom/prometheus:[^ \"']+@sha256:[0-9a-f]{64}", COMPOSE.read_text()).group(0)
    if not has_promtool:
        if not shutil.which("docker") or subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode != 0:   # noqa: S603, S607
            pytest.skip("neither promtool nor the pinned Prometheus image is available locally (run scripts/observability-validate.sh where one is)")
    r = subprocess.run([str(ROOT / "scripts" / "observability-validate.sh")], capture_output=True, text=True, timeout=300)  # noqa: S603
    assert r.returncode == 0, r.stdout + r.stderr
    assert "observability-validate: OK" in r.stdout
