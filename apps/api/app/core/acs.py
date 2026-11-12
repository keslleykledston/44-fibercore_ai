"""Registro de tipos de ACS e validação do `settings` POR TIPO (ADR-0046 D2). Puro: sem I/O, sem banco.

`ACS_KINDS` é um REGISTRO NO CÓDIGO: o banco só confere a forma do `kind` (`acs_connections.kind`, migração 0052), então trocar ou acrescentar um tipo é mudar esta lista e o validador do tipo,
sem migração (a parte do Edge, o adaptador do tipo, é outra mudança). `settings` NUNCA carrega segredo, URL ou host: a URL e o segredo do NBI ficam no `config.json`
do Edge (ADR-0041 D3). Qualquer chave que o tipo não conhece é recusada, e os erros daqui nunca repetem o que foi enviado (nem chave, nem valor): só um código estável."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

ACS_KINDS: tuple[str, ...] = ("genieacs",)

SETTINGS_MAX_BYTES = 2048        # o mesmo limite do CHECK da tabela
NAME_MIN, NAME_MAX = 2, 60       # o mesmo do CHECK da tabela
LABEL_MAX = 80

# Códigos que o Edge pode informar (lista FECHADA): o que ele consegue dizer sobre uma falha do ACS sem texto livre, URL ou id de aparelho.
ACS_ERROR_CODES: tuple[str, ...] = ("unreachable", "timeout", "unauthorized", "unexpected_status", "bad_response", "too_large", "unknown")

# pt-BR para quem lê o código (tela, documentação, log do suporte)
ACS_ERROR_LABELS: dict[str, str] = {
    "unreachable": "O Edge não conseguiu falar com o ACS (rede, DNS ou porta).",
    "timeout": "O ACS demorou demais para responder.",
    "unauthorized": "O ACS recusou o usuário e a senha do NBI configurados no Edge.",
    "unexpected_status": "O ACS respondeu com um erro inesperado.",
    "bad_response": "A resposta do ACS não tem o formato esperado.",
    "too_large": "A resposta do ACS passou do tamanho que o Edge aceita.",
    "unknown": "Falha não classificada no Edge.",
}


class SettingsError(ValueError):
    """`settings` fora do contrato do tipo. `code` é estável e seguro para devolver; a mensagem NUNCA repete o que foi enviado."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _genieacs(settings: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in settings.items():
        if key == "nbi_scheme":
            if value not in ("http", "https"):
                raise SettingsError("settings_bad_value")
            out[key] = value
        else:
            raise SettingsError("settings_unknown_key")   # no secret, URL or host is ever accepted: only the keys the kind knows
    return out


# kind -> validator. Every kind in ACS_KINDS has exactly one (a test ties them together).
SETTINGS_VALIDATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {"genieacs": _genieacs}


def validate_settings(kind: str, settings: Any) -> dict[str, Any]:
    """The normalised `settings` of a kind, or SettingsError. `None` means "none sent" and is `{}`."""
    if kind not in SETTINGS_VALIDATORS:
        raise SettingsError("unknown_kind")
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise SettingsError("settings_bad_value")
    try:
        size = len(json.dumps(settings, ensure_ascii=False, separators=(",", ":")).encode())
    except (TypeError, ValueError) as exc:
        raise SettingsError("settings_bad_value") from exc
    if size > SETTINGS_MAX_BYTES:
        raise SettingsError("settings_too_large")
    return SETTINGS_VALIDATORS[kind](settings)


def check_registry() -> None:
    """Fail closed at import: a kind without validator (or the reverse) is a programming error."""
    if set(ACS_KINDS) != set(SETTINGS_VALIDATORS) or len(set(ACS_KINDS)) != len(ACS_KINDS):
        raise RuntimeError("ACS_KINDS and SETTINGS_VALIDATORS disagree")


check_registry()
