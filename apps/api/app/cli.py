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

ROLES = ["isp_admin", "access_manager", "engineer", "noc_n2", "noc_n1", "support", "auditor", "edge_agent"]


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
    po = sub.add_parser("platform-operator", help="ADR-0031: mark/unmark an account as a platform operator (the only accounts a workspace can delegate access to)")
    po.add_argument("--email", required=True)
    po.add_argument("--off", action="store_true", help="remove the mark (the account's active delegations stop working at once)")
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
    ls = sub.add_parser("onu-cpe-link-suggest", help="ADR-0030 item 2(a): record a SUGGESTED ONU<->CPE link backed by an H1 evidence file; never confirms (a person reviews it)")
    ls.add_argument("tenant_id"); ls.add_argument("onu_id"); ls.add_argument("cpe_id")
    ls.add_argument("--evidence-ref", required=True, help="repo path of the H1 evidence, docs/wiki/bench/H1-*.md (read from the evidence root, FIBERCORE_EVIDENCE_ROOT, default /bench)")
    ls.add_argument("--by", required=True, help="who records it (the owner)")
    br = sub.add_parser("bench-target-remove", help="ADR-0030: remove a bench target (refused while it has open authorizations or jobs)")
    br.add_argument("tenant_id"); br.add_argument("cpe_id")
    ba = sub.add_parser("bench-authorize", help="ADR-0030: record the PRIOR single-use authorization for one bench maneuver (owner-only)")
    ba.add_argument("tenant_id"); ba.add_argument("operation"); ba.add_argument("cpe_id")
    ba.add_argument("--from", dest="start", required=True, help="ISO-8601 start of the window")
    ba.add_argument("--to", dest="end", required=True, help="ISO-8601 end of the window (at most 4 h after the start)")
    ba.add_argument("--by", required=True, help="who authorizes (the responsible person)")
    ba.add_argument("--ssid", help="set_wifi_ssid only: the exact SSID this authorization covers (BANCADA-<A-Z0-9>)")
    ba.add_argument("--speed-target", help="speed_test_* only: the logical endpoint id this authorization covers (no URL, no address)")
    ba.add_argument("--speed-profile", help="speed_test_* only: the file-size profile this authorization covers (10mb, 50mb, 200mb)")
    ba.add_argument("--ping-target", help="ping_test only: the logical destination id this authorization covers (no address)")
    ba.add_argument("--first-run", action="store_true", help="ADR-0030 amendment: stands in for the missing `observed` registry entry (single use)")
    bu = sub.add_parser("bench-unlock", help="ADR-0030: clear the write lock of a bench target after a documented reconciliation")
    bu.add_argument("tenant_id"); bu.add_argument("cpe_id"); bu.add_argument("--reason", required=True)
    ots = sub.add_parser("olt-transfer-start", help="ADR-0029: phase 1 of moving an OLT to another Edge: no lease, no dispatch, open queries cancelled (owner-only)")
    ots.add_argument("tenant_id"); ots.add_argument("olt_id"); ots.add_argument("to_edge_id")
    otf = sub.add_parser("olt-transfer-finish", help="ADR-0029: phase 2: the new Edge becomes the owner (epoch + 1) once the old Edge's last lease has run out")
    otf.add_argument("tenant_id"); otf.add_argument("olt_id")
    fs = sub.add_parser("feature-set", help="turn a per-tenant feature flag on/off (owner-only; overrides the code default)")
    fs.add_argument("tenant_id"); fs.add_argument("feature"); fs.add_argument("state", choices=["on", "off", "default"])
    oc = sub.add_parser("ont-config-mock", help="ADR-0034: write a SYNTHETIC configuration profile for a CPE (source 'mock', labelled synthetic; lab/demo only; owner-only)")
    oc.add_argument("tenant_id"); oc.add_argument("cpe_id"); oc.add_argument("profile", help="dualband | multi_ssid | no_wifi | inactive_5g | clear")
    ob = sub.add_parser("olt-board-mock", help="SYNTHETIC board inventory (`olt.board`, source 'mock') for a DEMO OLT so the front-panel screen can be shown without equipment (demo/e2e only: refuses any tenant that is not the demonstration tenant and any OLT that already has an inventory read from the equipment; owner-only)")
    ob.add_argument("tenant_id"); ob.add_argument("olt_name"); ob.add_argument("--slots", default="0:H805GPFD,1:H805GPFD", help="service boards as slot:MODEL,... (the control and power boards are added)")
    se = sub.add_parser("speed-endpoint-set", help="ADR-0038: create/update a LOGICAL speed-test endpoint (id, label, CORE|INTERNET, region, enabled). No URL: the Edge holds the address (owner-only)")
    se.add_argument("tenant_id"); se.add_argument("endpoint_id"); se.add_argument("label")
    se.add_argument("kind", choices=["CORE", "INTERNET"]); se.add_argument("region"); se.add_argument("state", choices=["on", "off"])
    se.add_argument("--edge", required=True, help="the Edge that owns this test node (only it can report its health, and only a bench CPE of that Edge can use it)")
    pt = sub.add_parser("probe-target-set", help="ADR-0039: create/update a LOGICAL ping destination (id, label, CORE|INTERNET, region, enabled). No address: the Edge holds it (owner-only)")
    pt.add_argument("tenant_id"); pt.add_argument("target_id"); pt.add_argument("label")
    pt.add_argument("kind", choices=["CORE", "INTERNET"]); pt.add_argument("region"); pt.add_argument("state", choices=["on", "off"])
    pt.add_argument("--edge", required=True, help="the Edge that owns this destination (it holds the address in its local configuration; only a bench CPE of that Edge can use it)")
    sas = sub.add_parser("speed-acceptance-set", help="ADR-0038 amendment (option C): record the formal acceptance of the 3xx risk for ONE vendor/model/firmware and CORE destinations (owner-only)")
    sas.add_argument("tenant_id"); sas.add_argument("vendor"); sas.add_argument("model"); sas.add_argument("firmware")
    sas.add_argument("--endpoints", required=True, help="comma-separated LOGICAL endpoint ids (CORE only)")
    sas.add_argument("--approved-by", required=True); sas.add_argument("--accepted-on", required=True, help="YYYY-MM-DD")
    sas.add_argument("--expires-on", required=True, help="YYYY-MM-DD, at most 90 days after --accepted-on")
    sas.add_argument("--doc", required=True, help="path of docs/wiki/bench/ACEITE-risco-3xx-<model>-<date>.md as mounted in this container")
    sar = sub.add_parser("speed-acceptance-revoke", help="ADR-0038 amendment: revoke an acceptance (takes effect for every job not yet dispatched)")
    sar.add_argument("tenant_id"); sar.add_argument("acceptance_id")
    saa = sub.add_parser("speed-acceptance-audit", help="recompute each acceptance document hash against the mounted docs directory; exit 1 on a mismatch or missing file of an ACTIVE acceptance")
    saa.add_argument("tenant_id"); saa.add_argument("--docs-dir", required=True)
    sp = sub.add_parser("set-password", help="set a user's password (owner-only); ends all their sessions")
    sp.add_argument("email"); sp.add_argument("--password-env")
    ul = sub.add_parser("unlock-login"); ul.add_argument("key", help="e-mail, or svc:<client_id>, or ip:<addr>")
    da = sub.add_parser("deactivate-account", help="owner-only: deactivate service accounts by exact name and/or end users' membership of one tenant; refuses Edge agents and isp_admin users")
    da.add_argument("tenant_id"); da.add_argument("--service-account", action="append", default=[]); da.add_argument("--user", action="append", default=[], help="e-mail")
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
        elif a.cmd == "platform-operator":
            n = c.execute(text("UPDATE users_global SET is_platform_operator = :v, tokens_valid_after = clock_timestamp() "
                               "WHERE lower(email) = lower(:e) RETURNING 1"), {"v": not a.off, "e": a.email}).rowcount
            if n != 1:
                sys.exit("no such account")
            print("platform operator " + ("removed" if a.off else "set"))
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
            from app.core import speed as _speed0
            registry_only = {o for o, _ in _speed0.REGISTRY_ONLY} | {"olt_profile_read"}   # registry rows that are an observation, not a job operation
            if a.operation not in OPERATIONS and a.operation not in registry_only:
                sys.exit(f"unknown operation {a.operation!r}; known: {', '.join(sorted(OPERATIONS))}")
            from app.core.capabilities import catalog_for
            valid = {(e.operation, e.protocol) for kind in ("cpe", "olt") for e in catalog_for(kind, OPERATIONS)}
            from app.core import bench as _bench
            valid |= {(n, sp.protocol) for n, sp in _bench.BENCH_OPS.items()}   # the bench catalog names its own (operation, protocol) pairs
            from app.core import speed as _speed
            valid |= set(_speed.REGISTRY_ONLY)
            from app.core import profile_studio as _ps
            valid.add(_ps.PROFILE_READ)   # ADR-0040: a driver can READ the profiles of this OLT firmware (an observation, not a job operation)
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
        elif a.cmd == "onu-cpe-link-suggest":
            import hashlib as _hl
            import os as _os
            import re as _re
            if not _re.fullmatch(r"docs/wiki/bench/H1-[A-Za-z0-9._-]{3,100}\.md", a.evidence_ref):
                sys.exit("evidence_ref must be a docs/wiki/bench/H1-*.md path")
            # the file read IS the referenced one: <evidence root>/<its name>, resolved, inside the root and not a symlink
            root = _os.path.realpath(_os.environ.get("FIBERCORE_EVIDENCE_ROOT", "/bench"))
            target = _os.path.join(root, _os.path.basename(a.evidence_ref))
            if _os.path.islink(target) or _os.path.realpath(target) != target or _os.path.dirname(target) != root:
                sys.exit("the referenced evidence must be a regular file directly under the evidence root")
            import stat as _st
            try:
                fd = _os.open(target, _os.O_RDONLY | _os.O_NOFOLLOW | _os.O_NONBLOCK)   # never blocks on a FIFO, never follows a symlink
                try:
                    if not _st.S_ISREG(_os.fstat(fd).st_mode):
                        sys.exit("the referenced evidence must be a regular file directly under the evidence root")
                    chunks, got = [], 0
                    while got <= 256 << 10:   # read to EOF (a read may return less than asked), at most 256 KiB + 1 byte
                        chunk = _os.read(fd, (256 << 10) + 1 - got)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        got += len(chunk)
                    raw_bytes = b"".join(chunks)
                finally:
                    _os.close(fd)
                if len(raw_bytes) > 256 << 10:
                    sys.exit("the evidence file is larger than 256 KiB")
                body = raw_bytes.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                sys.exit(f"cannot read the evidence file: {exc}")
            import ipaddress as _ip
            def _has_address(text_: str) -> bool:
                for tok in _re.findall(r"\[([0-9A-Fa-f:.]+)\]", text_) + _re.findall(r"[0-9A-Fa-f:.]{3,}", text_):   # "[v6]:port" is checked without the port
                    if ":" in tok or "." in tok:
                        try:
                            _ip.ip_address(tok.rstrip(".:"))
                            return True
                        except ValueError:
                            continue
                return False
            labels = r"(?i)(senha|password|secret|token|credencial|api[_-]?key|chave)\s*[:=]"
            if len(body.strip()) < 200 or _re.search(labels, body) or _re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", body) or _has_address(body):
                sys.exit("the evidence file is empty or carries an address or credential")
            by = a.by.strip()[:120]
            if not by:
                sys.exit("--by is required")
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            if (c.execute(text("SELECT 1 FROM onus WHERE id = :o AND tenant_id = :t"), {"o": a.onu_id, "t": a.tenant_id}).first() is None  # the owner role bypasses RLS: name the tenant
                    or c.execute(text("SELECT 1 FROM cpes WHERE id = :c AND tenant_id = :t"), {"c": a.cpe_id, "t": a.tenant_id}).first() is None):
                sys.exit("onu or cpe not found for this tenant")
            ev = {"rule": "owner_physical_evidence", "ambiguous": False, "evidence_ref": a.evidence_ref, "evidence_sha256": _hl.sha256(raw_bytes).hexdigest(), "recorded_by": by,
                  "note": "recorded by the owner with physical evidence; a person still confirms it"}
            done = c.execute(text("INSERT INTO onu_cpe_links (tenant_id, onu_id, cpe_id, confidence, evidence) VALUES (:t,:o,:c,0.60,CAST(:e AS jsonb)) "
                                  "ON CONFLICT DO NOTHING RETURNING id"), {"t": a.tenant_id, "o": a.onu_id, "c": a.cpe_id, "e": json.dumps(ev)}).first()
            if done is None:
                print("a link for this ONU and CPE already exists; nothing changed")
            else:
                c.execute(text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
                               "VALUES (:t,'onu_cpe_link',:i,'onu_cpe_link.suggested','1',CAST(:p AS jsonb))"),
                          {"t": a.tenant_id, "i": done.id, "p": json.dumps({"onu_id": a.onu_id, "cpe_id": a.cpe_id, "rule": "owner_physical_evidence"})})
                print(f"suggested link {done.id} (owner_physical_evidence); a person must confirm it")
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
            if a.operation in bench.SPEED_OPS:
                if not bench.SPEED_EDGE_SUPPORT:
                    sys.exit("refused: the Edge half of the speed test is not delivered yet (ADR-0038)")
                params = {"target": a.speed_target, "profile": a.speed_profile}
            if a.operation in bench.PING_OPS:
                if not bench.PING_EDGE_SUPPORT:
                    sys.exit("refused: the Edge half of the ping test is not delivered yet (ADR-0039)")
                params = {"target": a.ping_target}
            if not bench.params_valid(a.operation, params):
                sys.exit(f"parameters outside the bench catalog for {a.operation!r} (set_wifi_ssid needs --ssid BANCADA-...; speed_test_* needs --speed-target "
                     "and --speed-profile; ping_test needs --ping-target; others take none)")
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
        elif a.cmd == "speed-endpoint-set":
            from app.core import speed
            if speed.ENDPOINT_ID_RE.fullmatch(a.endpoint_id) is None:
                sys.exit("endpoint id: lowercase letters, digits and '-', 2..31 characters; it is a name, never an address or URL")
            if not 1 <= len(a.label) <= 60 or "://" in a.label or "/" in a.label:
                sys.exit("label: 1..60 characters, a name (no URL, no address)")
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            if c.execute(text("SELECT 1 FROM edges WHERE id = :e AND tenant_id = :t"), {"e": a.edge, "t": a.tenant_id}).first() is None:
                sys.exit("unknown edge for this tenant")
            c.execute(text("INSERT INTO speed_endpoints (tenant_id, id, label, target_kind, region, enabled, edge_id) VALUES (:t,:i,:l,:k,:r,:e,:g) "
                           "ON CONFLICT (tenant_id, id) DO UPDATE SET label = EXCLUDED.label, target_kind = EXCLUDED.target_kind, "
                           "region = EXCLUDED.region, enabled = EXCLUDED.enabled, edge_id = EXCLUDED.edge_id, "
                           "health = CASE WHEN speed_endpoints.edge_id IS DISTINCT FROM EXCLUDED.edge_id THEN 'unknown' ELSE speed_endpoints.health END"),
                      {"t": a.tenant_id, "i": a.endpoint_id, "l": a.label, "k": a.kind, "r": a.region, "e": a.state == "on", "g": a.edge})
            print(f"speed endpoint {a.endpoint_id}: {a.kind}, {'enabled' if a.state == 'on' else 'disabled'} (health is reported by the Edge)")
        elif a.cmd == "probe-target-set":
            from app.core import probe
            if probe.TARGET_ID_RE.fullmatch(a.target_id) is None:
                sys.exit("target id: lowercase letters, digits and '-', 2..31 characters; it is a name, never an address")
            if not 1 <= len(a.label) <= 60 or "://" in a.label or "/" in a.label:
                sys.exit("label: 1..60 characters, a name (no URL, no address)")
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            if c.execute(text("SELECT 1 FROM edges WHERE id = :e AND tenant_id = :t"), {"e": a.edge, "t": a.tenant_id}).first() is None:
                sys.exit("unknown edge for this tenant")
            c.execute(text("INSERT INTO probe_targets (tenant_id, id, label, target_kind, region, enabled, edge_id) VALUES (:t,:i,:l,:k,:r,:e,:g) "
                           "ON CONFLICT (tenant_id, id) DO UPDATE SET label = EXCLUDED.label, target_kind = EXCLUDED.target_kind, "
                           "region = EXCLUDED.region, enabled = EXCLUDED.enabled, edge_id = EXCLUDED.edge_id"),
                      {"t": a.tenant_id, "i": a.target_id, "l": a.label, "k": a.kind, "r": a.region, "e": a.state == "on", "g": a.edge})
            print(f"ping target {a.target_id}: {a.kind}, {'enabled' if a.state == 'on' else 'disabled'} (the Edge must list the same id with its own address)")
        elif a.cmd == "speed-acceptance-set":
            import hashlib
            from datetime import UTC, date, datetime, timedelta

            from app.core import bench, speed
            eps = [x for x in (e.strip() for e in a.endpoints.split(",")) if x]
            if not eps or any(speed.ENDPOINT_ID_RE.fullmatch(e) is None for e in eps):
                sys.exit("--endpoints: logical ids only (a name, never an address or URL)")
            try:
                acc_on, exp_on = date.fromisoformat(a.accepted_on), date.fromisoformat(a.expires_on)
            except ValueError:
                sys.exit("dates must be YYYY-MM-DD")
            if not acc_on < exp_on <= acc_on + timedelta(days=speed.ACCEPTANCE_MAX_DAYS):
                sys.exit(f"the acceptance lasts at most {speed.ACCEPTANCE_MAX_DAYS} days")
            if acc_on > datetime.now(UTC).date():
                sys.exit("the acceptance date cannot be in the future: record it on the day it is given")
            try:
                raw = open(a.doc, "rb").read()
            except OSError as exc:
                sys.exit(f"cannot read the acceptance document: {exc}")
            base = os.path.basename(a.doc)
            gaps = speed.acceptance_doc_gaps(base, raw.decode("utf-8", "replace"), vendor=a.vendor, model=a.model, firmware=a.firmware,
                                             approved_by=a.approved_by, accepted_on=a.accepted_on, endpoint_ids=eps)
            if gaps:
                sys.exit("the acceptance document is incomplete: " + "; ".join(gaps))
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            for op in sorted(speed.OPERATION_DIRECTION):   # exclusive against every gate evaluation of the two speed operations
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": bench.capability_lock_key(a.tenant_id, op)})
            core = {r.id for r in c.execute(text("SELECT id FROM speed_endpoints WHERE target_kind = 'CORE'"))}
            if any(e not in core for e in eps):
                sys.exit("every destination must be an existing CORE endpoint (INTERNET nodes are not ours: never accepted)")
            probe = c.execute(text("SELECT 1 FROM device_capabilities WHERE lower(vendor) = lower(:v) AND lower(model) = lower(:m) AND firmware = :f AND protocol = 'tr069' "
                                   "AND operation = :o AND status = 'unsupported' AND certification IN ('observed','certified') AND evidence_ref IS NOT NULL AND verified_at IS NOT NULL"),
                              {"v": a.vendor.strip(), "m": a.model.strip(), "f": a.firmware.strip(), "o": speed.REDIRECT_PROBE}).first()
            if probe is None:
                sys.exit("the 3xx probe must be recorded first for this exact vendor/model/firmware (speed_test_redirect_probe, unsupported, observed, with evidence)")
            aid = c.execute(text("INSERT INTO speed_risk_acceptances (tenant_id, vendor, model, firmware, endpoint_ids, approved_by, accepted_on, expires_on, doc_ref, doc_sha256) "
                                 "VALUES (:t, btrim(:v), btrim(:m), btrim(:f), :e, btrim(:b), :a, :x, :r, :h) RETURNING id"),
                            {"t": a.tenant_id, "v": a.vendor, "m": a.model, "f": a.firmware, "e": eps, "b": a.approved_by, "a": acc_on, "x": exp_on,
                             "r": "docs/wiki/bench/" + base, "h": hashlib.sha256(raw).hexdigest()}).scalar()
            print(f"speed risk acceptance {aid}: {a.vendor} {a.model} {a.firmware}, destinations {','.join(eps)}, until {exp_on} (doc sha256 {hashlib.sha256(raw).hexdigest()[:12]}…)")
        elif a.cmd == "speed-acceptance-revoke":
            from app.core import bench, speed
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            for op in sorted(speed.OPERATION_DIRECTION):
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": bench.capability_lock_key(a.tenant_id, op)})
            n = c.execute(text("UPDATE speed_risk_acceptances SET revoked_at = now() WHERE id = :i AND revoked_at IS NULL"), {"i": a.acceptance_id}).rowcount
            if not n:
                sys.exit("no active acceptance with this id for this tenant")
            print("acceptance revoked: no job that has not been dispatched yet can use it")
        elif a.cmd == "speed-acceptance-audit":
            import hashlib
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            bad = 0
            for r in c.execute(text("SELECT id, doc_ref, doc_sha256, revoked_at, expires_on >= (now() AT TIME ZONE 'UTC')::date AS live FROM speed_risk_acceptances ORDER BY created_at")):
                active = r.revoked_at is None and r.live
                try:
                    got = hashlib.sha256(open(os.path.join(a.docs_dir, os.path.basename(r.doc_ref)), "rb").read()).hexdigest()
                    state = "OK" if got == r.doc_sha256 else "MISMATCH"
                except OSError:
                    state = "MISSING"
                bad += state != "OK" and active
                print(f"{r.id} {'active' if active else 'inactive'} {state}")
            sys.exit(1 if bad else 0)
        elif a.cmd == "olt-transfer-start":
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            o = c.execute(text("SELECT edge_id, transfer_to FROM olts WHERE id = :o FOR UPDATE"), {"o": a.olt_id}).first()
            if o is None:
                sys.exit("olt not found for this tenant")
            if o.transfer_to is not None:
                sys.exit("a transfer of this olt is already in progress")
            if str(o.edge_id) == a.to_edge_id:
                sys.exit("the olt already belongs to that edge")
            if c.execute(text("SELECT 1 FROM edges WHERE id = :e"), {"e": a.to_edge_id}).first() is None:
                sys.exit("edge not found for this tenant")
            # one transaction: from here no lease is issued and nothing is dispatched for this OLT, and every query not yet concluded ends
            c.execute(text("UPDATE olts SET transfer_to = :e, transfer_started_at = now() WHERE id = :o"), {"e": a.to_edge_id, "o": a.olt_id})
            n = c.execute(text("UPDATE jobs SET status = CASE WHEN status = 'DISPATCHED' THEN 'EXPIRED' ELSE 'CANCELLED' END, updated_at = now() "
                               "WHERE operation = 'olt_query' AND target_id = :o AND status IN ('PREVIEWED','PENDING_APPROVAL','APPROVED','DISPATCHED') RETURNING 1"),
                          {"o": a.olt_id}).rowcount
            c.execute(text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
                           "VALUES (:t,'olt',:o,'olt.transfer_started','1',CAST(:p AS jsonb))"),
                      {"t": a.tenant_id, "o": a.olt_id, "p": json.dumps({"to_edge": a.to_edge_id, "queries_ended": n})})
            print(f"transfer started: {n} open queries ended; finish after the old edge's lease has run out")
        elif a.cmd == "olt-transfer-finish":
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            from app.core import olt_ownership
            o = c.execute(text("SELECT transfer_to, lease_until FROM olts WHERE id = :o FOR UPDATE"), {"o": a.olt_id}).first()
            if o is None or o.transfer_to is None:
                sys.exit("no transfer in progress for this olt")
            wait = o.lease_until + olt_ownership.CLOCK_MARGIN if o.lease_until else None
            left = c.execute(text("SELECT :w > clock_timestamp()"), {"w": wait}).scalar() if wait else False
            if left:
                sys.exit(f"refused: the old edge may still hold a lease (until {wait.isoformat()} incl. margin); try again after that")
            c.execute(text("UPDATE olts SET edge_id = transfer_to, owner_epoch = owner_epoch + 1, transfer_to = NULL, transfer_started_at = NULL, lease_until = NULL "
                           "WHERE id = :o"), {"o": a.olt_id})
            ep = c.execute(text("SELECT owner_epoch FROM olts WHERE id = :o"), {"o": a.olt_id}).scalar()
            c.execute(text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
                           "VALUES (:t,'olt',:o,'olt.transfer_finished','1',CAST(:p AS jsonb))"),
                      {"t": a.tenant_id, "o": a.olt_id, "p": json.dumps({"owner_epoch": ep})})
            print(f"transfer finished: owner_epoch {ep}")
        elif a.cmd == "olt-board-mock":
            from app.core import olt_board_mock
            try:
                got = olt_board_mock.store(c, a.tenant_id, a.olt_name, a.slots)
            except ValueError as e:
                sys.exit(str(e))
            print(f"synthetic board inventory stored for {a.olt_name}: slots {got}")
        elif a.cmd == "ont-config-mock":
            from app.core import ont_config_mock
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": a.tenant_id})
            if c.execute(text("SELECT 1 FROM cpes WHERE tenant_id = :t AND id = :c"), {"t": a.tenant_id, "c": a.cpe_id}).first() is None:
                sys.exit("cpe not found for this tenant")
            c.execute(text("DELETE FROM cpe_config_fields WHERE tenant_id = :t AND cpe_id = :c AND source = 'mock'"), {"t": a.tenant_id, "c": a.cpe_id})
            n = 0
            if a.profile != "clear":
                try:
                    rows = ont_config_mock.rows_for(a.profile)
                except ValueError as e:
                    sys.exit(str(e))
                for name, inst, value in rows:
                    n += c.execute(
                        text("INSERT INTO cpe_config_fields (tenant_id, cpe_id, name, instance_key, value, captured_at, observed_at, data_model, protocol, source) "
                             "VALUES (:t,:c,:n,:i,CAST(:v AS jsonb),now(),now(),'tr181','tr069','mock') ON CONFLICT DO NOTHING"),
                        {"t": a.tenant_id, "c": a.cpe_id, "n": name, "i": inst, "v": json.dumps(value)}).rowcount
            print(f"synthetic configuration: {n} fields ({a.profile})")
        elif a.cmd == "feature-set":
            from app.core.features import FEATURES
            if a.feature not in FEATURES:
                sys.exit(f"unknown feature {a.feature!r}; known: {', '.join(sorted(FEATURES))}")
            if a.feature == "bench_writes" and a.state == "on":
                from app.core import bench
                if not bench.EDGE_SUPPORT:
                    sys.exit("refused: bench_writes cannot be turned on until the Edge-side bench gate exists and is tested (ADR-0030)")
            if a.feature == "olt_query" and a.state == "on":
                from app.core import olt_query
                if not olt_query.EDGE_SUPPORT:
                    sys.exit("refused: olt_query cannot be turned on until the Edge-side channel exists and is tested (ADR-0029)")
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
        elif a.cmd == "deactivate-account":  # closing a homologation: owner-only, explicit tenant filter (the owner role bypasses RLS), one outbox event each
            if not a.service_account and not a.user:
                sys.exit("name at least one --service-account or --user")
            done_sa = done_users = 0
            for name in a.service_account:
                rows = c.execute(text("SELECT id, role, is_active FROM service_accounts WHERE tenant_id = :t AND name = :n"), {"t": a.tenant_id, "n": name}).all()
                if len(rows) != 1:
                    sys.exit(f"service account {name!r}: expected exactly one, found {len(rows)}")
                sid, role, active = rows[0]
                if role == "edge_agent":
                    sys.exit(f"service account {name!r} is an Edge agent account: refused")
                if active:
                    c.execute(text("UPDATE service_accounts SET is_active = false WHERE tenant_id = :t AND id = :i"), {"t": a.tenant_id, "i": sid})
                    c.execute(text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
                                   "VALUES (:t,'service_account',:i,'account.deactivated','1',CAST(:p AS jsonb))"), {"t": a.tenant_id, "i": sid, "p": json.dumps({"kind": "service_account"})})
                    done_sa += 1
            for email in a.user:
                rows = c.execute(text("SELECT u.id, m.role FROM users_global u JOIN tenant_memberships m ON m.user_id = u.id "
                                      "WHERE m.tenant_id = :t AND lower(u.email) = lower(:e)"), {"t": a.tenant_id, "e": email}).all()
                if len(rows) != 1:
                    sys.exit("user: not a member of this tenant")
                uid, role = rows[0]
                if role == "isp_admin":
                    sys.exit("user is an isp_admin: refused (this command closes homologation accounts, it does not remove administrators)")
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('account:' || CAST(:u AS text), 0))"), {"u": str(uid)})
                if c.execute(text("SELECT 1 FROM tenant_memberships WHERE user_id = :u AND tenant_id <> :t LIMIT 1"), {"u": uid, "t": a.tenant_id}).first():
                    # sessions and token validity are per USER, not per tenant: ending them here would log the user out of the other tenants too
                    sys.exit("user belongs to other tenants: refused (this command closes accounts used only in this tenant)")
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"delegation:{a.tenant_id}:{uid}"})   # same lock as grant/revoke
                if c.execute(text("SELECT 1 FROM membership_delegations WHERE tenant_id = :t AND user_id = :u AND revoked_at IS NULL AND expires_at > clock_timestamp() LIMIT 1"),
                             {"t": a.tenant_id, "u": uid}).first():
                    # a delegation is revoked by a person (`revoked_by`), which the owner CLI is not: revoke it in the product or wait for it to expire (at most 8 h)
                    sys.exit("user has a live delegation in this tenant: revoke it in the product or wait for it to expire")
                c.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :t AND user_id = :u"), {"t": a.tenant_id, "u": uid})
                c.execute(text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"), {"u": uid})
                c.execute(text("UPDATE users_global SET tokens_valid_after = clock_timestamp(), is_active = false WHERE id = :u"), {"u": uid})
                c.execute(text("INSERT INTO events_outbox (tenant_id, aggregate_type, aggregate_id, event_type, schema_version, payload) "
                               "VALUES (:t,'user',:u,'account.deactivated','1',CAST(:p AS jsonb))"), {"t": a.tenant_id, "u": uid, "p": json.dumps({"kind": "membership"})})
                done_users += 1
            print(f"deactivated {done_sa} service account(s) and ended {done_users} membership(s)")
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
