"""Batimento de vida dos workers (relay, consumer): o laço toca um arquivo a cada iteração BEM-SUCEDIDA; o healthcheck do contêiner lê a idade.

Sem `HEARTBEAT_FILE` não faz nada (testes e desenvolvimento). Falha ao tocar nunca derruba o worker.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def beat() -> None:
    p = os.environ.get("HEARTBEAT_FILE")
    if not p:
        return
    try:
        Path(p).touch()
    except OSError:
        pass


def age_s(path: str, now: float | None = None) -> float:
    """Idade do arquivo em segundos; arquivo ausente conta como infinita."""
    try:
        return (now if now is not None else time.time()) - os.path.getmtime(path)
    except OSError:
        return float("inf")


def main(argv: list[str]) -> int:
    """`python -m app.core.heartbeat <arquivo> <idade-máxima-s>` -> 0 saudável, 1 não."""
    path, limit = argv[1], float(argv[2])
    return 0 if age_s(path) <= limit else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
