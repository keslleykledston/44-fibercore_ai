"""Valida o adendo v2.2 integrado: pacote intacto, contratos coerentes com a API REAL, cobertura de IDs e nada declarado pronto sem existir."""
import hashlib
import json
import re
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
ADD = ROOT / "docs" / "addenda" / "v2.2"

# 1) pacote original intacto (checksums do próprio adendo)
for line in (ADD / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    digest, name = line.split(None, 1)
    name = name.strip().lstrip("*")
    f = ADD / name
    assert f.is_file(), f"arquivo do adendo ausente: {name}"
    assert hashlib.sha256(f.read_bytes()).hexdigest() == digest, f"adendo ALTERADO (deve permanecer intacto): {name}"

# 2) schema de eventos: válido, aceita um evento completo e recusa um sem `quality`
ev_schema = json.loads((ADD / "contracts" / "events.v2.2.schema.json").read_text(encoding="utf-8"))
jsonschema.Draft202012Validator.check_schema(ev_schema)
event = {"event_id": "00000000-0000-4000-8000-0000000000e1", "schema_version": "1", "tenant_id": "10000000-0000-4000-8000-000000000001",
         "subject_id": "00000000-0000-4000-8000-000000000001", "type": "device.capabilities.changed", "source": "capability_registry",
         "occurred_at": "2026-10-29T12:00:00-04:00", "ingested_at": "2026-10-29T12:00:01-04:00", "quality": "fresh"}
v = jsonschema.Draft202012Validator(ev_schema)
assert not list(v.iter_errors(event)), [e.message for e in v.iter_errors(event)]
assert list(v.iter_errors({k: x for k, x in event.items() if k != "quality"})), "evento sem quality deveria ser recusado"

# 3) exemplo de QoE conforme o schema proposto (score null + insufficient_data, nunca 0)
add_api = yaml.safe_load((ADD / "contracts" / "fibercore-v2.2-additive.openapi.yaml").read_text(encoding="utf-8"))
qoe = json.loads((ADD / "examples" / "qoe-insufficient.synthetic.json").read_text(encoding="utf-8"))
jsonschema.validate({k: qoe[k] for k in ("score_type", "status", "score", "coverage", "algorithm_version")}, add_api["components"]["schemas"]["QoeScore"])
assert qoe["score"] is None and qoe["status"] == "insufficient_data"

# 4) contrato reconciliado x API REAL (código FastAPI importado) x proxy
import sys

sys.path.insert(0, str(ROOT / "apps" / "api"))
from fastapi.routing import APIRoute  # noqa: E402

from app.main import app  # noqa: E402


def _code_routes(routes):
    for r in routes:
        if isinstance(r, APIRoute):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                yield m.lower(), r.path
        elif hasattr(r, "original_router"):
            yield from _code_routes(r.original_router.routes)


norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p)  # noqa: E731
CODE = {(m, norm(p)) for m, p in _code_routes(app.routes)}
assert all(p.startswith("/v1/") or p in ("/livez", "/readyz", "/version") for _, p in CODE), "rota do core fora de /v1"
proxy = (ROOT / "infra" / "deploy" / "Caddyfile.upstream").read_text(encoding="utf-8")
assert re.search(r"^\s*uri strip_prefix /api\s*$", proxy, re.M), "o proxy deveria remover exatamente o prefixo /api (ADR-0012)"

real = yaml.safe_load((ROOT / "contracts" / "fibercore-v2.openapi.yaml").read_text(encoding="utf-8"))
rec = yaml.safe_load((ADD / "contracts" / "fibercore-v2.2-reconciled.openapi.yaml").read_text(encoding="utf-8"))
assert rec["servers"][0]["url"] == real["servers"][0]["url"] == "/api/v1", "prefixo PÚBLICO divergente"
HTTP = ("get", "post", "put", "delete", "patch")
SPEC = {(m, norm("/v1" + p)) for p, ops in real["paths"].items() for m in ops if m in HTTP}  # público /api/v1 -> interno /v1

# deriva contrato x código: tem de ser EXATAMENTE a conhecida (C-19 da GAP); deriva nova reprova
KNOWN_DOCUMENTED_NOT_IMPLEMENTED = {
    ("get", "/v1/integrations/erp"), ("post", "/v1/integrations/erp"),
    ("post", "/v1/integrations/erp/{}/sync"), ("post", "/v1/copilot/suggestions"),
}
HEALTH = {("get", "/livez"), ("get", "/readyz"), ("get", "/version")}
assert SPEC - CODE == KNOWN_DOCUMENTED_NOT_IMPLEMENTED, f"deriva contrato->código mudou: {sorted(SPEC - CODE)}"
assert CODE - SPEC - HEALTH == set(), f"rota no código sem contrato: {sorted(CODE - SPEC - HEALTH)}"
GAP_NORM = norm((ADD / "GAP_ANALYSIS.md").read_text(encoding="utf-8"))
for m, p in KNOWN_DOCUMENTED_NOT_IMPLEMENTED:
    assert p.replace("/v1", "", 1) in GAP_NORM, f"deriva sem registro na GAP_ANALYSIS: {p}"

REC = {}
for path, ops in rec["paths"].items():
    for method, op in ops.items():
        fid, status = op.get("x-fc22-id"), op.get("x-status")
        assert re.fullmatch(r"FC22-0\d\d", str(fid)), f"{method} {path}: x-fc22-id ausente"
        assert status in ("implemented", "planned"), f"{method} {path}: x-status inválido"
        key = (method, norm("/v1" + path))
        REC[key] = status
        assert (status == "implemented") == (key in CODE), f"{method} {path}: x-status={status} mas rota no CÓDIGO={key in CODE}"
        assert ((status == "planned") and key in SPEC) <= (key in KNOWN_DOCUMENTED_NOT_IMPLEMENTED), f"{method} {path}: planned colide com rota já documentada"
# toda operação do contrato vigente sobre capabilities / jobs/preview precisa constar no reconciliado
for m, p in SPEC:
    if p.endswith("/capabilities") or p.endswith("/jobs/preview"):
        assert (m, p) in REC, f"operação existente omitida do reconciliado: {m} {p}"

# 5) rastreabilidade: todos os FC22 no backlog e na análise; todos os AC na matriz de testes; ADRs 0019-0023 com Status
backlog = (ROOT / "docs" / "product" / "ROADMAP_BACKLOG.md").read_text(encoding="utf-8")
gap = (ADD / "GAP_ANALYSIS.md").read_text(encoding="utf-8")
for n in range(1, 19):
    assert f"FC22-{n:03d}" in backlog, f"FC22-{n:03d} fora do backlog integrado"
    assert f"FC22-{n:03d}" in gap, f"FC22-{n:03d} fora da análise de GAP"
tests = (ADD / "TEST_DESIGN.md").read_text(encoding="utf-8")
for n in range(1, 19):
    assert f"AC-{n:03d}" in tests, f"AC-{n:03d} fora do desenho de testes"
for adr in sorted((ROOT / "docs" / "wiki" / "adr").glob("ADR-00[12][0-9]-*.md")):
    if int(adr.name[4:8]) >= 19:
        assert re.search(r"^Status: ", adr.read_text(encoding="utf-8"), re.M), f"{adr.name}: sem Status"
assert len(list((ROOT / "docs" / "wiki" / "adr").glob("ADR-002[0-3]-*.md"))) == 4 and (ROOT / "docs/wiki/adr/ADR-0019-capability-registry.md").is_file()

# 6) nada sensível no adendo (exemplos sintéticos)
for f in ADD.rglob("*"):
    if f.is_file() and f.suffix in {".md", ".json", ".yaml", ".yml"}:
        t = f.read_text(encoding="utf-8")
        assert not re.search(r"BEGIN [A-Z ]*PRIVATE KEY|snmp-?community\s*[:=]|password\s*[:=]\s*\S{6,}", t, re.I), f"possível segredo em {f}"
print("PASS: adendo v2.2 intacto; contratos reconciliados com a API real; 18 FC22 e 18 AC rastreados; ADRs 0019-0023")
