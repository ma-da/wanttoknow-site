from __future__ import annotations

import base64
import json
import os
import re
import secrets
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


ENVELOPE_VERSION = 1
ALGORITHM = "AES-256-GCM"

HKDF_SALT = b"wanttoknow.info-data-encryption-v1"

KEY_ID_RE = re.compile(
    r"^[A-Za-z0-9_-]{1,32}$"
)


class CryptoConfigurationError(RuntimeError):
    """Encryption configuration is missing or invalid."""


class CryptoEnvelopeError(ValueError):
    """Encrypted envelope is malformed or invalid."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(
        value
    ).decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(
            value.encode("ascii")
        )

    except Exception as exc:
        raise CryptoEnvelopeError(
            "Invalid Base64 data."
        ) from exc


def _active_key_id() -> str:
    key_id = os.getenv(
        "WTK_DATA_ACTIVE_KEY_ID",
        "",
    ).strip()

    if not key_id:
        raise CryptoConfigurationError(
            "WTK_DATA_ACTIVE_KEY_ID is not configured."
        )

    if not KEY_ID_RE.fullmatch(key_id):
        raise CryptoConfigurationError(
            "Invalid active encryption key ID."
        )

    return key_id


def _key_environment_name(
    key_id: str,
) -> str:
    if not KEY_ID_RE.fullmatch(key_id):
        raise CryptoConfigurationError(
            "Invalid encryption key ID."
        )

    normalized = (
        key_id
        .upper()
        .replace("-", "_")
    )

    return f"WTK_DATA_KEY_{normalized}"


def _root_key(
    key_id: str,
) -> bytes:
    env_name = _key_environment_name(
        key_id
    )

    encoded = os.getenv(
        env_name,
        "",
    ).strip()

    if not encoded:
        raise CryptoConfigurationError(
            f"{env_name} is not configured."
        )

    try:
        key = base64.b64decode(
            encoded,
            validate=True,
        )

    except Exception as exc:
        raise CryptoConfigurationError(
            f"{env_name} is not valid Base64."
        ) from exc

    if len(key) != 32:
        raise CryptoConfigurationError(
            f"{env_name} must decode to exactly "
            "32 bytes."
        )

    return key


def _derive_key(
    *,
    key_id: str,
    purpose: str,
) -> bytes:
    purpose = purpose.strip()

    if not purpose:
        raise CryptoConfigurationError(
            "Encryption purpose cannot be empty."
        )

    root_key = _root_key(
        key_id
    )

    info = (
        "wanttoknow.info|"
        f"key={key_id}|"
        f"purpose={purpose}"
    ).encode("utf-8")

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=HKDF_SALT,
        info=info,
    ).derive(root_key)


def _aad(
    *,
    version: int,
    algorithm: str,
    key_id: str,
    purpose: str,
) -> bytes:
    metadata = {
        "alg": algorithm,
        "kid": key_id,
        "purpose": purpose,
        "v": version,
    }

    return json.dumps(
        metadata,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def encrypt_bytes(
    data: bytes,
    *,
    purpose: str,
) -> dict[str, Any]:
    if not isinstance(
        data,
        (bytes, bytearray),
    ):
        raise TypeError(
            "encrypt_bytes expects bytes."
        )

    purpose = purpose.strip()

    if not purpose:
        raise ValueError(
            "Encryption purpose cannot be empty."
        )

    key_id = _active_key_id()

    key = _derive_key(
        key_id=key_id,
        purpose=purpose,
    )

    nonce = secrets.token_bytes(12)

    aad = _aad(
        version=ENVELOPE_VERSION,
        algorithm=ALGORITHM,
        key_id=key_id,
        purpose=purpose,
    )

    ciphertext = AESGCM(
        key
    ).encrypt(
        nonce,
        bytes(data),
        aad,
    )

    return {
        "v": ENVELOPE_VERSION,
        "alg": ALGORITHM,
        "kid": key_id,
        "purpose": purpose,
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(
            ciphertext
        ),
    }


def decrypt_bytes(
    envelope: dict[str, Any],
    *,
    expected_purpose: str,
) -> bytes:
    try:
        version = int(
            envelope["v"]
        )

        algorithm = str(
            envelope["alg"]
        )

        key_id = str(
            envelope["kid"]
        )

        purpose = str(
            envelope["purpose"]
        )

        nonce = _b64decode(
            str(
                envelope["nonce"]
            )
        )

        ciphertext = _b64decode(
            str(
                envelope["ciphertext"]
            )
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise CryptoEnvelopeError(
            "Malformed encrypted envelope."
        ) from exc

    if version != ENVELOPE_VERSION:
        raise CryptoEnvelopeError(
            f"Unsupported envelope version: "
            f"{version}"
        )

    if algorithm != ALGORITHM:
        raise CryptoEnvelopeError(
            f"Unsupported algorithm: "
            f"{algorithm}"
        )

    if purpose != expected_purpose:
        raise CryptoEnvelopeError(
            "Encrypted record purpose does "
            "not match expected purpose."
        )

    if len(nonce) != 12:
        raise CryptoEnvelopeError(
            "Invalid AES-GCM nonce length."
        )

    key = _derive_key(
        key_id=key_id,
        purpose=purpose,
    )

    aad = _aad(
        version=version,
        algorithm=algorithm,
        key_id=key_id,
        purpose=purpose,
    )

    try:
        return AESGCM(
            key
        ).decrypt(
            nonce,
            ciphertext,
            aad,
        )

    except Exception as exc:
        raise CryptoEnvelopeError(
            "Encrypted data failed "
            "authentication."
        ) from exc


def encrypt_text(
    text: str,
    *,
    purpose: str,
) -> dict[str, Any]:
    return encrypt_bytes(
        text.encode("utf-8"),
        purpose=purpose,
    )


def decrypt_text(
    envelope: dict[str, Any],
    *,
    expected_purpose: str,
) -> str:
    return decrypt_bytes(
        envelope,
        expected_purpose=(
            expected_purpose
        ),
    ).decode("utf-8")


def encrypt_json(
    value: Any,
    *,
    purpose: str,
) -> dict[str, Any]:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return encrypt_bytes(
        serialized,
        purpose=purpose,
    )


def decrypt_json(
    envelope: dict[str, Any],
    *,
    expected_purpose: str,
) -> Any:
    plaintext = decrypt_bytes(
        envelope,
        expected_purpose=(
            expected_purpose
        ),
    )

    return json.loads(
        plaintext.decode("utf-8")
    )