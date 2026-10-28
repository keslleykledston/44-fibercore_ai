"""Provisioning CLI using the OWNER role (ADMIN_DATABASE_URL). Not exposed over HTTP.

Passwords are read from a prompt or env var named by --password-env; never from argv.
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys

from sqlalchemy import text

from app.core.db import make_engine
from app.core.security import hash_secret

ROLES = ["isp_admin", "engineer", "noc_n2", "noc_n1", "support", "auditor", "platform_support", "edge_agent"]


def _engine():
    dsn = os.environ.get("ADMIN_DATABASE_URL")
    if not dsn:
        sys.exit("ADMIN_DATABASE_URL required")
    return make_engine(dsn)


def _password(env_name: str | None) -> str:
    pw = os.environ.get(env_name, "") if env_name else getpass.getpass("Password: ")
    if len(pw) < 12:
        sys.exit("password must have >= 12 characters")
    return pw


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fibercore-admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("create-tenant"); t.add_argument("name")
    u = sub.add_parser("create-user")
    u.add_argument("email"); u.add_argument("display_name"); u.add_argument("--password-env")
    m = sub.add_parser("add-member")
    m.add_argument("tenant_id"); m.add_argument("email"); m.add_argument("role", choices=ROLES)
    s = sub.add_parser("create-service-account")
    s.add_argument("tenant_id"); s.add_argument("name"); s.add_argument("role", choices=ROLES); s.add_argument("--edge-id")
    e = sub.add_parser("register-edge"); e.add_argument("tenant_id"); e.add_argument("name"); e.add_argument("--site")
    a = ap.parse_args(argv)
    eng = _engine()
    with eng.begin() as c:
        if a.cmd == "create-tenant":
            print(c.execute(text("INSERT INTO tenants(name) VALUES (:n) RETURNING id"), {"n": a.name}).scalar())
        elif a.cmd == "create-user":
            h = hash_secret(_password(a.password_env))
            print(c.execute(
                text("INSERT INTO users_global(email, display_name, password_hash) VALUES (:e,:d,:h) RETURNING id"),
                {"e": a.email.lower(), "d": a.display_name, "h": h}).scalar())
        elif a.cmd == "add-member":
            c.execute(
                text("INSERT INTO tenant_memberships(tenant_id,user_id,role) "
                     "SELECT :t, id, :r FROM users_global WHERE lower(email)=lower(:e)"),
                {"t": a.tenant_id, "r": a.role, "e": a.email})
        elif a.cmd == "register-edge":
            print(c.execute(text("INSERT INTO edges(tenant_id,name,site_name) VALUES (:t,:n,:s) RETURNING id"),
                            {"t": a.tenant_id, "n": a.name, "s": a.site}).scalar())
        elif a.cmd == "create-service-account":
            secret = secrets.token_urlsafe(32)
            sid = c.execute(
                text("INSERT INTO service_accounts(tenant_id,name,role,secret_hash,edge_id) VALUES (:t,:n,:r,:h,:e) RETURNING id"),
                {"t": a.tenant_id, "n": a.name, "r": a.role, "h": hash_secret(secret), "e": a.edge_id}).scalar()
            print(f"client_id={sid}\nclient_secret={secret}  # shown once; store in secret manager")


if __name__ == "__main__":
    main()
