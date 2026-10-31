#!/usr/bin/env python3
"""Validacao independente de fixtures, schema e metadados do handoff (nao app)."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    raise SystemExit('Instale jsonschema em ambiente de teste para validar as fixtures: pip install jsonschema')
schema=json.loads((root/'04_contracts/quick-inspector.schema.json').read_text())
Draft202012Validator.check_schema(schema)
v=Draft202012Validator(schema,format_checker=FormatChecker())
fixtures=list((root/'05_fixtures').glob('*.json'))
assert len(fixtures)>=7
for f in fixtures:
    d=json.loads(f.read_text())
    errs=list(v.iter_errors(d))
    assert not errs, f'{f.name}: '+', '.join(e.message for e in errs)
    assert d['visual']['type']=='generic' and not d['visual']['leds_homologated']
    if not d['authorization']['can_view_customer']:
        assert d['association']['customer_display_name'] is None
    # A ultima observacao pode ter sido online mesmo se ficar stale.
    # O seletor UI nao pode promover esse valor historico a status corrente.
print(f'OK: schema + {len(fixtures)} fixtures validos')
