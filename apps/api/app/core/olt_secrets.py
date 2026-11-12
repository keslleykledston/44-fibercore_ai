"""OLT credentials typed on the screen, sealed in the browser for the Edge (ADR-0045): the PURE rules. No I/O, and no way to OPEN a blob: only the Edge's private key can, and it never leaves the Edge.

Contract (ADR-0045, "Criptografia"):
* Edge key = ECDH P-256 uncompressed point (65 bytes), base64url without padding. `key_id` = first 16 hex of SHA-256(point). Fingerprint (for people) = first 32 hex of SHA-256(point), 8 groups of 4 joined by '-'.
* Blob = 0x01 || ephemeral_pub(65) || nonce(12) || ciphertext||tag, base64url. AAD =
  "fibercore-seal-v1\\n{tenant_id}\\n{edge_id}\\n{olt_name}\\n{kind}\\n{delivery_id}\\n{key_id}\\n{expires_at_unix}".
* Delivery signature = Ed25519 (the same signing key as the job envelopes) over
  "fibercore-delivery-v1\\n{AAD}\\n{lowercase hex SHA-256 of the DECODED blob bytes}", sent as base64url without padding.
The API validates FORMAT only (it cannot authenticate a blob); the Edge authenticates by opening it.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

CREDENTIAL_KINDS = ("ssh_login", "snmp_community")   # ADR-0045: permission fleet:secrets, flag fleet_secrets
CONNECTION_KIND = "olt_connection"                    # ADR-0046 D4: permission fleet:provision, flag fleet_provision; same channel, same sealing, same AAD (with this kind), same states and retention
KINDS = (*CREDENTIAL_KINDS, CONNECTION_KIND)
KIND_GATE = {"ssh_login": ("fleet:secrets", "fleet_secrets"), "snmp_community": ("fleet:secrets", "fleet_secrets"), CONNECTION_KIND: ("fleet:provision", "fleet_provision")}
SEAL_PREFIX = "fibercore-seal-v1"
DELIVERY_PREFIX = "fibercore-delivery-v1"
BLOB_VERSION = 0x01
POINT_LEN = 65
NONCE_LEN = 12
TAG_LEN = 16
MIN_BLOB_BYTES = 1 + POINT_LEN + NONCE_LEN + TAG_LEN + 1
# ADR: "Limite do blob: 2048 bytes". The blob travels as base64url text, so the API reads the limit on the ENCODED form (2048 characters = at most 1536 decoded bytes): the stricter of the two readings.
# A real blob is ~100 to ~600 bytes (user <= 64, password <= 128, community <= 64), so nothing legitimate is refused.
MAX_BLOB_CHARS = 2048
MAX_PENDING_PER_OLT = 5
MAX_ATTEMPTS = 3
LEASE_SECONDS = 300
MAX_WINDOW_SECONDS = 3600
# the failure codes an Edge may report (ADR-0045 + ADR-0046 D5); `awaiting_local_trust` is NOT one: it rides on an `applied` result of an `olt_connection` (APPLIED_CODES)
RESULT_CODES = ("bad_key_id", "expired", "aad_mismatch", "bad_signature", "decrypt_failed", "invalid_payload", "stale", "target_not_configured", "write_failed", "state_unreadable",
                "protocol_not_supported", "vendor_not_supported", "vendor_not_allowed", "address_not_allowed", "port_not_allowed", "too_many_olts", "legacy_not_allowed", "name_conflict",
                "managed_olts_disabled")
APPLIED_CODES = ("awaiting_local_trust",)
# What a person reads for each failure code (pt-BR): the web shows these; the API only ever returns the code.
CODE_PT = {
    "bad_key_id": "A chave do Edge mudou desde a digitação. Confirme a nova impressão digital e envie de novo.",
    "expired": "O prazo da entrega venceu antes de o Edge aplicar. Envie de novo.",
    "aad_mismatch": "O Edge recusou: a entrega não é para esta OLT ou este Edge.",
    "bad_signature": "O Edge recusou: assinatura da nuvem inválida (confira a chave pública do Edge).",
    "decrypt_failed": "O Edge não conseguiu abrir a entrega (chave diferente). Confirme a impressão digital e envie de novo.",
    "invalid_payload": "O Edge recusou o conteúdo (formato ou tamanho dos campos).",
    "stale": "O Edge já aplicou uma entrega mais nova deste tipo.",
    "target_not_configured": "Esta OLT não aceita credencial remota: o administrador do Edge precisa habilitar credentials_file para ela.",
    "write_failed": "O Edge não conseguiu gravar o arquivo de credenciais (permissão ou disco).",
    "state_unreadable": "O Edge não conseguiu ler o próprio registro de entregas aplicadas.",
    "lease_exhausted": "O Edge não respondeu a tempo em várias tentativas.",
    # ADR-0046 D5 (the Edge's answer about the OLT's connection)
    "awaiting_local_trust": ("Conexão aplicada no Edge, mas ele só conecta depois da confirmação local: no servidor do Edge rode "
                             "fibercore-edge managed-trust <nome da OLT> e redigite a impressão digital do host."),
    "protocol_not_supported": "O Edge recusou: este protocolo não é suportado (Telnet é só cadastro por enquanto).",
    "vendor_not_supported": "O Edge ainda não opera este fabricante (hoje só Huawei e ZTE). O cadastro continua como inventário.",
    "vendor_not_allowed": "A política local do Edge não permite este fabricante (allowed_vendors).",
    "address_not_allowed": "O endereço está fora das redes liberadas na política local do Edge (allowed_cidrs) ou é um endereço proibido.",
    "port_not_allowed": "A porta não está liberada na política local do Edge (allowed_ports).",
    "too_many_olts": "O Edge atingiu o máximo de OLTs gerenciadas pela nuvem (max_olts).",
    "legacy_not_allowed": "A política local do Edge não permite SSH legado (allow_legacy_ssh).",
    "name_conflict": "Já existe no Edge uma OLT estática com este nome: a estática manda e a nuvem não a sobrescreve.",
    "managed_olts_disabled": "Este Edge não aceita OLT gerenciada pela nuvem: quem administra o Edge precisa criar a seção managed_olts no config.json.",
    # cancellations made by the Cloud itself (never an Edge answer)
    "connection_changed": "A conexão da OLT mudou depois do envio: a entrega foi cancelada e o conteúdo apagado. Envie de novo.",
    "protocol_changed": "A OLT passou a Telnet (só cadastro): as entregas pendentes foram canceladas e o conteúdo apagado.",
}

_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Strict: base64url alphabet only, no padding, canonical (re-encoding gives back the same text). Raises ValueError otherwise."""
    if not text or not _B64URL.match(text) or len(text) % 4 == 1:
        raise ValueError("not base64url")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not base64url") from exc
    if b64url_encode(raw) != text:
        raise ValueError("not canonical base64url")
    return raw


def _check_point(raw: bytes) -> None:
    if len(raw) != POINT_LEN or raw[0] != 0x04:
        raise ValueError("not an uncompressed P-256 point")
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)   # also proves the point is ON the curve
    except ValueError as exc:
        raise ValueError("not a point of P-256") from exc


def parse_public_key(text: str) -> bytes:
    """The Edge's public key (base64url of the 65-byte uncompressed point). Raises ValueError, never echoing the value."""
    raw = b64url_decode(text)
    _check_point(raw)
    return raw


def key_id(point: bytes) -> str:
    return hashlib.sha256(point).hexdigest()[:16]


def fingerprint(point: bytes) -> str:
    h = hashlib.sha256(point).hexdigest()[:32]
    return "-".join(h[i:i + 4] for i in range(0, 32, 4))


def normalize_fingerprint(text: str) -> str | None:
    """What a person typed, reduced to 32 lower-case hex; None when it is not that (spaces, dashes and case are forgiven)."""
    h = re.sub(r"[\s-]", "", text).lower()
    return h if re.fullmatch(r"[0-9a-f]{32}", h) else None


def fingerprint_matches(typed: str, point: bytes) -> bool:
    h = normalize_fingerprint(typed)
    return h is not None and hmac.compare_digest(h, hashlib.sha256(point).hexdigest()[:32])


def parse_blob(text: str) -> bytes:
    """Format check of a sealed blob (version byte, a real P-256 ephemeral point, room for nonce and tag, size limit). Raises ValueError, never echoing the value."""
    if len(text) > MAX_BLOB_CHARS:
        raise ValueError("blob too large")
    raw = b64url_decode(text)
    if len(raw) < MIN_BLOB_BYTES or raw[0] != BLOB_VERSION:
        raise ValueError("not a sealed blob")
    _check_point(raw[1:1 + POINT_LEN])
    return raw


def aad(*, tenant_id: UUID | str, edge_id: UUID | str, olt_name: str, kind: str, delivery_id: UUID | str, key_id_: str, expires_at_unix: int) -> str:
    return "\n".join((SEAL_PREFIX, str(tenant_id).lower(), str(edge_id).lower(), olt_name, kind, str(delivery_id).lower(), key_id_, str(int(expires_at_unix))))


def delivery_message(aad_text: str, blob: bytes) -> bytes:
    return f"{DELIVERY_PREFIX}\n{aad_text}\n{hashlib.sha256(blob).hexdigest()}".encode()


def sign_delivery(key: Ed25519PrivateKey, aad_text: str, blob: bytes) -> str:
    return b64url_encode(key.sign(delivery_message(aad_text, blob)))
