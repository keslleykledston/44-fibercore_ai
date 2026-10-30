"""Escreve docs/security/RBAC_MATRIX.md a partir do código (ADR-0031). Uso: .venv/bin/python scripts/gen_rbac_matrix.py [--check]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.core.rbac_matrix import render  # noqa: E402

target = ROOT / "docs" / "security" / "RBAC_MATRIX.md"
if "--check" in sys.argv:
    sys.exit(0 if target.exists() and target.read_text(encoding="utf-8") == render() else 1)
target.write_text(render(), encoding="utf-8")
print(f"escrito {target.relative_to(ROOT)}")
