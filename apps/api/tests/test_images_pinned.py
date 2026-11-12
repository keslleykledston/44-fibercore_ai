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


def test_unknown_images_in_docker_commands_are_caught_even_outside_the_lock(tmp_path):
    files = {
        "scripts/a.sh": "docker run --rm -p 1:1 -e A=b ghcr.io/vendor/tool:latest --flag\n",
        "scripts/b.sh": f"X=$(docker run -d \\\n  --name n -v /a:/b \\\n  busybox:1@{D1} sleep 1)\n",
        "scripts/c.sh": "docker pull redis:7\ndocker container create --rm redis:7@sha256:x\n",
        "scripts/d.sh": 'docker run --rm "$IMG" true\ndocker run --rm\n',
        ".github/workflows/ci.yml": "jobs:\n  j:\n    steps:\n      - run: docker run --rm vendor/scan:1 image x\n      - uses: docker://vendor/act:2\n",
        "Makefile": "t:\n\tdocker run -d --label k=v $(IMG)\n",
    }
    errs = "\n".join(images.check(tree(tmp_path, files)))
    assert "scripts/a.sh:1: imagem sem digest: ghcr.io/vendor/tool:latest" in errs
    assert "scripts/b.sh:1: busybox:1 não está em" in errs                      # linha continuada: a imagem está na 3ª linha, o erro aponta o comando
    assert "scripts/c.sh:1: imagem sem digest: redis:7" in errs and "scripts/c.sh:2" in errs
    assert "scripts/d.sh:1: referência com variável" in errs and "scripts/d.sh:2: docker run/create/pull sem imagem identificável" in errs
    assert "ci.yml:4: imagem sem digest: vendor/scan:1" in errs and "ci.yml:5: imagem sem digest: vendor/act:2" in errs
    assert "Makefile:2: referência com variável" in errs


def test_locally_built_tags_comments_and_flag_values_are_not_false_positives(tmp_path):
    files = {
        "scripts/ok.sh": "docker build -f Dockerfile -t app:ci .\ndocker run --rm app:ci true\n# docker run nope:1 (comentário)\ntrap 'x' EXIT   # armed only AFTER docker run succeeded\n"
                         f"docker run -d --name x --label a=b -p 1:1 --tmpfs /t -e K=v alpine:3.20@{D1}\n",
    }
    assert images.check(tree(tmp_path, files)) == []


def test_dockerfile_copy_from_an_external_image_needs_a_digest(tmp_path):
    ok = f"FROM alpine:3.20@{D1} AS build\nFROM alpine:3.20@{D1}\nCOPY --from=build /a /b\nCOPY --from=0 /a /b\nCOPY --chown=1:1 --from=alpine:3.20@{D1} /x /y\n"
    assert images.check(tree(tmp_path, {"Dockerfile": ok})) == []
    bad = f"FROM alpine:3.20@{D1}\nCOPY --from=busybox:1 /a /b\nRUN --mount=type=bind,from=nginx:1,target=/x true\n"
    errs = "\n".join(images.check(tree(tmp_path / "bad", {"Dockerfile": bad})))
    assert "Dockerfile:2: imagem sem digest: busybox:1" in errs and "Dockerfile:3: imagem sem digest: nginx:1" in errs


def test_update_is_all_or_nothing_and_keeps_mode_and_line_endings(tmp_path, monkeypatch):
    import os
    import shutil

    import pytest
    root = tree(tmp_path, {"Dockerfile": f"FROM alpine:3.20@{D1}\r\n", "scripts/t.sh": f"docker run alpine:3.20@{D1} true\n"})
    os.chmod(root / "scripts" / "t.sh", 0o755)  # noqa: S103
    monkeypatch.setattr(images, "resolve", lambda ref: D2)
    real = shutil.copymode
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disco cheio")
        return real(src, dst)

    before = {p: p.read_bytes() for p in (root / "Dockerfile", root / "scripts" / "t.sh", root / "infra" / "images.lock")}
    monkeypatch.setattr(images.shutil, "copymode", flaky)
    with pytest.raises(OSError):
        images.update(root, write=True)
    assert {p: p.read_bytes() for p in before} == before                       # nenhum arquivo mudou
    assert not list(root.rglob("*.tmp"))                                       # sem resíduo
    monkeypatch.setattr(images.shutil, "copymode", real)
    assert images.update(root, write=True) == 0
    assert (root / "Dockerfile").read_bytes() == f"FROM alpine:3.20@{D2}\r\n".encode()   # CRLF preservado
    assert oct((root / "scripts" / "t.sh").stat().st_mode & 0o777) == "0o755"
    assert [e for e in images.check(root) if "PENDING" not in e] == []
