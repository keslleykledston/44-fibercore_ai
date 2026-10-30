"""RBAC inventory (ADR-0031, delivery 1). No database: it reads the real app. Changing who can do what, or adding a route without deciding its
permission, makes one of these fail — on purpose: update the expectation below in the same change, with the reason."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.permissions import CATALOG
from app.core.rbac_matrix import inventory, render
from app.core.security import ROLE_PERMISSIONS

ROOT = Path(__file__).resolve().parents[3]

# What each role may do TODAY (frozen from the behaviour before the catalog existed; the catalog must not change it).
EXPECTED = {
    "isp_admin": {"customers:read", "customers:import", "associations:review", "incidents:read", "incidents:ack", "jobs:read", "jobs:request",
                  "jobs:approve", "inventory:read", "tenant:read", "audit:read", "members:read", "edge:read", "members:mfa_reset", "diagnostics:run"},
    "engineer": {"customers:read", "associations:review", "incidents:read", "incidents:ack", "jobs:read", "jobs:request", "inventory:read",
                 "tenant:read", "edge:read", "diagnostics:run"},
    "noc_n2": {"customers:read", "incidents:read", "incidents:ack", "jobs:read", "jobs:request", "inventory:read", "tenant:read", "edge:read",
               "diagnostics:run"},
    "noc_n1": {"tenant:read", "inventory:read", "incidents:read"},
    "support": {"tenant:read", "inventory:read", "customers:read"},
    "auditor": {"tenant:read", "audit:read"},
    "platform_support": {"tenant:read"},
    "edge_agent": {"edge:heartbeat", "inventory:write", "jobs:execute"},
}

# Routes that carry NO `require(...)`, each with the reason. A new route that is not here and has no permission fails the test.
PUBLIC = {  # no credentials at all
    ("GET", "/livez"), ("GET", "/readyz"), ("GET", "/version"),
    ("POST", "/v1/auth/token"), ("POST", "/v1/auth/service-token"), ("POST", "/v1/auth/refresh"), ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/mfa/verify"),  # takes the short-lived mfa_token it was handed at login
}
SELF_AUTH = {  # authenticate the caller's OWN account (token read inside the handler); they act on that account only, never on another member
    ("GET", "/v1/auth/workspaces"), ("GET", "/v1/auth/mfa/status"), ("POST", "/v1/auth/mfa/enroll"), ("POST", "/v1/auth/mfa/activate"),
    ("POST", "/v1/auth/mfa/disable"), ("POST", "/v1/auth/mfa/recovery-codes"),
}
SESSION_ONLY = {  # any valid session of the provider; no permission needed (the caller's own identity and platform metadata)
    ("GET", "/v1/auth/me"), ("GET", "/v1/platform/modules"), ("GET", "/v1/platform/versions"),
}


def test_every_role_has_exactly_the_permissions_it_has_today():
    assert {r: set(p) for r, p in ROLE_PERMISSIONS.items()} == EXPECTED


def test_every_permission_a_role_holds_or_a_route_requires_is_in_the_catalog_and_each_catalog_entry_is_used():
    held = set().union(*ROLE_PERMISSIONS.values())
    required = {p for r in inventory() for p in r["permissions"]}
    assert held <= set(CATALOG) and required <= set(CATALOG)
    assert set(CATALOG) <= held | required, f"catalog entries nobody holds or requires: {sorted(set(CATALOG) - held - required)}"
    assert required <= held, f"routes require permissions no role holds: {sorted(required - held)}"


def test_require_rejects_a_permission_outside_the_catalog():
    from app.api.deps import require

    with pytest.raises(RuntimeError):
        require("inventory:reed")  # a typo must stop the app from importing, not silently deny (or allow) everything


def test_every_route_has_a_decided_permission_or_is_on_a_named_list():
    rows = inventory()
    assert len(rows) > 50
    undecided = []
    for r in rows:
        key = (r["method"], r["path"])
        if r["kind"] == "require":
            assert key not in PUBLIC | SELF_AUTH | SESSION_ONLY, f"{key} is listed as unprotected but requires a permission: update the list"
        elif r["kind"] == "principal":
            if key not in SESSION_ONLY:
                undecided.append(key)
        elif key not in PUBLIC | SELF_AUTH:
            undecided.append(key)
    assert not undecided, f"routes with no permission and not on a list (decide, then add with a reason): {undecided}"
    listed = PUBLIC | SELF_AUTH | SESSION_ONLY
    assert listed <= {(r["method"], r["path"]) for r in rows}, "a listed route no longer exists: remove it"


def test_state_changing_and_personal_data_routes_are_never_session_only_or_public():
    for r in inventory():
        key = (r["method"], r["path"])
        if r["kind"] != "require" and key not in PUBLIC | SELF_AUTH | SESSION_ONLY:
            continue
        if key in SESSION_ONLY:
            assert r["method"] == "GET" and not r["path"].startswith(("/v1/customers", "/v1/members", "/v1/jobs"))


def test_the_generated_matrix_in_docs_matches_the_code():
    target = ROOT / "docs" / "security" / "RBAC_MATRIX.md"
    assert target.read_text(encoding="utf-8") == render(), "run: .venv/bin/python scripts/gen_rbac_matrix.py"
