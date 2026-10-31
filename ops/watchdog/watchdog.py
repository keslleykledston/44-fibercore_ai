#!/usr/bin/env python3
"""FiberCore LAB watchdog: recupera contêineres e avisa quando a recuperação sozinha não basta.

Roda a cada minuto pelo cron (uma instância, `flock`). Só biblioteca padrão. Nada de segredo em argv, log ou alerta.

Recupera (com limite de MAX_ACTIONS por contêiner por hora, depois só avisa):
  - contêiner do projeto parado que deveria estar de pé  -> `docker start`
  - contêiner `unhealthy` por UNHEALTHY_CYCLES ciclos seguidos -> `docker restart`
  - NUNCA reinicia serviço com estado (postgres, nats) por estar `unhealthy`: só avisa (reiniciar interromperia gravações/publicações).
Falha ao coletar (docker, banco) é estado DESCONHECIDO: os alertas daquele assunto ficam como estão, nunca viram `resolvido`.
Só avisa (não há o que reiniciar daqui):
  - Edge sem heartbeat há mais de EDGE_STALE_S (padrão 300 s)
  - evento do outbox sem publicar há mais de OUTBOX_STALE_S (padrão 300 s)
  - backup concluído mais velho que BACKUP_STALE_H (padrão 26 h) ou disco abaixo de DISK_MIN_PCT livres
Alertas: linha JSON em `watchdog.log` e, se existir `webhook.url` (0600), um POST JSON. Cada chave de alerta repete no máximo 1 vez por hora e emite
um `resolved` quando a condição some.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT = os.environ.get("FC_WATCHDOG_PROJECT", "fibercore-prod")
HOME = Path(os.environ.get("FC_WATCHDOG_DIR", str(Path.home() / "fibercore-watchdog")))
BACKUP_DIR = Path(os.environ.get("FIBERCORE_BACKUP_DIR", str(Path.home() / "fibercore-backups")))
POSTGRES = os.environ.get("FC_WATCHDOG_POSTGRES", f"{PROJECT}-postgres-1")
ONESHOT = {"migrate"}  # serviços que terminam com código 0 de propósito
STATEFUL = {"postgres", "nats"}  # unhealthy => só avisa
UNHEALTHY_CYCLES = 2  # ciclos seguidos (~2 min) antes de reiniciar
MAX_ACTIONS = 3
ACTION_WINDOW_S = 3600
ALERT_COOLDOWN_S = 3600
EDGE_STALE_S = int(os.environ.get("FC_EDGE_STALE_S", "300"))
OUTBOX_STALE_S = int(os.environ.get("FC_OUTBOX_STALE_S", "300"))
BACKUP_STALE_H = int(os.environ.get("FC_BACKUP_STALE_H", "26"))
DISK_MIN_PCT = int(os.environ.get("FC_DISK_MIN_PCT", "10"))
LOG_MAX = 2 * 1024 * 1024


def sh(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, type(e).__name__


class Watchdog:
    def __init__(self, run=sh, now=time.time, home: Path = HOME, backup_dir: Path = BACKUP_DIR, webhook=None, disk=shutil.disk_usage):
        self.run, self.now, self.home, self.backup_dir, self.disk = run, now, home, backup_dir, disk
        self.webhook = webhook or self._post
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_path = self.home / "state.json"
        self.state = self._load()
        self.events: list[dict] = []

    # ---------- estado e saída ----------
    def _load(self) -> dict:
        try:
            s = json.loads(self.state_path.read_text())
            if isinstance(s, dict):
                return {"actions": s.get("actions", {}), "alerts": s.get("alerts", {}), "unhealthy": s.get("unhealthy", {})}
        except (OSError, ValueError):
            pass
        return {"actions": {}, "alerts": {}, "unhealthy": {}}

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.state_path)

    def log(self, level: str, msg: str, **kw) -> None:
        line = json.dumps({"t": int(self.now()), "level": level, "msg": msg, **kw}, ensure_ascii=False)
        p = self.home / "watchdog.log"
        if p.exists() and p.stat().st_size > LOG_MAX:
            os.replace(p, self.home / "watchdog.log.1")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(line + "\n")
        self.events.append({"level": level, "msg": msg, **kw})

    def _post(self, text: str) -> None:
        p = self.home / "webhook.url"
        try:
            st = p.stat()
        except OSError:
            return
        if st.st_mode & 0o077:
            self.log("warn", "webhook.url com permissão aberta; ignorado")
            return
        url = p.read_text().strip()
        if not url.startswith("https://"):
            return
        req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=8).close()
        except Exception as e:  # noqa: BLE001  # o aviso não pode derrubar o watchdog
            self.log("warn", "webhook falhou", err=type(e).__name__)

    # ---------- alertas com cooldown e resolução ----------
    def alert(self, key: str, text: str) -> None:
        a = self.state["alerts"].get(key)
        t = self.now()
        if a and t - a["last"] < ALERT_COOLDOWN_S:
            return
        self.state["alerts"][key] = {"last": t}
        self.log("alert", text, key=key)
        self.webhook(f"[FiberCore LAB] {text}")

    def resolve_missing(self, active: set[str], unknown: set[str]) -> None:
        # chave de assunto cuja coleta falhou: preserva (não se sabe se a condição sumiu)
        for key in [k for k in self.state["alerts"] if k not in active and not any(k == u or k.startswith(u + ":") for u in unknown)]:
            del self.state["alerts"][key]
            self.log("info", "resolvido", key=key)
            self.webhook(f"[FiberCore LAB] resolvido: {key}")

    # ---------- contêineres ----------
    def _may_act(self, name: str) -> bool:
        t = self.now()
        recent = [x for x in self.state["actions"].get(name, []) if t - x < ACTION_WINDOW_S]
        self.state["actions"][name] = recent
        if len(recent) >= MAX_ACTIONS:
            return False
        recent.append(t)
        return True

    def containers(self) -> list[dict] | None:
        rc, out = self.run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={PROJECT}", "--format", "{{json .}}"])
        if rc != 0:
            self.log("error", "docker ps falhou", rc=rc)
            return None
        rows = []
        for line in out.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def check_containers(self, active: set[str], unknown: set[str]) -> None:
        rows = self.containers()
        if rows is None:
            unknown.add("container")
            self.state["unhealthy"] = {}  # ciclo desconhecido quebra a sequência de "unhealthy seguidos"
            active.add("docker")
            self.alert("docker", "watchdog não consegue consultar o Docker")
            return
        seen_unhealthy: set[str] = set()
        for c in rows:
            name = c.get("Names", "")
            svc = name.removeprefix(PROJECT + "-").rsplit("-", 1)[0]
            state, status = c.get("State", ""), c.get("Status", "")
            action = None
            if state != "running":
                if svc in ONESHOT and state == "exited" and "Exited (0)" in status:
                    continue
                action = "start"
            elif "(unhealthy)" in status:
                seen_unhealthy.add(name)
                n = self.state["unhealthy"].get(name, 0) + 1
                self.state["unhealthy"][name] = n
                key = f"container:{svc}"
                if svc in STATEFUL:
                    active.add(key)
                    self.alert(key, f"{svc} está unhealthy; serviço com estado não é reiniciado sozinho, precisa de pessoa")
                    continue
                if n < UNHEALTHY_CYCLES:
                    continue
                action = "restart"
            if not action:
                continue
            key = f"container:{svc}"
            if self._may_act(name):
                rc, _ = self.run(["docker", action, name], timeout=120)
                self.log("warn", f"{action} de {svc}", rc=rc, svc=svc)
                if rc != 0:
                    active.add(key)
                    self.alert(key, f"{svc}: {action} falhou")
                else:
                    active.add(key + ":recuperado")
                    self.alert(key + ":recuperado", f"{svc} estava {'parado' if action == 'start' else 'unhealthy'} e foi reiniciado")
            else:
                active.add(key)
                self.alert(key, f"{svc} continua {'parado' if action == 'start' else 'unhealthy'} depois de {MAX_ACTIONS} reinícios em 1 h; precisa de pessoa")
        for n in [n for n in self.state["unhealthy"] if n not in seen_unhealthy]:
            del self.state["unhealthy"][n]

    # ---------- consultas ao banco (só contagem/idade) ----------
    def sql(self, q: str) -> str | None:
        rc, out = self.run(["docker", "exec", "-i", POSTGRES, "sh", "-c", 'psql -U "${POSTGRES_USER:-fibercore}" -d "${POSTGRES_DB:-fibercore}" -tAc "$0"', q])
        return out.strip() if rc == 0 else None

    def check_edge(self, active: set[str], unknown: set[str]) -> None:
        v = self.sql("select coalesce(max(extract(epoch from now()-last_heartbeat_at))::bigint, -1) from edges where status <> 'revoked'")
        if v is None:
            unknown.update({"edge", "outbox"})
            active.add("db")
            self.alert("db", "watchdog não consegue consultar o banco")
            return
        try:
            age = int(v)
        except ValueError:
            unknown.add("edge")
            return
        if age == -1 or age > EDGE_STALE_S:
            active.add("edge"); self.alert("edge", "Edge sem heartbeat" + ("" if age == -1 else f" há {age // 60} min"))

    def check_outbox(self, active: set[str], unknown: set[str]) -> None:
        v = self.sql(f"select count(*) from events_outbox where published_at is null and created_at < now() - interval '{OUTBOX_STALE_S} seconds'")
        if v is None or not v.isdigit():
            unknown.add("outbox")
            return
        if int(v) > 0:
            active.add("outbox")
            self.alert("outbox", f"{v} evento(s) do outbox sem publicar há mais de {OUTBOX_STALE_S // 60} min")

    def check_backup_and_disk(self, active: set[str]) -> None:
        done = sorted(self.backup_dir.glob("fibercore-prod-*.dump.done"), key=lambda p: p.stat().st_mtime) if self.backup_dir.exists() else []
        if not done or self.now() - done[-1].stat().st_mtime > BACKUP_STALE_H * 3600:
            active.add("backup"); self.alert("backup", f"nenhum backup concluído nas últimas {BACKUP_STALE_H} h")
        for label, path in (("raiz", "/"), ("docker", "/var/lib/docker")):
            try:
                u = self.disk(path)
            except OSError:
                continue
            if u.free * 100 // u.total < DISK_MIN_PCT:
                active.add(f"disk:{label}"); self.alert(f"disk:{label}", f"disco {label} com menos de {DISK_MIN_PCT}% livre")

    def run_all(self) -> None:
        active: set[str] = set()
        unknown: set[str] = set()
        self.check_containers(active, unknown)
        self.check_edge(active, unknown)
        if "outbox" not in unknown:
            self.check_outbox(active, unknown)
        self.check_backup_and_disk(active)
        # chaves ":recuperado" são avisos de um evento só: somem no ciclo seguinte sem emitir "resolvido"
        for k in [k for k in self.state["alerts"] if k.endswith(":recuperado") and k not in active]:
            del self.state["alerts"][k]
        self.resolve_missing(active, unknown)
        self.save()


def main() -> int:
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = os.open(HOME / ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    Watchdog().run_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
