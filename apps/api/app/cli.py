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
    sp = sub.add_parser("set-password", help="set a user's password (owner-only); ends all their sessions")
    sp.add_argument("email"); sp.add_argument("--password-env")
    ul = sub.add_parser("unlock-login"); ul.add_argument("key", help="e-mail, or svc:<client_id>, or ip:<addr>")
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
            # same per-account lock as the administrator MFA reset: a membership cannot appear between that route's
            # "only this workspace" check and its DELETE
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('account:' || id::text, 0)) "
                     "FROM users_global WHERE lower(email)=lower(:e)"),
                {"e": a.email},
            )
            c.execute(
                text("INSERT INTO tenant_memberships(tenant_id,user_id,role) "
                     "SELECT :t, id, :r FROM users_global WHERE lower(email)=lower(:e)"),
                {"t": a.tenant_id, "r": a.role, "e": a.email})
        elif a.cmd == "set-password":
            h = hash_secret(_password(a.password_env))
            uid = c.execute(text("SELECT id FROM users_global WHERE lower(email)=lower(:e)"), {"e": a.email}).scalar()
            if uid is None:
                sys.exit("user not found")
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('account:' || CAST(:u AS text), 0))"), {"u": str(uid)}
            )
            c.execute(
                text("UPDATE users_global SET password_hash = :h, tokens_valid_after = clock_timestamp() WHERE id = :u"),
                {"h": h, "u": uid},
            )
            n = c.execute(
                text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"), {"u": uid}
            ).rowcount
            c.execute(
                text("DELETE FROM login_attempts WHERE key = lower(:e) OR key = 'reauth:' || CAST(:u AS text)"),
                {"e": a.email, "u": str(uid)}
            )
            print(f"password updated; {n} session(s) revoked")  # never prints the password
        elif a.cmd == "unlock-login":  # recovery path for a locked account (owner-only)
            n = c.execute(text("DELETE FROM login_attempts WHERE key = :k"), {"k": a.key.lower() if "@" in a.key else a.key}).rowcount
            print(f"cleared {n} attempt(s) for {a.key}")
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
