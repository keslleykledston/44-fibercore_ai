"""NATS com TLS mútuo + ACL por papel (ADR-0042): configuração dos clientes (unitário) e prova contra um NATS real (integração).

A integração sobe um projeto compose PRÓPRIO (`infra/compose/nats-acl-test.compose.yaml`, nome único, portas altas livres, `down -v` ao final) com uma PKI
descartável gerada por `scripts/nats-tls.sh` em `build/` (ignorado pelo Git, apagada ao final). Não toca na stack da LAB. Sem Docker, só os testes unitários rodam.
"""
import asyncio
import os
import shutil
import socket
import ssl
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import nats
import pytest
from sqlalchemy import text

from app.core.db import make_engine, scoped_connection
from app.events import bus, consumer, outbox
from app.workers.relay import relay_once

REPO = Path(__file__).resolve().parents[3]
TLS_SCRIPT = REPO / "scripts" / "nats-tls.sh"
COMPOSE_FILE = REPO / "infra" / "compose" / "nats-acl-test.compose.yaml"
OPENSSL = shutil.which("openssl") or "openssl"
ENV_KEYS = ("NATS_TLS_CA", "NATS_TLS_CERT", "NATS_TLS_KEY", "NATS_INBOX_PREFIX")


def run(coro):
    return asyncio.run(coro)


def role_env(pki: Path, role: str) -> dict:
    return {"NATS_TLS_CA": str(pki / "ca.pem"), "NATS_TLS_CERT": str(pki / f"{role}.pem"), "NATS_TLS_KEY": str(pki / f"{role}.key"), "NATS_INBOX_PREFIX": f"_INBOX.{role}"}


# ---------------------------------------------------------------------------------------------------------------- configuração dos clientes (sem Docker)

def test_nothing_configured_changes_nothing(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    assert bus.connect_options() == {}
    assert bus.connect_options({k: "" for k in ENV_KEYS}) == {}          # `${VAR:-}` do compose chega como string vazia
    assert bus.connect_options({k: "  " for k in ENV_KEYS}) == {}


def test_connect_passes_exactly_the_old_options_when_off(monkeypatch):
    seen = {}

    async def fake_connect(url, **kw):
        seen.update(url=url, **kw)

        class NC:
            def jetstream(self):
                return "js"
        return NC()

    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(bus.nats, "connect", fake_connect)
    run(bus.connect("nats://nats:4222"))
    assert seen == {"url": "nats://nats:4222", "connect_timeout": 3, "max_reconnect_attempts": 3}


def test_tls_and_identity_build_a_verifying_context():
    d = _gen_pki()
    try:
        opts = bus.connect_options(role_env(d, "relay"))
        ctx = opts["tls"]
        assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True        # o servidor É verificado
        assert opts["inbox_prefix"] == b"_INBOX.relay"
        ca_only = bus.connect_options({"NATS_TLS_CA": str(d / "ca.pem")})
        assert set(ca_only) == {"tls"}
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.parametrize("env,why", [
    ({"NATS_TLS_CERT": "/x/c.pem"}, "together"),
    ({"NATS_TLS_KEY": "/x/c.key"}, "together"),
    ({"NATS_TLS_CERT": "/x/c.pem", "NATS_TLS_KEY": "/x/c.key"}, "need NATS_TLS_CA"),
    ({"NATS_TLS_CA": "/nao/existe.pem"}, "unusable"),
    ({"NATS_INBOX_PREFIX": "_INBOX..relay"}, "dot-separated"),
    ({"NATS_INBOX_PREFIX": "_INBOX.>"}, "dot-separated"),
    ({"NATS_INBOX_PREFIX": "_INBOX.re lay"}, "dot-separated"),
])
def test_half_configured_or_unusable_settings_fail_closed(env, why):
    with pytest.raises(ValueError, match=why):
        bus.connect_options(env)


def test_unreadable_certificate_or_key_fails_closed(tmp_path):
    d = _gen_pki()
    try:
        junk = tmp_path / "junk.pem"
        junk.write_text("nao e um certificado")
        env = role_env(d, "relay")
        with pytest.raises(ValueError, match="unusable"):
            bus.connect_options({**env, "NATS_TLS_CERT": str(junk)})
        with pytest.raises(ValueError, match="unusable"):
            bus.connect_options({**env, "NATS_TLS_KEY": str(d / "consumer.key")})          # chave que não é do certificado
        with pytest.raises(ValueError, match="unusable"):
            bus.connect_options({**env, "NATS_TLS_CA": str(junk)})
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_only_the_relay_and_the_consumer_speak_nats():
    """Guarda do ADR-0042: um cliente NATS novo (ou o Edge passando a falar NATS) exige papel + ACL + ADR, não pode aparecer de graça."""
    api_app = REPO / "apps" / "api" / "app"
    users = sorted(p.relative_to(api_app).as_posix() for p in api_app.rglob("*.py") if "import nats" in p.read_text() or "from nats" in p.read_text())
    assert users == ["events/bus.py", "events/consumer.py"]
    connects = sorted(p.relative_to(api_app).as_posix() for p in api_app.rglob("*.py") if "nats.connect(" in p.read_text())
    assert connects == ["events/bus.py"]
    callers = sorted(p.relative_to(api_app).as_posix() for p in api_app.rglob("*.py") if "bus.connect(" in p.read_text())
    assert callers == ["events/consumer.py", "workers/relay.py"]
    edge = REPO / "agents" / "edge"
    assert "nats" not in (edge / "go.mod").read_text().lower()
    assert [p for p in edge.rglob("*.go") if "nats" in p.read_text().lower()] == []


# ---------------------------------------------------------------------------------------------------------------- PKI e stack de integração

def _gen_pki() -> Path:
    d = REPO / "build" / f"nats-it-{uuid4().hex[:8]}"
    subprocess.run([str(TLS_SCRIPT), "gen", str(d)], check=True, capture_output=True)
    return d


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0


class Stack:
    def __init__(self, pki: Path, secure_port: int, plain_port: int):
        self.pki, self.secure_url, self.plain_url = pki, f"nats://127.0.0.1:{secure_port}", f"nats://127.0.0.1:{plain_port}"

    def env(self, role: str) -> dict:
        return role_env(self.pki, role)


async def connect_as(url: str, env: dict, errors: list | None = None, deadline: float = 15.0):
    async def on_error(e):
        if errors is not None:
            errors.append(str(e))
    nc = await asyncio.wait_for(nats.connect(url, connect_timeout=3, max_reconnect_attempts=1, reconnect_time_wait=0.2, error_cb=on_error, **bus.connect_options(env)), deadline)
    return nc, nc.jetstream()


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    if not _docker_ok():
        pytest.skip("Docker indisponível (integração do NATS seguro)")
    pki = _gen_pki()
    project = f"fibercore-natsit-{uuid4().hex[:8]}"
    ports = (_free_port(), _free_port())
    empty_env = tmp_path_factory.mktemp("natsit") / "empty.env"
    empty_env.write_text("")                                                               # nunca deixar o compose ler um .env do repositório
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"), "NATS_IT_SECURE_PORT": str(ports[0]), "NATS_IT_PLAIN_PORT": str(ports[1]), "NATS_IT_PKI_DIR": str(pki)}
    compose = ["docker", "compose", "-p", project, "--env-file", str(empty_env), "-f", str(COMPOSE_FILE)]
    try:
        subprocess.run([*compose, "up", "-d"], check=True, capture_output=True, env=env, timeout=240)
        st = Stack(pki, *ports)
        deadline = time.time() + 40
        while True:
            try:
                async def probe():
                    nc, _ = await connect_as(st.secure_url, st.env("relay"), deadline=5)
                    await nc.close()
                    nc, _ = await connect_as(st.plain_url, {}, deadline=5)
                    await nc.close()
                run(probe())
                break
            except Exception:  # noqa: BLE001
                if time.time() > deadline:
                    logs = subprocess.run([*compose, "logs", "--no-color", "--tail", "30"], capture_output=True, text=True, env=env).stdout
                    raise RuntimeError(f"NATS de teste não ficou pronto:\n{logs}") from None
                time.sleep(1)
        yield st
    finally:
        down = subprocess.run([*compose, "down", "-v", "--remove-orphans", "--timeout", "3"], capture_output=True, text=True, env=env, timeout=120)
        left = _project_leftovers(project)
        if left:                                                                         # só mexe no que leva o rótulo do NOSSO projeto (nome único)
            subprocess.run(["docker", "rm", "-fv", *left], capture_output=True, timeout=120)
            left = _project_leftovers(project)
        if down.returncode != 0 or left:
            # deixa a PKI e diz exatamente o que ficou, para diagnóstico e limpeza manual (docker compose -p <projeto> down -v)
            raise AssertionError(f"teardown do NATS de teste incompleto: projeto={project} down_rc={down.returncode} contêineres_restantes={left} pki={pki} stderr={down.stderr[-300:]}")
        shutil.rmtree(pki, ignore_errors=True)


def _project_leftovers(project: str) -> list[str]:
    out = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"], capture_output=True, text=True, timeout=60)
    return out.stdout.split()


def _issue(pki: Path, name: str, san: str, days: int = 1, ca: Path | None = None) -> Path:
    """Certificado de cliente 'artesanal' (para os casos que o script recusa de propósito: identidade desconhecida, expirado)."""
    ca = ca or pki
    key, csr, crt, ext = (pki / f"{name}.{x}" for x in ("key", "csr", "pem", "ext"))
    subprocess.run([OPENSSL, "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(key)], check=True, capture_output=True)
    subprocess.run([OPENSSL, "req", "-new", "-key", str(key), "-subj", f"/CN={name}", "-out", str(csr)], check=True, capture_output=True)
    ext.write_text(f"basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=clientAuth\nsubjectAltName={san}\n")
    subprocess.run([OPENSSL, "x509", "-req", "-in", str(csr), "-CA", str(ca / "ca.pem"), "-CAkey", str(ca / "ca.key"), "-CAcreateserial", "-days", str(days), "-sha256", "-extfile", str(ext), "-out", str(crt)], check=True, capture_output=True)
    return crt


def _wait_for(pred, seconds=3.0):
    async def go():
        end = time.time() + seconds
        while time.time() < end:
            if pred():
                return True
            await asyncio.sleep(0.05)
        return pred()
    return go()


# ---------------------------------------------------------------------------------------------------------------- integração: quem entra

def test_without_a_valid_identity_the_connection_is_refused(stack, tmp_path):
    """Cada forma de chegar sem credencial válida é recusada (e a mesma stack aceita o relay legítimo: o teste não passa por defeito de ambiente)."""
    async def ok():
        nc, _ = await connect_as(stack.secure_url, stack.env("relay"))
        assert nc.is_connected
        await nc.close()
    run(ok())

    other = _gen_pki()                                  # outra CA, mesmo nome de papel
    unknown = _issue(stack.pki, "edge", "DNS:fibercore-edge")   # CA certa, identidade sem usuário no ACL
    expired = _issue(stack.pki, "relay-expired", "DNS:fibercore-relay", days=0)
    time.sleep(1.2)
    try:
        cases = {
            "sem TLS nem credencial (cliente antigo)": {},
            "TLS verificado, sem certificado de cliente": {"NATS_TLS_CA": str(stack.pki / "ca.pem")},
            "certificado de outra CA": role_env(other, "relay") | {"NATS_TLS_CA": str(stack.pki / "ca.pem")},
            "servidor de outra CA (cliente não confia)": role_env(other, "relay"),
            "identidade desconhecida (CA certa, sem usuário)": {**stack.env("relay"), "NATS_TLS_CERT": str(unknown), "NATS_TLS_KEY": str(stack.pki / "edge.key")},
            "certificado expirado": {**stack.env("relay"), "NATS_TLS_CERT": str(expired), "NATS_TLS_KEY": str(stack.pki / "relay-expired.key")},
        }
        for label, env in cases.items():
            async def attempt(env=env):
                nc, _ = await connect_as(stack.secure_url, env, deadline=12)
                await nc.close()
            with pytest.raises(Exception) as refusal:  # noqa: B017, PT011 - qualquer recusa (handshake, autorização ou prazo), nunca uma conexão
                run(attempt())
            assert not isinstance(refusal.value, ValueError), (label, "erro de configuração do teste, não recusa do servidor")
            print("recusado:", label, "->", type(refusal.value).__name__)
    finally:
        shutil.rmtree(other, ignore_errors=True)


def test_a_misconfigured_plain_client_gives_up_instead_of_hanging(stack, monkeypatch):
    """Rollback/skew hazard: relay ainda sem as variáveis TLS contra o NATS seguro. Sem prazo total, o connect() do nats-py pode esperar para sempre (observado)."""
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(bus, "CONNECT_DEADLINE_S", 3.0)
    t = time.time()
    with pytest.raises(Exception) as e:  # noqa: B017, PT011
        run(bus.connect(stack.secure_url))
    assert time.time() - t < 15 and not isinstance(e.value, ValueError)


def test_feature_off_the_plain_nats_works_exactly_as_before(stack, monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)

    async def go():
        nc, js = await bus.connect(stack.plain_url)                    # o caminho de produção de hoje: sem nenhuma variável
        await bus.ensure_streams(js)
        ack = await js.publish("fibercore.events.t1.x", b"{}", headers={"Nats-Msg-Id": "plain-1"})
        await nc.close()
        return ack.seq
    assert run(go()) == 1


# ---------------------------------------------------------------------------------------------------------------- integração: o que cada papel pode (e não pode)

def test_each_role_can_do_its_job_and_nothing_else(stack):
    """O código REAL (bus.ensure_streams, ensure_consumer, js.publish, ack/nak/term, DLQ) funciona com as permissões mínimas; o resto é negado e NÃO tem efeito."""
    async def go():
        r_err, c_err = [], []
        rnc, rjs = await connect_as(stack.secure_url, stack.env("relay"), r_err)
        cnc, cjs = await connect_as(stack.secure_url, stack.env("consumer"), c_err)
        try:
            await bus.ensure_streams(rjs)
            await bus.ensure_streams(cjs)
            for i in range(3):
                await rjs.publish(f"fibercore.events.t1.ev{i}", b'{"i":%d}' % i, headers={"Nats-Msg-Id": f"id-{i}"})
            sub = await consumer.ensure_consumer(cjs, "audit-projection")
            m1, m2, m3 = await sub.fetch(3, timeout=3)
            await m1.ack()
            await m2.nak(delay=1)
            await m3.term()
            await cjs.publish(f"{bus.DLQ_ROOT}.audit-projection", m3.data, headers={"x-original-subject": m3.subject})
            assert (await rjs.stream_info(bus.DLQ_STREAM)).state.messages == 1
            await asyncio.sleep(1.5)
            (again,) = await sub.fetch(1, timeout=3)                    # só o nak volta; o ack e o term nunca
            assert again.subject == m2.subject
            await again.ack()
            for _ in range(40):                                         # o ack é um publish sem resposta: o servidor o aplica logo depois
                ci = await cjs.consumer_info(bus.STREAM, "audit-projection")
                if (ci.num_ack_pending, ci.num_pending) == (0, 0):
                    break
                await asyncio.sleep(0.1)
            assert (ci.num_ack_pending, ci.num_pending) == (0, 0)       # ack, nak e term CHEGARAM ao servidor (sem a permissão de $JS.ACK eles se perdem em silêncio)
            assert (await rjs.stream_info(bus.STREAM)).state.messages == 3
            base = (await rjs.stream_info(bus.STREAM)).state.messages

            # --- papel errado: cada tentativa gera 'Permissions Violation' e NÃO muda nada ---
            await cnc.publish("fibercore.events.t1.forjado", b"{}")                 # consumer não publica evento
            await cnc.publish("$JS.API.STREAM.DELETE.FIBERCORE_EVENTS", b"")      # nem apaga stream
            await cnc.publish("$JS.API.STREAM.PURGE.FIBERCORE_EVENTS", b"")
            await cnc.subscribe("_INBOX.relay.>")                                 # nem escuta a caixa de resposta do relay
            await cnc.flush()
            await rnc.publish(f"{bus.DLQ_ROOT}.audit-projection", b"x")            # relay não escreve na DLQ
            await rnc.publish("$JS.API.CONSUMER.MSG.NEXT.FIBERCORE_EVENTS.audit-projection", b"")   # nem consome
            await rnc.publish("$JS.API.STREAM.DELETE.FIBERCORE_EVENTS", b"")
            await rnc.subscribe("fibercore.events.>")                             # nem espia os eventos
            await rnc.subscribe("_INBOX.consumer.>")
            await rnc.flush()
            await _wait_for(lambda: len(c_err) >= 4 and len(r_err) >= 5, 4.0)
            joined_c, joined_r = "\n".join(c_err).lower(), "\n".join(r_err).lower()          # nats-py devolve a mensagem em minúsculas
            for kind, subject in (("publish", "fibercore.events.t1.forjado"), ("publish", "$JS.API.STREAM.DELETE.FIBERCORE_EVENTS"), ("publish", "$JS.API.STREAM.PURGE.FIBERCORE_EVENTS"), ("subscription", "_INBOX.relay.>")):
                assert f'permissions violation for {kind} to "{subject.lower()}"' in joined_c, (kind, subject, c_err)
            for kind, subject in (("publish", f"{bus.DLQ_ROOT}.audit-projection"), ("publish", "$JS.API.CONSUMER.MSG.NEXT.FIBERCORE_EVENTS.audit-projection"), ("publish", "$JS.API.STREAM.DELETE.FIBERCORE_EVENTS"),
                                  ("subscription", "fibercore.events.>"), ("subscription", "_INBOX.consumer.>")):
                assert f'permissions violation for {kind} to "{subject.lower()}"' in joined_r, (kind, subject, r_err)
            await asyncio.sleep(0.3)
            info = await rjs.stream_info(bus.STREAM)
            assert info.state.messages == base == 3                                # nada foi forjado, apagado ou purgado
            assert (await rjs.stream_info(bus.DLQ_STREAM)).state.messages == 1
        finally:
            await rnc.close()
            await cnc.close()
    run(go())


def test_rotation_reissued_certificate_works_without_restarting_the_server(stack):
    old = (stack.pki / "relay.pem").read_text()
    subprocess.run([str(TLS_SCRIPT), "issue", str(stack.pki), "relay"], check=True, capture_output=True)
    assert (stack.pki / "relay.pem").read_text() != old
    assert not [p for p in stack.pki.iterdir() if p.name.startswith(".issue.")]            # sem resíduo temporário

    async def go():
        nc, js = await connect_as(stack.secure_url, stack.env("relay"))
        await bus.ensure_streams(js)                                  # usa o certificado novo para uma chamada de API permitida (sem deixar mensagem no stream)
        await nc.close()
    run(go())
    refused = subprocess.run([str(TLS_SCRIPT), "issue", str(stack.pki), "api"], capture_output=True, text=True)
    assert refused.returncode != 0 and "desconhecido" in refused.stderr                  # a API não tem identidade NATS


def test_the_pki_script_refuses_to_write_secrets_inside_the_repo(tmp_path):
    r = subprocess.run([str(TLS_SCRIPT), "gen", str(REPO / "docs" / "pki-nao-pode")], capture_output=True, text=True)
    assert r.returncode != 0 and "dentro do repositório" in r.stderr
    assert not (REPO / "docs" / "pki-nao-pode").exists()
    d = _gen_pki()
    try:
        again = subprocess.run([str(TLS_SCRIPT), "gen", str(d)], capture_output=True, text=True)
        assert again.returncode != 0 and "já tem uma CA" in again.stderr
        assert oct((d / "ca.key").stat().st_mode & 0o777) == "0o600" and oct(d.stat().st_mode & 0o777) == "0o700"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------- integração: relay e consumer REAIS (com PostgreSQL)

@pytest.fixture
def engines(seed, app_url, worker_url, migrated):
    with migrated.begin() as c:
        c.execute(text("TRUNCATE events_outbox, processed_events"))
    return make_engine(app_url), make_engine(worker_url)


def test_real_relay_and_consumer_over_tls_and_acl(stack, engines, seed):
    app_e, worker_e = engines
    with scoped_connection(app_e, tenant_id=seed["A"]) as c:
        eid = outbox.enqueue(c, tenant_id=seed["A"], aggregate_type="olt", aggregate_id=uuid4(), event_type="olt.acl", payload={"k": "v"})

    async def go():
        rnc, rjs = await connect_as(stack.secure_url, stack.env("relay"))
        cnc, cjs = await connect_as(stack.secure_url, stack.env("consumer"))
        try:
            await bus.ensure_streams(rjs)
            assert await relay_once(worker_e, rjs) == 1                                   # o relay REAL, com a identidade do relay
            sub = await consumer.ensure_consumer(cjs, "audit-projection")
            n = await consumer.consume_batch(sub, cjs, app_e, "audit-projection", consumer.audit_handler)   # o consumer REAL
            await asyncio.sleep(0.3)
            return n, (await rjs.stream_info(bus.STREAM)).state.messages
        finally:
            await rnc.close()
            await cnc.close()
    handled, in_stream = run(go())
    assert handled == 1 and in_stream >= 1
    with scoped_connection(app_e, tenant_id=seed["A"]) as c:
        assert c.execute(text("SELECT count(*) FROM audit_log WHERE action='event.consumed' AND target_id=:e"), {"e": str(eid)}).scalar() == 1
