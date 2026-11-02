"""Validate the offline artifact. Does not connect to devices or certify firmware."""
from pathlib import Path
import json, zipfile, sys
import yaml
from jsonschema import Draft202012Validator
ROOT = Path(__file__).resolve().parents[1]
expected = [
 'README_START_HERE.md','prompts/01_CLAUDE_CODE_MASTER.md',
 'prompts/02_CODEX_REVIEW.md','prompts/03_LOVABLE_UX.md',
 'contracts/olt-provisioning-v2.5.openapi.yaml',
 'contracts/expert-profile-v2.5.1.openapi.yaml',
 'contracts/service-intent.schema.json',
 'contracts/expert-profile-draft.schema.json',
 'docs/product/PRD_INTEGRADO_v2_5.md',
 'docs/ux/SCREENS_AND_FLOWS.md',
 'starter/profile_matcher.py',
]
for f in expected:
    assert (ROOT/f).is_file(), f
schemas = {}
for name in ['service-intent.schema.json','expert-profile-draft.schema.json']:
    sch=json.loads((ROOT/'contracts'/name).read_text())
    Draft202012Validator.check_schema(sch)
    schemas[name]=sch
examples = [
 ('service-intent.schema.json',ROOT/'profiles/example-intent.yaml'),
 ('expert-profile-draft.schema.json',ROOT/'examples/expert-draft-huawei-lab.synthetic.json'),
]
for s,path in examples:
    obj=yaml.safe_load(path.read_text()) if path.suffix=='.yaml' else json.loads(path.read_text())
    Draft202012Validator(schemas[s]).validate(obj)
route_total=0
for name in ['olt-provisioning-v2.5.openapi.yaml','expert-profile-v2.5.1.openapi.yaml']:
    api=yaml.safe_load((ROOT/'contracts'/name).read_text())
    assert api['openapi'].startswith('3.1.')
    assert api['servers'][0]['url']=='/api/v1'
    def check_ref(node):
        if isinstance(node,dict):
            if '$ref' in node:
                r=node['$ref']; assert r.startswith('#/'),(name,r)
                dest=api
                for k in r[2:].split('/'):
                    dest=dest[k.replace('~1','/').replace('~0','~')]
            for v in node.values():check_ref(v)
        elif isinstance(node,list):
            for v in node:check_ref(v)
    check_ref(api)
    route_total+=len(api['paths'])
assert route_total==15,route_total
assert not any(p.suffix in ('.pyc','.pyo') for p in ROOT.rglob('*') if p.is_file())
print(f'OK: {len(expected)} key files; 2 JSON Schemas + 2 validated fixtures; {route_total} routes; no compiled Python files')
