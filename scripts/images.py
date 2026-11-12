#!/usr/bin/env python3
"""Imagens por digest: verificação (offline) e atualização (precisa de rede).

  scripts/images.py check [--root DIR]        falha (rc=1) se algum FROM/image:/`docker run` ficar sem digest, com digest
                                              diferente de infra/images.lock, fora do lock ou com digest PENDING
  scripts/images.py update [--write]          resolve o digest atual de cada <repo>:<tag> do lock (docker buildx imagetools)
                                              e mostra o que mudaria; com --write regrava o lock e todos os arquivos

Regras do `check`:
  * Dockerfile: todo `FROM` externo precisa de `@sha256:` (stage anterior e `scratch` são isentos; `$VAR` é recusado).
  * Compose: todo `image:` precisa de `@sha256:`, exceto serviço com `build:` (a tag é do build local).
  * Qualquer outra ocorrência textual de um <repo>:<tag> do lock (Makefile, scripts, CI) precisa do digest do lock.
  * Toda imagem externa precisa estar no lock; PENDING no lock = falha (lista explícita do que falta resolver).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
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
    for n, raw in enumerate(p.read_text().splitlines(), 1):
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
            if "build" not in svc:
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


def text_problems(text: str, lock: dict[str, str], skip_image_keys: bool):
    """(linha, mensagem) para cada <repo>:<tag> do lock que aparece sem `@sha256:` ou com digest diferente do lock."""
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#") or (skip_image_keys and re.match(r"^\s*(-\s*)?image:", line)):
            continue
        for base, want in lock.items():
            for m in re.finditer(r"(?<![\w./-])" + re.escape(base) + r"(?![\w.-])", line):
                rest = line[m.end():]
                dm = re.match(r"@(sha256:[0-9a-f]{64})", rest)
                if not dm:
                    yield n, f"{base} sem digest"
                elif dm.group(1) != want:
                    yield n, f"digest de {base} difere do lock"


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
            errors += [f"{rel}:{n}: {msg}" for n, msg in text_problems(p.read_text(), lock, skip_image_keys=is_workflow(p))]
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
    for p in walk(root):
        if not is_text_target(p, root):
            continue
        txt = orig = p.read_text()
        for ref, d in new.items():
            if d != "PENDING":
                txt = re.sub(r"(?<![\w./-])" + re.escape(ref) + r"(@sha256:[0-9a-f]{64})?(?![\w.@-])", f"{ref}@{d}", txt)
        if txt != orig:
            p.write_text(txt)
            print(f"regravado {p.relative_to(root)}")
    lines = (root / LOCK_REL).read_text().splitlines()
    out = []
    for line in lines:
        parts = line.split()
        out.append(f"{parts[0]} {new[parts[0]]}" if len(parts) == 2 and parts[0] in new and not line.lstrip().startswith("#") else line)
    (root / LOCK_REL).write_text("\n".join(out) + "\n")
    return 0


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
