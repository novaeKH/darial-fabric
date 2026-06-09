import base64
import hashlib
import os
import binascii

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


AES_256_KEY_SIZE_BYTES = 32
AES_GCM_NONCE_SIZE_BYTES = 12


class EncryptionServiceError(RuntimeError):
    """Base exception for encryption/decryption errors."""


class InvalidEncryptionMetadataError(EncryptionServiceError):
    """Raised when encrypted metadata is missing or malformed."""


class DecryptionFailedError(EncryptionServiceError):
    """Raised when encrypted content cannot be decrypted."""


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _b64decode(value: str, field_name: str) -> bytes:
    if not value:
        raise InvalidEncryptionMetadataError(f"Missing encryption metadata: {field_name}")

    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidEncryptionMetadataError(f"Invalid base64 value for {field_name}") from exc


def _get_master_key() -> bytes:
    """
    Derive a stable 256-bit local KEK from settings.MASTER_KEK.

    MVP note:
    - This is acceptable for local/demo mode.
    - In production, this function should be replaced by Vault/KMS/HSM key access.
    """
    master_kek = settings.MASTER_KEK
    if not master_kek:
        raise InvalidEncryptionMetadataError("MASTER_KEK is not configured")

    raw = master_kek.encode("utf-8")
    return hashlib.sha256(raw).digest()


def generate_dek() -> bytes:
    """Generate a random 256-bit data encryption key per file."""
    return os.urandom(AES_256_KEY_SIZE_BYTES)


def encrypt_bytes(plain_data: bytes) -> dict:
    if plain_data is None:
        plain_data = b""

    if not isinstance(plain_data, bytes):
        raise TypeError("plain_data must be bytes")

    dek = generate_dek()
    file_nonce = os.urandom(AES_GCM_NONCE_SIZE_BYTES)

    file_aesgcm = AESGCM(dek)
    encrypted_data = file_aesgcm.encrypt(file_nonce, plain_data, None)

    master_key = _get_master_key()
    dek_nonce = os.urandom(AES_GCM_NONCE_SIZE_BYTES)
    kek_aesgcm = AESGCM(master_key)
    encrypted_dek = kek_aesgcm.encrypt(dek_nonce, dek, None)

    return {
        "encrypted_data": encrypted_data,
        "encrypted_dek": _b64encode(encrypted_dek),
        "dek_nonce": _b64encode(dek_nonce),
        "file_nonce": _b64encode(file_nonce),
        "content_hash": hashlib.sha256(plain_data).hexdigest(),
        "size": len(plain_data),
        "algorithm": "AES-256-GCM",
        "dek_per_file": True,
    }


def decrypt_bytes(
    encrypted_data: bytes,
    encrypted_dek_b64: str,
    dek_nonce_b64: str,
    file_nonce_b64: str,
) -> bytes:
    if not isinstance(encrypted_data, bytes):
        raise InvalidEncryptionMetadataError("encrypted_data must be bytes")

    master_key = _get_master_key()

    encrypted_dek = _b64decode(encrypted_dek_b64, "encrypted_dek")
    dek_nonce = _b64decode(dek_nonce_b64, "dek_nonce")
    file_nonce = _b64decode(file_nonce_b64, "file_nonce")

    if len(dek_nonce) != AES_GCM_NONCE_SIZE_BYTES:
        raise InvalidEncryptionMetadataError("Invalid dek_nonce length")

    if len(file_nonce) != AES_GCM_NONCE_SIZE_BYTES:
        raise InvalidEncryptionMetadataError("Invalid file_nonce length")

    try:
        kek_aesgcm = AESGCM(master_key)
        dek = kek_aesgcm.decrypt(dek_nonce, encrypted_dek, None)

        if len(dek) != AES_256_KEY_SIZE_BYTES:
            raise InvalidEncryptionMetadataError("Invalid DEK length")

        file_aesgcm = AESGCM(dek)
        return file_aesgcm.decrypt(file_nonce, encrypted_data, None)
    except InvalidEncryptionMetadataError:
        raise
    except InvalidTag as exc:
        raise DecryptionFailedError("Decryption failed: authentication tag is invalid") from exc
    except Exception as exc:
        raise DecryptionFailedError("Decryption failed") from exc