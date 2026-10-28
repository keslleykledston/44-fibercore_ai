from pathlib import Path
import json
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"node_modules", ".next", ".venv", "build", ".git"}  # artefatos de build/dependências não são parte do kit


def _files(pattern):
    return [p for p in ROOT.rglob(pattern) if not SKIP & set(p.relative_to(ROOT).parts)]


YAMLS = _files("*.yaml") + _files("*.yml")
for path in YAMLS:
    with path.open(encoding="utf-8") as f:
        yaml.safe_load(f)
for path in _files("*.json"):
    with path.open(encoding="utf-8") as f:
        json.load(f)
manifest = yaml.safe_load((ROOT / "configs/modules.yaml").read_text(encoding="utf-8"))
ids = [m["id"] for m in manifest["modules"]]
assert len(set(ids)) == len(ids), "duplicate module ID"
assert "acs-cwmp" in ids and "usp-tr369" in ids
assert all(not p.get("certified_operations") for p in yaml.safe_load((ROOT / "configs/catalog/olts/brazil-seed.yaml").read_text())['profiles'])
api = yaml.safe_load((ROOT / "contracts/fibercore-v2.openapi.yaml").read_text(encoding="utf-8"))
assert api['openapi'].startswith('3.')
assert len(api['paths']) >= 9
deploy = yaml.safe_load((ROOT / "configs/deployment/public-domain.yaml").read_text(encoding="utf-8"))
assert deploy["public_frontend"]["hostname"] == "fibercore.devops.k3gsolutions.com.br"
assert api["servers"][0]["url"] == "/api/v1", "API public prefix drift"
assert (ROOT / "docs/ux/DESIGN_SYSTEM_IOS_LIKE.md").is_file()
assert (ROOT / "docs/engineering/SCREENSHOT_AND_HOWTO_PIPELINE.md").is_file()
print(f"PASS: {len(YAMLS)} YAML, schemas, {len(ids)} modules, {len(api['paths'])} paths; domain/UX/how-to contracts")
