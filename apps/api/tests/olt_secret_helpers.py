"""TEST-ONLY mirror of what the browser and the Edge do in ADR-0045 (ECDH P-256 + HKDF-SHA256 + AES-256-GCM). The product code on the cloud side has NO way to open a blob; only tests do, with a test key."""
from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core import olt_secrets

VECTORS = json.loads((Path(__file__).resolve().parents[3] / "docs" / "addenda" / "olt-secrets" / "vectors.json").read_text(encoding="utf-8"))


def point(priv: ec.EllipticCurvePrivateKey) -> bytes:
    return priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def new_edge_key() -> tuple[ec.EllipticCurvePrivateKey, str]:
    priv = ec.generate_private_key(ec.SECP256R1())
    return priv, olt_secrets.b64url_encode(point(priv))


def scalar_key(hex_scalar: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int(hex_scalar, 16), ec.SECP256R1())


def _aes_key(shared: bytes, key_id: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"fibercore-seal-v1|" + key_id.encode()).derive(shared)


def seal(edge_pub_point: bytes, plaintext: bytes, aad_text: str, key_id: str, *, ephemeral: ec.EllipticCurvePrivateKey | None = None, nonce: bytes | None = None) -> bytes:
    eph = ephemeral or ec.generate_private_key(ec.SECP256R1())
    shared = eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), edge_pub_point))
    nonce = nonce or os.urandom(12)
    return b"\x01" + point(eph) + nonce + AESGCM(_aes_key(shared, key_id)).encrypt(nonce, plaintext, aad_text.encode())


def open_blob(edge_priv: ec.EllipticCurvePrivateKey, blob: bytes, aad_text: str, key_id: str) -> bytes:
    """What the Edge does (step 2): raises cryptography.exceptions.InvalidTag when the key, the AAD or a byte is wrong."""
    assert blob[0] == 1
    eph_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), blob[1:66])
    return AESGCM(_aes_key(edge_priv.exchange(ec.ECDH(), eph_pub), key_id)).decrypt(blob[66:78], blob[78:], aad_text.encode())
