#!/usr/bin/env python3
r"""Imagens por digest: verificação (offline) e atualização (precisa de rede).

  scripts/images.py check [--root DIR]        falha (rc=1) se algum FROM/image:/`docker run` ficar sem digest, com digest
                                              diferente de infra/images.lock, fora do lock ou com digest PENDING
  scripts/images.py update [--write]          resolve o digest atual de cada <repo>:<tag> do lock (docker buildx imagetools)
                                              e mostra o que mudaria; com --write regrava o lock e todos os arquivos

Regras do `check`:
  * Dockerfile: todo `FROM` externo e `COPY --from=`/`--mount ...from=` externo precisam de `@sha256:` (stage anterior e `scratch` são isentos; `$VAR` é recusado).
  * Compose: todo `image:` precisa de `@sha256:`, exceto serviço com `build:` (a tag é do build local).
  * Makefile, scripts e CI: a imagem de TODO `docker run|create|pull` e de `uses: docker://` é extraída (mesmo fora do lock, mesmo em linha continuada com `\`)
    e validada; se não der para identificar a imagem, falha. Qualquer outra ocorrência textual de um <repo>:<tag> do lock também precisa do digest do lock.
  * Toda imagem externa precisa estar no lock; PENDING no lock = falha (lista explícita do que falta resolver).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "build", ".claude", "__pycache__", ".next", "legacy", "cap_raw"}
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REF_DIGEST_RE = re.compile(r"@(sha256:[0-9a-f]{64})$")
LOCK_REL = Path("infra/images.lock")


def read_lock(root: Path) -> dict[str, str]:
    lock: dict[str, str] = {}
    for n, raw in enumerate((root / LOCK_REL).read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2 or ":" not in parts[0] or "@" in parts[0] or not (parts[1] == "PENDING" or DIGEST_RE.match(parts[1])):
            raise SystemExit(f"{LOCK_REL}:{n}: linha inválida (esperado '<repo>:<tag> sha256:<64 hex>|PENDING'): {raw!r}")
        if parts[0] in lock:
            raise SystemExit(f"{LOCK_REL}:{n}: entrada duplicada {parts[0]}")
        lock[parts[0]] = parts[1]
    return lock


def walk(root: Path):
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts) or not p.is_file():
            continue
        yield p


def is_dockerfile(p: Path) -> bool:
    return p.name == "Dockerfile" or p.name.startswith("Dockerfile.") or p.name.endswith(".Dockerfile")


def is_compose(p: Path) -> bool:
    return p.suffix in {".yaml", ".yml"} and ("compose" in p.name) and ".github" not in p.parts


def is_workflow(p: Path) -> bool:
    return p.suffix in {".yaml", ".yml"} and ".github" in p.parts and "workflows" in p.parts


def is_text_target(p: Path, root: Path) -> bool:
    rel = p.relative_to(root)
    return (
        is_dockerfile(p) or is_compose(p) or is_workflow(p) or p.name == "Makefile" or p.suffix == ".sh"
        and rel.parts[0] in {"scripts", "ops", "infra", "tools"}
    )


def split_ref(ref: str) -> tuple[str, str | None]:
    m = REF_DIGEST_RE.search(ref)
    return (ref[: m.start()], m.group(1)) if m else (ref, None)


def check_ref(where: str, ref: str, lock: dict[str, str], errors: list[str]) -> None:
    base, digest = split_ref(ref)
    if "$" in ref:
        errors.append(f"{where}: referência com variável não é verificável: {ref}")
    elif digest is None:
        errors.append(f"{where}: imagem sem digest: {ref}")
    elif base not in lock:
        errors.append(f"{where}: {base} não está em {LOCK_REL}")
    elif lock[base] != digest:
        errors.append(f"{where}: digest de {base} difere do lock ({digest} != {lock[base]})")


def check_dockerfile(p: Path, rel: str, lock: dict[str, str], errors: list[str]) -> None:
    stages: set[str] = set()
    for n, raw in logical_lines(p.read_text()):   # instrução continuada com `\` (ex.: `FROM \` + imagem na linha seguinte) vale como uma só
        for fm in re.finditer(r"(?:^\s*COPY\s+(?:--\S+\s+)*?--from=|^\s*RUN\s+.*--mount=\S*?\bfrom=)([^\s,]+)", raw, re.I):
            src = fm.group(1)
            if src.lower() not in stages and not src.isdigit():
                check_ref(f"{rel}:{n}", src, lock, errors)
        m = re.match(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?\s*$", raw, re.I)
        if not m:
            continue
        ref, alias = m.group(1), m.group(2)
        if ref.lower() != "scratch" and ref.lower() not in stages:
            check_ref(f"{rel}:{n}", ref, lock, errors)
        if alias:
            stages.add(alias.lower())


def check_compose(p: Path, rel: str, lock: dict[str, str], errors: list[str]) -> None:
    try:
        doc = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        errors.append(f"{rel}: YAML inválido: {e}")
        return
    for name, svc in ((doc or {}).get("services") or {}).items():
        if not isinstance(svc, dict):
            continue
        image = svc.get("image")
        if image is None:
            if "build" not in svc and "override" not in p.name:   # override só ajusta serviço que o compose.yaml já define
                errors.append(f"{rel}: serviço {name} sem image nem build")
        elif "build" not in svc:
            check_ref(f"{rel}: serviço {name}", str(image), lock, errors)


def check_workflow(p: Path, rel: str, lock: dict[str, str], errors: list[str]) -> None:
    try:
        doc = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        errors.append(f"{rel}: YAML inválido: {e}")
        return
    for job, spec in ((doc or {}).get("jobs") or {}).items():
        for sname, svc in ((spec or {}).get("services") or {}).items():
            if isinstance(svc, dict) and svc.get("image"):
                check_ref(f"{rel}: job {job} serviço {sname}", str(svc["image"]), lock, errors)
        c = (spec or {}).get("container")
        if c:
            check_ref(f"{rel}: job {job} container", str(c.get("image") if isinstance(c, dict) else c), lock, errors)


# flags de `docker run|create` que consomem o PRÓXIMO argumento (sem `=`); flag desconhecida é tratada como booleana (se errar, falha FECHADO: "sem digest")
VALUE_FLAGS = {
    "-e", "--env", "--env-file", "-p", "--publish", "-v", "--volume", "--name", "-l", "--label", "--label-file", "--network", "--net", "--tmpfs", "-u", "--user", "-w", "--workdir",
    "--entrypoint", "--mount", "--add-host", "-m", "--memory", "-c", "--cpus", "--cpu-shares", "--restart", "--cap-add", "--cap-drop", "--security-opt", "--pids-limit", "-h", "--hostname",
    "--platform", "--pull", "--log-driver", "--log-opt", "--device", "--group-add", "--ulimit", "--health-cmd", "--health-interval", "--health-retries", "--health-timeout", "--health-start-period",
    "--dns", "--ip", "--shm-size", "--stop-signal", "--stop-timeout", "--user-ns", "--pid", "--ipc", "--cgroupns", "--runtime", "--sysctl", "--annotation", "--expose", "--link", "--volumes-from",
}
DOCKER_CMD_RE = re.compile(r"\bdocker\s+(?:container\s+|image\s+)?(run|create|pull)\b")


def logical_lines(text: str):
    """(nº da primeira linha, linha lógica): junta as linhas continuadas com `\\` (shell/Makefile)."""
    buf, start = "", 0
    for n, raw in enumerate(text.splitlines(), 1):
        if not buf:
            start = n
        if raw.rstrip().endswith("\\"):
            buf += raw.rstrip()[:-1] + " "
            continue
        yield start, buf + raw
        buf = ""
    if buf:
        yield start, buf


def docker_image_refs(text: str):
    """(linha, ref | None) para cada docker run/create/pull e `uses: docker://`; None = imagem não identificável (falha fechado)."""
    built = {t for _, ln in logical_lines(text) for t in re.findall(r"\bdocker\s+(?:buildx\s+)?build\b.*?(?:-t|--tag)[= ]+(\S+)", ln)}   # tag construída neste mesmo arquivo: não é do registro
    for n, line in logical_lines(text):
        line = re.sub(r"\s#.*$", "", line)
        if line.lstrip().startswith("#"):
            continue
        for m in re.finditer(r"\buses:\s*docker://(\S+)", line):
            yield n, m.group(1).strip("'\"")
        for m in DOCKER_CMD_RE.finditer(line):
            toks = line[m.end():].split()
            images: list[str] = []
            i = 0
            while i < len(toks):
                t = toks[i]
                if t.startswith("-"):
                    i += 2 if (t in VALUE_FLAGS and "=" not in t) else 1
                    continue
                if t in {"|", "||", "&&", ";"}:
                    break
                images.append(t.strip("'\"").rstrip(");|&`").strip("'\""))
                if m.group(1) != "pull":      # run/create: o primeiro argumento é a imagem, o resto é o comando; pull aceita VÁRIAS imagens
                    break
                i += 1
            if not images:
                yield n, None
            for image in images:
                if image not in built:
                    yield n, (image or None)


def text_problems(text: str, lock: dict[str, str], skip_image_keys: bool, lock_only: bool = False):
    """{linha: mensagem}: imagem de comando docker sem digest/fora do lock/digest errado, e <repo>:<tag> do lock sem `@sha256:` ou com digest diferente."""
    out: dict[int, str] = {}
    if not lock_only:
        for n, ref in docker_image_refs(text):
            tmp: list[str] = []
            if ref is None:
                tmp.append("docker run/create/pull sem imagem identificável (ajuste o comando ou VALUE_FLAGS em scripts/images.py)")
            else:
                check_ref("", ref, lock, tmp)
            if tmp:
                out.setdefault(n, tmp[0].lstrip(": "))
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#") or (skip_image_keys and re.match(r"^\s*(-\s*)?image:", line)):
            continue
        for base, want in lock.items():
            for m in re.finditer(r"(?<![\w./-])" + re.escape(base) + r"(?![\w.-])", line):
                dm = re.match(r"@(sha256:[0-9a-f]{64})", line[m.end():])
                if not dm:
                    out.setdefault(n, f"{base} sem digest")
                elif dm.group(1) != want:
                    out.setdefault(n, f"digest de {base} difere do lock")
    return out


def check(root: Path) -> list[str]:
    lock = read_lock(root)
    errors = [f"{LOCK_REL}: {ref} está PENDING (digest não resolvido)" for ref, d in lock.items() if d == "PENDING"]
    for p in walk(root):
        rel = str(p.relative_to(root))
        if is_dockerfile(p):
            check_dockerfile(p, rel, lock, errors)
        elif is_compose(p):
            check_compose(p, rel, lock, errors)
        elif is_text_target(p, root):  # Makefile, scripts, CI: `docker run`, services:, etc.
            if is_workflow(p):
                check_workflow(p, rel, lock, errors)
            errors += [f"{rel}:{n}: {msg}" for n, msg in sorted(text_problems(p.read_text(), lock, skip_image_keys=is_workflow(p)).items())]
    return errors


def resolve(ref: str) -> str | None:
    """Digest do índice (o que `docker pull` resolve para qualquer arquitetura). None se não resolver."""
    try:
        out = subprocess.run(["docker", "buildx", "imagetools", "inspect", ref], capture_output=True, text=True, timeout=90).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"^Digest:\s+(sha256:[0-9a-f]{64})\s*$", out, re.M)
    return m.group(1) if m else None


def update(root: Path, write: bool) -> int:
    lock = read_lock(root)
    new: dict[str, str] = {}
    for ref, old in lock.items():
        d = resolve(ref)
        if d is None:
            print(f"NÃO RESOLVIDO  {ref} (mantido {old}; sem rede, imagem privada ou tag inexistente)")
            new[ref] = old
        else:
            print(f"{'igual' if d == old else 'MUDOU':14} {ref} {old} -> {d}")
            new[ref] = d
    if not write:
        print("dry-run: nada gravado (use --write)")
        return 0
    changes: dict[Path, str] = {}
    for p in walk(root):
        if not is_text_target(p, root):
            continue
        txt = orig = p.read_bytes().decode("utf-8")
        for ref, d in new.items():
            if d != "PENDING":
                txt = re.sub(r"(?<![\w./-])" + re.escape(ref) + r"(@sha256:[0-9a-f]{64})?(?![\w.@-])", f"{ref}@{d}", txt)
        if txt != orig:
            changes[p] = txt
    out = []
    for line in (root / LOCK_REL).read_bytes().decode("utf-8").splitlines():
        parts = line.split()
        out.append(f"{parts[0]} {new[parts[0]]}" if len(parts) == 2 and parts[0] in new and not line.lstrip().startswith("#") else line)
    changes[root / LOCK_REL] = "\n".join(out) + "\n"
    replace_all(changes)
    for p in changes:
        print(f"regravado {p.relative_to(root)}")
    return 0


def replace_all(changes: dict[Path, str]) -> None:
    """Tudo ou nada na parte que pode falhar (disco cheio, permissão): grava TODOS os temporários (mesmo diretório, mesmo modo) e só então troca cada original por os.replace (atômico)."""
    staged: list[tuple[str, Path]] = []
    try:
        for p, txt in changes.items():
            fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
            staged.append((tmp, p))
            with os.fdopen(fd, "wb") as f:
                f.write(txt.encode("utf-8"))
            shutil.copymode(p, tmp)
    except BaseException:
        for tmp, _ in staged:
            Path(tmp).unlink(missing_ok=True)
        raise
    originals = {p: p.read_bytes() for _, p in staged}
    done: list[Path] = []
    try:
        for tmp, p in staged:
            os.replace(tmp, p)
            done.append(p)
    except BaseException:                               # troca falhou no meio: devolve os já trocados e apaga os temporários que sobraram
        for p in done:
            fd, back = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".bak")
            with os.fdopen(fd, "wb") as f:
                f.write(originals[p])
            shutil.copymode(p, back)
            os.replace(back, p)
        for tmp, _ in staged:
            Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "update"])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "update":
        return update(a.root, a.write)
    errors = check(a.root)
    for e in errors:
        print(f"FALHA {e}", file=sys.stderr)
    print(f"images check: {'FAIL (' + str(len(errors)) + ')' if errors else 'OK'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
