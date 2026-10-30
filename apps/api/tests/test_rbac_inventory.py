"""RBAC inventory (ADR-0031, delivery 1). No database: it reads the real app. Changing who can do what, or adding a route without deciding its
permission, makes one of these fail — on purpose: update the expectation below in the same change, with the reason."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.permissions import CATALOG
from app.core.rbac_matrix import inventory, render, served_operations
from app.core.security import ROLE_PERMISSIONS

ROOT = Path(__file__).resolve().parents[3]

# What each role may do TODAY (frozen from the behaviour before the catalog existed; the catalog must not change it).
EXPECTED = {
    "isp_admin": {"customers:read", "customers:import", "associations:review", "incidents:read", "incidents:ack", "jobs:read", "jobs:request",
                  "jobs:approve", "inventory:read", "tenant:read", "audit:read", "members:read", "edge:read", "members:mfa_reset", "diagnostics:run",
                  "members:manage", "roles:read", "platform:delegate", "devices:act:reboot_cpe", "devices:act:set_wifi_ssid", "bench:authorize"},
    "access_manager": {"tenant:read", "members:read", "members:manage", "roles:read", "audit:read"},
    "engineer": {"customers:read", "associations:review", "incidents:read", "incidents:ack", "jobs:read", "jobs:request", "inventory:read",
                 "tenant:read", "edge:read", "diagnostics:run", "devices:act:reboot_cpe", "devices:act:set_wifi_ssid", "bench:authorize"},
    "noc_n2": {"customers:read", "incidents:read", "incidents:ack", "jobs:read", "jobs:request", "inventory:read", "tenant:read", "edge:read",
               "diagnostics:run", "devices:act:reboot_cpe", "bench:authorize"},
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
    ("GET", "/v1/invites/{token}"), ("POST", "/v1/invites/{token}/accept"),  # the link itself is the credential (SHA-256 looked up, throttled, single use)
}
SELF_AUTH = {  # authenticate the caller's OWN account (token read inside the handler); they act on that account only, never on another member
    ("GET", "/v1/auth/workspaces"), ("GET", "/v1/auth/mfa/status"), ("POST", "/v1/auth/mfa/enroll"), ("POST", "/v1/auth/mfa/activate"),
    ("POST", "/v1/auth/mfa/disable"), ("POST", "/v1/auth/mfa/recovery-codes"), ("POST", "/v1/auth/mfa/step-up"), ("POST", "/v1/auth/password"),
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


def test_the_inventory_is_exactly_what_the_app_serves():
    """Independent check: the inventory (route tree walk) must equal the operations of the app's own OpenAPI schema, both ways."""
    inv = {(r["method"], r["path"]) for r in inventory()}
    served = served_operations()
    assert inv == served, f"only in inventory: {sorted(inv - served)}; only served: {sorted(served - inv)}"


def test_every_route_has_a_decided_permission_or_is_on_a_named_list_whose_mechanism_is_checked():
    kinds = {(r["method"], r["path"]): r["kind"] for r in inventory()}
    assert len(kinds) > 50
    for key, kind in kinds.items():
        if kind == "require":
            assert key not in PUBLIC | SELF_AUTH | SESSION_ONLY, f"{key} requires a permission but is on an unprotected list: update the list"
    # each list is tied to the authentication mechanism it claims: a route that gains or loses protection changes kind and fails here
    assert {k for k, v in kinds.items() if v == "none"} == PUBLIC, "routes with no credential check must be exactly the PUBLIC list"
    assert {k for k, v in kinds.items() if v == "header_auth"} == SELF_AUTH, "own-token routes must be exactly the SELF_AUTH list"
    assert {k for k, v in kinds.items() if v == "principal"} == SESSION_ONLY, "session-only routes must be exactly the SESSION_ONLY list"


def test_own_account_routes_cannot_name_another_account():
    for method, path in SELF_AUTH:
        assert "{" not in path, f"{method} {path}: a path parameter could point at another account"


def test_session_only_routes_are_read_only_platform_and_identity_metadata():
    assert SESSION_ONLY == {("GET", "/v1/auth/me"), ("GET", "/v1/platform/modules"), ("GET", "/v1/platform/versions")}


BODY = {"password": "x", "code": "000000", "refresh_token": "x" * 30, "current_password": "x", "new_password": "y" * 14}   # satisfies every request model of the own-account routes, so only the missing credential can fail


@pytest.mark.parametrize("method,path", sorted(SELF_AUTH | SESSION_ONLY))
def test_routes_without_a_permission_still_refuse_a_missing_or_invalid_credential(client, method, path):
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        r = client.request(method, path, headers=headers, json=BODY if method == "POST" else None)
        assert r.status_code == 401, f"{method} {path} with headers {list(headers)}: {r.status_code}"


def test_the_generated_matrix_in_docs_matches_the_code():
    target = ROOT / "docs" / "security" / "RBAC_MATRIX.md"
    assert target.read_text(encoding="utf-8") == render(), "run: .venv/bin/python scripts/gen_rbac_matrix.py"
