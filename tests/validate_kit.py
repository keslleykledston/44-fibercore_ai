from pathlib import Path
import json
import yaml

ROOT = Path(__file__).resolve().parents[1]
YAMLS = list(ROOT.rglob("*.yaml")) + list(ROOT.rglob("*.yml"))
for path in YAMLS:
    with path.open(encoding="utf-8") as f:
        yaml.safe_load(f)
for path in ROOT.rglob("*.json"):
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
print(f"PASS: {len(YAMLS)} YAML, schemas, {len(ids)} modules, {len(api['paths'])} paths")
