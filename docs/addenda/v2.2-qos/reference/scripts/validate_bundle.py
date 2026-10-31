#!/usr/bin/env python3
"""Static checks for QoS-001 addendum; never contacts networks or devices."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
files=list(ROOT.rglob('*'))
errs=[]
for f in files:
    if f.is_file() and f.suffix=='.json':
        try: json.loads(f.read_text('utf-8'))
        except Exception as exc: errs.append(f'Invalid JSON {f}: {exc}')
try:
    import yaml
    for f in ROOT.rglob('*.yaml'):
        try: yaml.safe_load(f.read_text('utf-8'))
        except Exception as exc: errs.append(f'Invalid YAML {f}: {exc}')
except ImportError:
    print('PyYAML missing; YAML syntax validation skipped')
try:
    from jsonschema import Draft202012Validator,FormatChecker
    schema=json.loads((ROOT/'contracts/quality-run.schema.json').read_text('utf-8'))
    Draft202012Validator.check_schema(schema)
    validator=Draft202012Validator(schema,format_checker=FormatChecker())
    for f in sorted((ROOT/'fixtures').glob('*.json')):
        obj=json.loads(f.read_text('utf-8'))
        for e in validator.iter_errors(obj): errs.append(f'Fixture {f.name}: {e.message} (path {list(e.path)})')
        for m in obj['metrics']:
            if m['status'] in ('not_supported','not_available','not_applicable','inconclusive','failed') and m['value'] is not None:
                errs.append(f'{f.name}: non-valid metric {m["id"]} must have null value')
        if obj['mode']=='QUICK' and obj['speedRunIds']:
            errs.append(f'{f.name}: QUICK must not reference speed runs')
except ImportError:
    print('jsonschema missing; fixture schema validation skipped')
required=['README.md','docs/01_DELTA_E_NAO_REGRESSAO.md','docs/02_PRD_PRIORIDADES.md','docs/08_HOMOLOGACAO_E_ACEITE.md','prompts/CLAUDE_CODE_ADENDO.md','contracts/openapi.quality-addon.yaml']
for f in required:
    if not (ROOT/f).is_file(): errs.append(f'Missing required file: {f}')
if errs:
    for e in errs: print('FAIL',e)
    print(f'FAIL: {len(errs)} error(s)'); sys.exit(1)
print(f'PASS: {sum(f.is_file() for f in files)} files; all JSON fixtures and available schemas valid. No network/device actions performed.')
