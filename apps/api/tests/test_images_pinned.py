"""Imagens por digest (scripts/images.py): o repositório está fixado e o verificador pega cada forma de regressão."""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("images_tool", REPO / "scripts" / "images.py")
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)

D1 = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64


def tree(tmp_path, files: dict[str, str], lock: str | None = None) -> Path:
    (tmp_path / "infra").mkdir(parents=True, exist_ok=True)
    (tmp_path / "infra" / "images.lock").write_text(lock if lock is not None else f"alpine:3.20 {D1}\npostgres:17-alpine {D1}\n")
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return tmp_path


def test_the_repository_is_fully_pinned():
    assert images.check(REPO) == []


def test_a_pinned_dockerfile_with_stages_passes(tmp_path):
    root = tree(tmp_path, {"app/Dockerfile": f"FROM alpine:3.20@{D1} AS build\nRUN true\nFROM build AS final\nFROM scratch\n"})
    assert images.check(root) == []


def test_dockerfile_without_digest_or_with_variable_or_other_digest_fails(tmp_path):
    root = tree(tmp_path, {"a/Dockerfile": "FROM alpine:3.20\n", "b/Dockerfile": "ARG B=x\nFROM ${B}\n", "c/Dockerfile": f"FROM alpine:3.20@{D2}\n"})
    errs = images.check(root)
    assert any("a/Dockerfile:1" in e and "sem digest" in e for e in errs)
    assert any("b/Dockerfile:2" in e and "variável" in e for e in errs)
    assert any("c/Dockerfile:1" in e and "difere do lock" in e for e in errs)


def test_image_not_in_the_lock_fails_even_with_a_digest(tmp_path):
    assert any("não está em" in e for e in images.check(tree(tmp_path, {"Dockerfile": f"FROM busybox:1@{D1}\n"})))


def test_compose_requires_digest_except_for_locally_built_services(tmp_path):
    ok = f"services:\n  db:\n    image: postgres:17-alpine@{D1}\n  app:\n    build: .\n    image: app:local\n"
    assert images.check(tree(tmp_path, {"infra/compose/compose.yaml": ok})) == []
    bad = "services:\n  db:\n    image: postgres:17-alpine\n  x: {command: [a]}\n"
    errs = images.check(tree(tmp_path / "bad", {"infra/compose/compose.yaml": bad}))
    assert any("serviço db" in e and "sem digest" in e for e in errs)
    assert any("serviço x sem image nem build" in e for e in errs)


def test_bare_reference_in_scripts_makefile_and_ci_fails(tmp_path):
    files = {
        "scripts/t.sh": "docker run -d postgres:17-alpine\n# docker run postgres:17-alpine (comentário não conta)\n",
        "Makefile": f"x:\n\tdocker run alpine:3.20@{D2} true\n",
        ".github/workflows/ci.yml": "jobs:\n  j:\n    services:\n      pg:\n        image: postgres:17-alpine\n    steps:\n      - run: docker run alpine:3.20 true\n",
    }
    errs = images.check(tree(tmp_path, files))
    assert any("scripts/t.sh:1" in e for e in errs) and not any("scripts/t.sh:2" in e for e in errs)
    assert any("Makefile:2" in e and "difere do lock" in e for e in errs)
    assert any("ci.yml" in e and "serviço pg" in e for e in errs)
    assert any("ci.yml:7" in e for e in errs)


def test_port_like_tags_are_not_confused_with_images(tmp_path):
    root = tree(tmp_path, {"scripts/t.sh": "psql postgres://h:5432/postgres:17-alpinex\necho postgres:5432\n"})
    assert images.check(root) == []


def test_pending_entry_fails_explicitly(tmp_path):
    root = tree(tmp_path, {"Dockerfile": f"FROM alpine:3.20@{D1}\n"}, lock=f"alpine:3.20 {D1}\nnats:2.11-alpine PENDING\n")
    assert images.check(root) == [f"{images.LOCK_REL}: nats:2.11-alpine está PENDING (digest não resolvido)"]


def test_malformed_lock_is_refused(tmp_path):
    import pytest

    for bad in ("alpine:3.20 sha256:short\n", f"alpine {D1}\n", f"alpine:3.20 {D1}\nalpine:3.20 {D1}\n"):
        with pytest.raises(SystemExit):
            images.read_lock(tree(tmp_path, {}, lock=bad))


def test_update_rewrites_lock_and_files_and_keeps_unresolved_as_is(tmp_path, monkeypatch):
    root = tree(tmp_path, {"Dockerfile": f"FROM alpine:3.20@{D1}\n", "scripts/t.sh": "docker run postgres:17-alpine\n"})
    monkeypatch.setattr(images, "resolve", lambda ref: D2 if ref == "alpine:3.20" else None)   # postgres: sem rede
    assert images.update(root, write=False) == 0
    assert D2 not in (root / "Dockerfile").read_text()                                          # dry-run não grava
    assert images.update(root, write=True) == 0
    assert (root / "Dockerfile").read_text() == f"FROM alpine:3.20@{D2}\n"
    lock = images.read_lock(root)
    assert lock == {"alpine:3.20": D2, "postgres:17-alpine": D1}                                # não resolvido: mantido, nunca inventado
