"""SD-001 (ADR-0025), SD-PR-01: contratos e mocks. Sem endpoint, sem migração, flags desligadas.

Estes testes não exercitam a API (ela ainda não tem nada do SD-001); garantem que o que foi proposto é coerente, não colide com o contrato
canônico e que nenhuma rota do SD-001 existe antes do PR que a implementa.
"""
import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from app.core import features
from app.main import app

ROOT = Path(__file__).resolve().parents[3]
SD = ROOT / "contracts" / "sd001"
FIX = ROOT / "tests" / "fixtures" / "sd001"
CANON = yaml.safe_load((ROOT / "contracts" / "fibercore-v2.openapi.yaml").read_text(encoding="utf-8"))
OVERLAY = yaml.safe_load((SD / "smart-diagnostics.openapi.yaml").read_text(encoding="utf-8"))
EVENTS = yaml.safe_load((SD / "smart-diagnostics.events.yaml").read_text(encoding="utf-8"))
EVIDENCE = json.loads((SD / "evidence-envelope.schema.json").read_text(encoding="utf-8"))
AI_OUT = json.loads((SD / "ai-diagnostic-output.schema.json").read_text(encoding="utf-8"))
METHODS = {"get", "post", "put", "patch", "delete"}


def _ops(doc):
    return {(path, m): op for path, item in doc["paths"].items() for m, op in item.items() if m in METHODS}


def _refs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                yield v
            else:
                yield from _refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _refs(v)


def test_json_schemas_are_valid_and_fixtures_conform():
    for s in (EVIDENCE, AI_OUT):
        Draft202012Validator.check_schema(s)
    ev = json.loads((FIX / "evidence.json").read_text(encoding="utf-8"))
    assert ev and all(not list(Draft202012Validator(EVIDENCE).iter_errors(e)) for e in ev)
    ai = json.loads((FIX / "ai_response.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(AI_OUT).iter_errors(ai))


def test_schemas_reject_malformed_payloads():
    ev = json.loads((FIX / "evidence.json").read_text(encoding="utf-8"))[0]
    for bad in ({**ev, "job_id": "nao-e-uuid-mas-string"}, {**ev, "extra": 1}, {k: v for k, v in ev.items() if k != "measurement"},
                {**ev, "source_type": "ssh_shell"}, {**ev, "status": "ok"}):
        errs = list(Draft202012Validator(EVIDENCE, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(bad))
        assert errs, bad
    ai = json.loads((FIX / "ai_response.json").read_text(encoding="utf-8"))
    for bad in ({**ai, "extra": 1}, {**ai, "status": "done"},
                {**ai, "findings": [{**ai["findings"][0], "evidence_ids": ["a", "a"]}]},
                {**ai, "proposed_actions": [{"action_kind": "cpe_reboot", "rationale": "x"}]}):  # ação sem evidência
        assert list(Draft202012Validator(AI_OUT).iter_errors(bad)), bad


def _v(schema, instance):
    return list(Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(instance))


def _component(name):
    return {"$ref": f"#/components/schemas/{name}", "components": OVERLAY["components"]}


def test_actions_and_conclusions_must_cite_evidence():
    ai = json.loads((FIX / "ai_response.json").read_text(encoding="utf-8"))
    act = ai["proposed_actions"][0]
    assert _v(AI_OUT, {**ai, "proposed_actions": [{**act, "evidence_ids": []}]})  # ação sem evidência
    assert _v(AI_OUT, {**ai, "proposed_actions": [{"action_kind": "run_shell", "rationale": "x", "evidence_ids": ["ev-1"]}]})  # tipo fora da lista
    assert _v(AI_OUT, {**ai, "findings": [{**ai["findings"][0], "evidence_ids": []}]})  # likely sem evidência
    assert not _v(AI_OUT, {**ai, "findings": [{**ai["findings"][0], "certainty": "insufficient_evidence", "evidence_ids": []}]})
    f = {"category": "WIFI_SIGNAL", "certainty": "likely", "evidence_ids": [], "explanation": "x"}
    assert _v(_component("Finding"), f)
    assert not _v(_component("Finding"), {**f, "certainty": "insufficient_evidence"})


def test_sensitive_values_cannot_travel_in_evidence():
    ev = json.loads((FIX / "evidence.json").read_text(encoding="utf-8"))[1]  # wan_link_status = "Up"
    assert not _v(EVIDENCE, ev)
    meas = ev["measurement"]
    for bad in (
        {**ev, "measurement": {**meas, "value": "S3nh4-do-Wi-Fi!"}},  # PSK em texto livre
        {**ev, "measurement": {**meas, "name": "wifi_psk"}},
        {**ev, "measurement": {**meas, "origin": "senha do cliente"}},
        {**ev, "source_ref": "aa:bb:cc:dd:ee:ff"},
        {**ev, "source_ref": "AA-BB-CC-DD-EE-FF"},
        {**ev, "evidence_id": "00:1a:2b:3c:4d:5e"},
        {**ev, "firmware": "user=joao@pppoe"},
        {**ev, "instrument_limitations": ["texto livre com dado do cliente"]},
    ):
        assert _v(EVIDENCE, bad), bad
    # mesma garantia no contrato HTTP
    http = {"evidence_id": "ev-1", "source_type": "cpe_cwmp", "status": "available", "metric": "wan_link_status", "value": "Up",
            "captured_at": "2026-10-29T05:00:10Z"}
    assert not _v(_component("Evidence"), http)
    for bad in ({**http, "value": "S3nh4-do-Wi-Fi!"}, {**http, "metric": "wifi_psk"}, {**http, "evidence_id": "aa:bb:cc:dd:ee:ff"}, {**http, "x": 1}):
        assert _v(_component("Evidence"), bad), bad


def test_narrative_text_rejects_credentials_and_macs_and_is_bounded():
    ai = json.loads((FIX / "ai_response.json").read_text(encoding="utf-8"))
    assert not _v(AI_OUT, ai)
    leaks = ["senha: abc123", "PSK=xyz", "password = hunter2", "token:abc", "usuario: joao@isp", "mac aa:bb:cc:dd:ee:ff", "x" * 1600]
    for leak in leaks:
        assert _v(AI_OUT, {**ai, "summary_pt_br": leak}), leak
        assert _v(AI_OUT, {**ai, "operator_message": leak}), leak
        assert _v(AI_OUT, {**ai, "findings": [{**ai["findings"][0], "explanation": leak}]}), leak
        assert _v(AI_OUT, {**ai, "proposed_actions": [{**ai["proposed_actions"][0], "rationale": leak}]}), leak
        assert _v(_component("Finding"), {"category": "WIFI_SIGNAL", "certainty": "insufficient_evidence", "evidence_ids": [], "explanation": leak}), leak
    for key in ("missing_data", "recommended_tests"):  # códigos, nunca frase livre
        assert _v(AI_OUT, {**ai, key: ["senha do cliente é 1234"]})
    assert _v(AI_OUT, {**ai, "findings": [{**ai["findings"][0], "category": "texto livre"}]})
    assert not _v(AI_OUT, {**ai, "summary_pt_br": "O cliente deve testar perto do roteador e anotar a senha nova no cadastro."})  # a palavra sozinha é legítima


def test_action_parameters_are_strict_per_kind():
    base = {"proposal_id": "11111111-1111-4111-8111-111111111111", "cpe_id": "22222222-2222-4222-8222-222222222222", "risk": "R2",
            "proposal_hash": "a" * 64, "expires_at": "2026-10-30T00:00:00Z", "status": "proposed"}
    ok = {**base, "action_kind": "wifi_channel_change", "parameters": {"band": "5GHz", "channel": 36}}
    assert not _v(_component("ActionProposal"), ok)
    for bad in (
        {**ok, "parameters": {"band": "5GHz", "channel": 36, "psk": "x"}},  # propriedade extra
        {**ok, "parameters": {"band": "5GHz"}},  # faltando
        {**ok, "parameters": {"band": "6GHz", "channel": 36}},
        {k: v for k, v in ok.items() if k != "parameters"},
        {**base, "action_kind": "cpe_reboot", "parameters": {"ssid": "x"}},  # reboot não leva parâmetro
        {**base, "action_kind": "plan_profile_align", "parameters": {"profile_id": "nao-uuid"}},
        {**ok, "action_kind": "factory_reset"},
        {**ok, "tenant_id": "x"},
    ):
        assert _v(_component("ActionProposal"), bad), bad
    assert not _v(_component("ActionProposal"), {**base, "action_kind": "cpe_reboot", "parameters": {}})


def test_job_fixture_conforms_to_the_http_contract():
    job = json.loads((FIX / "diagnostic_job.json").read_text(encoding="utf-8"))
    assert not _v(_component("DiagnosticJob"), job)


def test_job_fixture_cites_only_existing_evidence_and_never_invents_a_value():
    job = json.loads((FIX / "diagnostic_job.json").read_text(encoding="utf-8"))
    ids = {e["evidence_id"] for e in job["evidences"]}
    assert job["run_id"] is None  # o diagnostic_run só nasce quando a regra é executada (ADR-0024)
    assert all(set(f["evidence_ids"]) <= ids for f in job["findings"])
    unsupported = [e for e in job["evidences"] if e["status"] == "unsupported"]
    assert unsupported and all(e["value"] is None for e in unsupported)  # não suportado ≠ 0 Mbps (T05)
    ai = json.loads((FIX / "ai_response.json").read_text(encoding="utf-8"))
    assert all(set(f["evidence_ids"]) <= ids for f in ai["findings"])
    assert all(set(a["evidence_ids"]) <= ids for a in ai["proposed_actions"])


def test_overlay_internal_refs_resolve():
    for ref in _refs(OVERLAY):
        assert ref.startswith("#/"), ref
        node = OVERLAY
        for part in ref[2:].split("/"):
            node = node[part]


def test_overlay_does_not_collide_with_the_canonical_contract():
    overlay, canon = _ops(OVERLAY), _ops(CANON)
    assert overlay and not set(overlay) & set(canon), "caminho+método do SD-001 já existe no contrato canônico"
    ids = [op["operationId"] for op in overlay.values()]
    assert len(ids) == len(set(ids))
    # createDiagnosticRun/getDiagnosticRun do canônico são o motor síncrono (ADR-0024); o assíncrono tem outro nome
    taken = {op["operationId"] for op in canon.values()}
    clash = set(ids) & taken
    assert not clash, f"operationId repetido: {clash}"
    assert not [p for p in OVERLAY["paths"] if "/devices/" in p], "/devices/{id}/capabilities duplicaria /cpes/{id}/capabilities"
    assert "createDiagnosticRun" not in ids and all("/diagnostics/runs" not in p for p in OVERLAY["paths"])


def _norm(path):
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_overlay_is_not_implemented_by_the_api_yet():
    routes = {(_norm(r.path), m.lower()) for r in app.routes for m in getattr(r, "methods", None) or []}
    assert routes, "app sem rotas: o teste estaria vazio"
    for path, method in _ops(OVERLAY):
        assert (_norm("/v1" + path), method) not in routes, f"rota do SD-001 já existe: {method} {path}"


def test_every_write_requires_idempotency_and_nothing_promises_execution():
    for (path, method), op in _ops(OVERLAY).items():
        if method == "post" and not path.endswith("/approvals"):
            names = [p.get("name") or p.get("$ref", "").rsplit("/", 1)[-1] for p in op["parameters"]]
            assert "IdempotencyKey" in names or "Idempotency-Key" in names, (path, method)
        assert any(p.get("$ref", "").endswith("/TenantId") for p in op["parameters"]), (path, method)  # tenant do cabeçalho validado, nunca do corpo
    schemas = OVERLAY["components"]["schemas"]
    assert set(schemas["ExecutionReceipt"]["properties"]["state"]["enum"]) == {"pending_preflight", "blocked"}  # 202 nunca diz "executado"
    assert "executed" not in schemas["ApprovalReceipt"]["properties"]["status"]["enum"]
    for name in ("CreateDiagnosticJob", "ActiveTestRequest", "ApprovalDecision", "ExecutionIntent"):
        assert schemas[name]["additionalProperties"] is False  # corpo estrito: nada de campo livre
    assert "tenant_id" not in json.dumps(schemas)  # tenant nunca vem do cliente
    assert schemas["ActiveTestRequest"]["properties"]["max_duration_seconds"]["maximum"] <= 120


def test_events_follow_the_outbox_convention_and_carry_no_personal_data():
    assert EVENTS["status"] == "proposal"
    for et, spec in EVENTS["events"].items():
        assert "." in et and et == et.lower() and "fibercore." not in et  # event_type do outbox, não subject
        assert spec["aggregate_type"] and spec["payload_required"]
        assert not set(spec["payload_required"]) & set(EVENTS["common"]["forbidden_in_payload"])


def test_flags_exist_default_off_and_are_unknown_safe():
    sd = {k: v for k, v in features.FEATURES.items() if k.startswith("smart_diagnostics_")}
    assert set(sd) == {"smart_diagnostics_jobs", "smart_diagnostics_active_tests", "smart_diagnostics_remediation", "smart_diagnostics_copilot"}
    assert not any(sd.values())


def test_adr_0025_is_accepted():
    adr = (ROOT / "docs" / "wiki" / "adr" / "ADR-0025-integracao-do-feature-pack-sd-001.md").read_text(encoding="utf-8")
    assert adr.splitlines()[2].startswith("Status: Accepted")


def _without_descriptions(node):
    if isinstance(node, dict):
        return {k: _without_descriptions(v) for k, v in node.items() if k not in ("description", "pattern")}
    if isinstance(node, list):
        return [_without_descriptions(v) for v in node]
    return node


@pytest.mark.parametrize("name", ["evidence-envelope.schema.json", "ai-diagnostic-output.schema.json"])
def test_no_secret_like_names_in_contract_schemas(name):
    # só estrutura (chaves e enums): descrições e padrões de rejeição citam justamente o que o contrato impede
    text = json.dumps(_without_descriptions(json.loads((SD / name).read_text(encoding="utf-8")))).lower()
    for bad in ("password", "psk", "passphrase", "secret", "pppoe_user"):
        assert bad not in text
