"""Watchdog do LAB (ops/watchdog/watchdog.py) com docker/psql/relógio simulados: nenhum contêiner real é tocado."""
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "ops" / "watchdog" / "watchdog.py"
spec = importlib.util.spec_from_file_location("fc_watchdog", SRC)
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)

P = wd.PROJECT


def row(svc, state="running", status="Up 2 hours (healthy)"):
    return json.dumps({"Names": f"{P}-{svc}-1", "State": state, "Status": status})


class Fake:
    """docker ps devolve `rows`; `sql` responde por trecho da consulta; registra cada ação."""

    def __init__(self, rows, edge_age="10", outbox="0", action_rc=0):
        self.rows, self.edge_age, self.outbox, self.action_rc, self.calls = rows, edge_age, outbox, action_rc, []

    def __call__(self, cmd, timeout=30):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "ps"]:
            return 0, "\n".join(self.rows)
        if cmd[:2] in (["docker", "start"], ["docker", "restart"]):
            return self.action_rc, ""
        if cmd[:2] == ["docker", "exec"]:
            q = cmd[-1]
            if "from edges" in q:
                return 0, self.edge_age + "\n"
            if "events_outbox" in q:
                return 0, self.outbox + "\n"
        return 1, ""

    def actions(self):
        return [c[1:] for c in self.calls if c[:2] in (["docker", "start"], ["docker", "restart"])]


@pytest.fixture
def env(tmp_path):
    b = tmp_path / "bk"
    b.mkdir()
    (b / "fibercore-prod-20261031T000000Z.dump.done").touch()
    sent = []
    return tmp_path, b, sent


def make(env, fake, now):
    home, b, sent = env
    return wd.Watchdog(run=fake, now=lambda: now[0], home=home / "w", backup_dir=b, webhook=sent.append, disk=lambda p: wd.shutil._ntuple_diskusage(100, 50, 50))


def test_healthy_stack_does_nothing(env):
    f = Fake([row("api-core"), row("migrate", "exited", "Exited (0) 2 hours ago")])
    w = make(env, f, [1_000_000.0])
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (1_000_000.0, 1_000_000.0))
    w.run_all()
    assert f.actions() == [] and env[2] == []


def test_unhealthy_container_is_restarted_and_announced_once(env):
    f = Fake([row("outbox-relay", status="Up 1 hour (unhealthy)")])
    now = [1_000_000.0]
    w = make(env, f, now)
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
    w.run_all()
    assert f.actions() == [["restart", f"{P}-outbox-relay-1"]]
    assert any("reiniciado" in m for m in env[2])


def test_stopped_container_is_started_but_oneshot_exit0_is_not(env):
    f = Fake([row("web", "exited", "Exited (137) 1 minute ago"), row("migrate", "exited", "Exited (0) 3 hours ago"),
              row("migrate2", "exited", "Exited (1) 3 hours ago")])
    now = [1_000_000.0]
    w = make(env, f, now)
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
    w.run_all()
    acts = f.actions()
    assert ["start", f"{P}-web-1"] in acts and ["start", f"{P}-migrate2-1"] in acts
    assert all("migrate-1" not in a[1] for a in acts)
    # migrate com código != 0 NÃO é aceito como "terminou de propósito"
    f2 = Fake([row("migrate", "exited", "Exited (1) 3 hours ago")])
    w2 = make(env, f2, now)
    w2.run_all()
    assert f2.actions() == [["start", f"{P}-migrate-1"]]


def test_restart_loop_is_capped_and_escalates(env):
    f = Fake([row("api-core", status="Up 1 minute (unhealthy)")])
    now = [1_000_000.0]
    w = make(env, f, now)
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
    for _ in range(6):
        now[0] += 60
        os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
        w.run_all()
    assert len(f.actions()) == wd.MAX_ACTIONS  # 3 reinícios, depois só avisa
    assert any("precisa de pessoa" in m for m in env[2])
    # passada a janela de 1 h, volta a poder agir
    now[0] += wd.ACTION_WINDOW_S + 10
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
    w.run_all()
    assert len(f.actions()) == wd.MAX_ACTIONS + 1


def test_failed_restart_alerts_and_alert_has_cooldown_then_resolves(env):
    f = Fake([row("web", status="Up 1 minute (unhealthy)")], action_rc=1)
    now = [1_000_000.0]
    w = make(env, f, now)
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
    w.run_all()
    assert any("falhou" in m for m in env[2])
    n = len(env[2])
    now[0] += 60
    w.run_all()
    assert len(env[2]) == n  # cooldown: não repete em 1 min
    f.rows = [row("web")]  # voltou
    now[0] += 60
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
    w.run_all()
    assert any("resolvido: container:web" in m for m in env[2])


def test_edge_outbox_backup_and_unreachable_db_alerts(env):
    now = [1_000_000.0]
    f = Fake([row("api-core")], edge_age="900", outbox="4")
    w = make(env, f, now)  # backup .done com mtime real (antigo em relação a `now` fictício? 2026 > 1e6) -> ajusta abaixo
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0] - 27 * 3600, now[0] - 27 * 3600))
    w.run_all()
    text = " | ".join(env[2])
    assert "Edge sem heartbeat há 15 min" in text and "4 evento(s) do outbox" in text and "nenhum backup concluído" in text

    class NoDb(Fake):
        def __call__(self, cmd, timeout=30):
            if cmd[:2] == ["docker", "exec"]:
                return 1, "x"
            return super().__call__(cmd, timeout)

    env2 = (env[0] / "2", env[1], [])
    env2[0].mkdir()
    w2 = make(env2, NoDb([row("api-core")]), [now[0]])
    w2.run_all()
    assert any("não consegue consultar o banco" in m for m in env2[2])


def test_no_edge_row_alerts(env):
    now = [1_000_000.0]
    w = make(env, Fake([row("api-core")], edge_age="-1"), now)
    os.utime(env[1] / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
    w.run_all()
    assert any(m.endswith("Edge sem heartbeat") for m in env[2])


def test_state_and_log_are_private_and_contain_no_secrets(env):
    now = [1_000_000.0]
    f = Fake([row("web", status="Up (unhealthy)")])
    w = make(env, f, now)
    w.run_all()
    for name in ("state.json", "watchdog.log"):
        p = env[0] / "w" / name
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert (env[0] / "w").stat().st_mode & 0o077 == 0


def test_webhook_file_with_open_permissions_is_ignored(env, monkeypatch):
    home, b, _ = env
    w = wd.Watchdog(run=Fake([]), now=lambda: 1.0, home=home / "w", backup_dir=b)
    url = home / "w" / "webhook.url"
    url.write_text("https://example.invalid/hook")
    os.chmod(url, 0o644)
    called = []
    monkeypatch.setattr(wd.urllib.request, "urlopen", lambda *a, **k: called.append(1))
    w._post("x")
    assert called == []
    os.chmod(url, 0o600)
    w._post("x")
    assert called == [1]
    url.write_text("http://insecure.invalid/hook")  # só https
    w._post("x")
    assert called == [1]


def test_low_disk_alerts_per_mount(env):
    home, b, sent = env
    now = [1_000_000.0]
    os.utime(b / "fibercore-prod-20261031T000000Z.dump.done", (now[0], now[0]))
    w = wd.Watchdog(run=Fake([]), now=lambda: now[0], home=home / "w", backup_dir=b, webhook=sent.append,
                    disk=lambda p: wd.shutil._ntuple_diskusage(100, 95, 5) if p == "/var/lib/docker" else wd.shutil._ntuple_diskusage(100, 20, 80))
    w.run_all()
    assert any("disco docker" in m for m in sent) and not any("disco raiz" in m for m in sent)


def test_docker_unavailable_does_not_crash(env):
    w = make(env, lambda cmd, timeout=30: (127, "OSError"), [1_000_000.0])
    w.run_all()
