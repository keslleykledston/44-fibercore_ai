"""Provisioning CLI using the OWNER role (ADMIN_DATABASE_URL). Not exposed over HTTP.

Passwords are read from a prompt or env var named by --password-env; never from argv.
"""
from __future__ import annotations

import argparse
import getpass
import json
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
    cs = sub.add_parser("capability-set", help="record what is known about an operation on a vendor/model/firmware profile")
    cs.add_argument("tenant_id"); cs.add_argument("vendor"); cs.add_argument("model"); cs.add_argument("firmware")
    cs.add_argument("protocol", choices=["tr069", "tr369", "olt"]); cs.add_argument("operation")
    cs.add_argument("status", choices=["supported", "unsupported", "unknown"])
    cs.add_argument("certification", choices=["identified", "observed", "certified"])
    cs.add_argument("--evidence", help="reference to the evidence (doc/commit/ticket); REQUIRED for observed/certified")
    cs.add_argument("--verified-at", help="ISO-8601 time the evidence was verified; REQUIRED for observed/certified")
    cs.add_argument("--evidence-file", help="bench operations (ADR-0030): path of the bench evidence file; every field is checked")
    bt = sub.add_parser("bench-target-add", help="ADR-0030: add a CPE to the closed list of bench targets (owner-only)")
    bt.add_argument("tenant_id"); bt.add_argument("cpe_id"); bt.add_argument("edge_id"); bt.add_argument("--note")
    br = sub.add_parser("bench-target-remove", help="ADR-0030: remove a bench target (refused while it has open authorizations or jobs)")
    br.add_argument("tenant_id"); br.add_argument("cpe_id")
    ba = sub.add_parser("bench-authorize", help="ADR-0030: record the PRIOR single-use authorization for one bench maneuver (owner-only)")
    ba.add_argument("tenant_id"); ba.add_argument("operation"); ba.add_argument("cpe_id")
    ba.add_argument("--from", dest="start", required=True, help="ISO-8601 start of the window")
    ba.add_argument("--to", dest="end", required=True, help="ISO-8601 end of the window (at most 4 h after the start)")
    ba.add_argument("--by", required=True, help="who authorizes (the responsible person)")
    ba.add_argument("--ssid", help="set_wifi_ssid only: the exact SSID this authorization covers (BANCADA-<A-Z0-9>)")
    ba.add_argument("--first-run", action="store_true", help="ADR-0030 amendment: stands in for the missing `observed` registry entry (single use)")
    bu = sub.add_parser("bench-unlock", help="ADR-0030: clear the write lock of a bench target after a documented reconciliation")
    bu.add_argument("tenant_id"); bu.add_argument("cpe_id"); bu.add_argument("--reason", required=True)
    fs = sub.add_parser("feature-set", help="turn a per-tenant feature flag on/off (owner-only; overrides the code default)")
    fs.add_argument("tenant_id"); fs.add_argument("feature"); fs.add_argument("state", choices=["on", "off", "default"])
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
        elif a.cmd == "capability-set":
            if (a.certification != "identified" or a.status != "unknown") and not (a.evidence and a.verified_at):
                sys.exit("any claim (supported/unsupported, or observed/certified) requires --evidence and --verified-at")
            from app.api.jobs import OPERATIONS  # the catalog is the job engine's operations: no invented names
            if a.operation not in OPERATIONS:
                sys.exit(f"unknown operation {a.operation!r}; known: {', '.join(sorted(OPERATIONS))}")
            from app.core.capabilities import catalog_for
            valid = {(e.operation, e.protocol) for kind in ("cpe", "olt") for e in catalog_for(kind, OPERATIONS)}
            from app.core import bench as _bench
            valid |= {(n, sp.protocol) for n, sp in _bench.BENCH_OPS.items()}   # the bench catalog names its own (operation, protocol) pairs
            if (a.operation, a.protocol) not in valid:  # a row the API could never show would hide the recorded state
                sys.exit(f"{a.operation!r} is not catalogued over {a.protocol!r}; valid pairs: {sorted(valid)}")
            from app.core import bench
            if a.operation in bench.BENCH_OPS and a.certification != "identified":  # ADR-0030 item 7: the evidence is a checked file
                if not a.evidence_file:
                    sys.exit("a bench operation needs --evidence-file (every ADR-0030 field is checked)")
                try:
                    gaps = bench.evidence_missing(open(a.evidence_file, encoding="utf-8").read())
                except OSError as exc:
                    sys.exit(f"cannot read the evidence file: {exc}")
                if gaps:
                    sys.exit("the evidence file is incomplete: " + "; ".join(gaps))
                if a.certification == "certified":
                    sys.exit("`certified` is not granted by ADR-0030: bench evidence supports `observed` only")
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            if a.operation in bench.BENCH_OPS:  # exclusive against every bench gate evaluation of this operation (see bench.gate)
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": bench.capability_lock_key(a.tenant_id, a.operation)})
            cid = c.execute(
                text("INSERT INTO device_capabilities (tenant_id, vendor, model, firmware, protocol, operation, status, certification, "
                     "verified_at, evidence_ref) VALUES (:t,btrim(:v),btrim(:m),btrim(:f),:p,:o,:s,:c,CAST(:va AS timestamptz),:e) "
                     "ON CONFLICT (tenant_id, lower(vendor), lower(model), firmware, protocol, operation) DO UPDATE SET "
                     "status = EXCLUDED.status, certification = EXCLUDED.certification, verified_at = EXCLUDED.verified_at, "
                     "evidence_ref = EXCLUDED.evidence_ref RETURNING id"),
                {"t": a.tenant_id, "v": a.vendor, "m": a.model, "f": a.firmware, "p": a.protocol, "o": a.operation, "s": a.status,
                 "c": a.certification, "va": a.verified_at, "e": a.evidence},
            ).scalar()
            c.execute(
                text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
                     "VALUES (:t,'capability',:i,'device.capabilities.changed','1',CAST(:p AS jsonb))"),
                {"t": a.tenant_id, "i": cid, "p": json.dumps({
                    "vendor": a.vendor, "model": a.model, "firmware": a.firmware, "protocol": a.protocol, "operation": a.operation,
                    "status": a.status, "certification": a.certification})},
            )
            print(f"capability {a.operation}/{a.protocol} on {a.vendor} {a.model} {a.firmware}: {a.status}/{a.certification}")
        elif a.cmd == "bench-target-add":
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            cpe = c.execute(text("SELECT edge_id FROM cpes WHERE id = :c"), {"c": a.cpe_id}).first()
            if cpe is None or str(cpe.edge_id) != a.edge_id:  # the target's Edge is the CPE's owner Edge; no other pairing
                sys.exit("cpe not found for this tenant, or it is owned by another edge")
            # the generation never goes back: a target that was removed and is added again gets a HIGHER owner_epoch, so an envelope issued
            # for an older generation can never match again (ADR-0029 fencing)
            last = c.execute(text("SELECT last_epoch FROM bench_target_epochs WHERE cpe_id = :c"), {"c": a.cpe_id}).scalar() or 0
            c.execute(text("INSERT INTO bench_targets (tenant_id, cpe_id, edge_id, note, owner_epoch) VALUES (:t,:c,:e,:n,:ep)"),
                      {"t": a.tenant_id, "c": a.cpe_id, "e": a.edge_id, "n": a.note, "ep": last + 1})
            print(f"bench target added: cpe {a.cpe_id} (edge {a.edge_id}), owner_epoch {last + 1}")
        elif a.cmd == "bench-target-remove":
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            busy = c.execute(
                text("SELECT (SELECT count(*) FROM bench_authorizations WHERE cpe_id = :c AND state = 'open' AND window_end > now()), "
                     "(SELECT count(*) FROM jobs WHERE target_id = :c AND status IN "
                     "('PENDING_APPROVAL','APPROVED','DISPATCHED','ACCEPTED','DEVICE_PENDING','VERIFYING'))"),
                {"c": a.cpe_id}).one()
            if busy[0] or busy[1]:
                sys.exit("refused: the target has open authorizations or jobs in flight")
            c.execute(text("DELETE FROM bench_authorizations WHERE cpe_id = :c AND state = 'open'"), {"c": a.cpe_id})
            c.execute(text("INSERT INTO bench_target_epochs (tenant_id, cpe_id, last_epoch) "
                           "SELECT tenant_id, cpe_id, owner_epoch FROM bench_targets WHERE cpe_id = :c "
                           "ON CONFLICT (tenant_id, cpe_id) DO UPDATE SET "
                           "last_epoch = GREATEST(bench_target_epochs.last_epoch, EXCLUDED.last_epoch)"),
                      {"c": a.cpe_id})
            c.execute(text("DELETE FROM bench_targets WHERE cpe_id = :c"), {"c": a.cpe_id})
            print("bench target removed")
        elif a.cmd == "bench-authorize":
            from datetime import datetime

            from app.core import bench
            if a.operation not in bench.BENCH_OPS:
                sys.exit(f"{a.operation!r} is not in the bench catalog: {sorted(bench.BENCH_OPS)}")
            if not bench.EDGE_SUPPORT:
                sys.exit("refused: no bench authorization can be recorded until the Edge-side bench gate exists and is tested (ADR-0030)")
            params = {"ssid": a.ssid} if a.ssid is not None else {}
            if not bench.params_valid(a.operation, params):
                sys.exit(f"parameters outside the bench catalog for {a.operation!r} (set_wifi_ssid needs --ssid BANCADA-...; others take none)")
            start, end = datetime.fromisoformat(a.start), datetime.fromisoformat(a.end)
            if start.tzinfo is None or end.tzinfo is None:
                sys.exit("--from/--to need a time zone (e.g. 2026-10-30T14:00:00+00:00)")
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            if a.first_run:  # ADR-0030 amendment: only while the evidence-backed entry does not exist yet, and only with the entry it needs
                cpe = bench.profile_for(c, a.tenant_id, a.cpe_id, bench.BENCH_OPS[a.operation].protocol)
                if cpe is None or not (cpe.vendor and cpe.model and cpe.firmware):
                    sys.exit("refused: the registry profile (vendor, model, firmware) is not known for this target")
                have = {r.certification for r in c.execute(
                    text("SELECT certification FROM device_capabilities WHERE tenant_id = :t AND lower(vendor) = lower(:v) "
                         "AND lower(model) = lower(:m) AND firmware = :f AND protocol = :p AND operation = :o AND status = 'supported' "
                         "AND evidence_ref IS NOT NULL AND verified_at IS NOT NULL"),
                    {"t": a.tenant_id, "v": cpe.vendor.strip(), "m": cpe.model.strip(), "f": cpe.firmware.strip(),
                     "p": bench.BENCH_OPS[a.operation].protocol, "o": a.operation})}
                if have & {"observed", "certified"}:
                    sys.exit("refused: an observed entry already exists for this profile; record a normal authorization (no --first-run)")
                if "identified" not in have:
                    sys.exit("refused: --first-run needs a complete `supported`/`identified` registry entry of the exact profile first")
            aid = c.execute(
                text("INSERT INTO bench_authorizations "
                     "(tenant_id, operation, cpe_id, params_hash, window_start, window_end, authorized_by, first_run) "
                     "VALUES (:t,:o,:c,:h,:s,:e,:by,:fr) RETURNING id"),
                {"t": a.tenant_id, "o": a.operation, "c": a.cpe_id, "h": bench.params_hash(params), "s": start, "e": end, "by": a.by,
                 "fr": a.first_run}).scalar()
            print(f"authorization {aid}: {a.operation} on {a.cpe_id}, {start.isoformat()} .. {end.isoformat()}, single use"
                  + (", FIRST RUN (valid only while no `observed` entry exists)" if a.first_run else ""))
        elif a.cmd == "bench-unlock":
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            n = c.execute(
                text("UPDATE bench_targets SET write_locked = false, lock_reason = NULL WHERE cpe_id = :c AND write_locked RETURNING id"),
                {"c": a.cpe_id}).first()
            if n is None:
                sys.exit("the target is not locked, or is not a bench target")
            c.execute(text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
                           "VALUES (:t,'bench_target',:i,'bench.unlocked','1',CAST(:p AS jsonb))"),
                      {"t": a.tenant_id, "i": n.id, "p": json.dumps({"reason": a.reason[:300]})})
            print("write lock cleared")
        elif a.cmd == "feature-set":
            from app.core.features import FEATURES
            if a.feature not in FEATURES:
                sys.exit(f"unknown feature {a.feature!r}; known: {', '.join(sorted(FEATURES))}")
            if a.feature == "bench_writes" and a.state == "on":
                from app.core import bench
                if not bench.EDGE_SUPPORT:
                    sys.exit("refused: bench_writes cannot be turned on until the Edge-side bench gate exists and is tested (ADR-0030)")
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            if a.state == "default":
                c.execute(text("DELETE FROM tenant_features WHERE tenant_id = :t AND feature = :f"), {"t": a.tenant_id, "f": a.feature})
            else:
                c.execute(
                    text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,:e) "
                         "ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now()"),
                    {"t": a.tenant_id, "f": a.feature, "e": a.state == "on"},
                )
            c.execute(
                text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
                     "VALUES (:t,'tenant',:t,'tenant.feature.changed','1',CAST(:p AS jsonb))"),
                {"t": a.tenant_id, "p": json.dumps({"feature": a.feature, "state": a.state})},
            )
            print(f"feature {a.feature}: {a.state}")
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
