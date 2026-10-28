"""Ed25519 signing of job envelopes. The Edge pins the public key locally and verifies signature, expiry, nonce and
edge/tenant binding before executing anything (contracts/job-envelope.schema.json)."""
from __future__ import annotations

import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical(envelope: dict) -> bytes:
    body = {k: v for k, v in envelope.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_private(seed_b64: str) -> Ed25519PrivateKey:
    seed = base64.b64decode(seed_b64, validate=True)
    if len(seed) != 32:
        raise ValueError("JOB_SIGNING_KEY must be a base64-encoded 32-byte Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(seed)


def sign(key: Ed25519PrivateKey, envelope: dict) -> str:
    return base64.b64encode(key.sign(canonical(envelope))).decode()


def verify(public_b64: str, envelope: dict) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64, validate=True)).verify(
            base64.b64decode(envelope.get("signature", ""), validate=True), canonical(envelope)
        )
        return True
    except (InvalidSignature, ValueError):
        return False
