"""
Authenticated encryption at rest using Fernet and OS keyring.
Strictly local-first. Never logs plaintext. Never silences decryption failures.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

KEYRING_SERVICE_NAME = "go81_agent"
KEYRING_USERNAME = "agent_master_key"
ENV_KEY_VAR = "GO81_ENCRYPTION_KEY"
FALLBACK_ENV_KEY_VAR = None
FALLBACK_KEYRING_SERVICE_NAME = None


# ============================================================================
# Exceptions
# ============================================================================

class CryptoError(Exception):
    """Base exception for cryptographic errors."""
    pass


class MissingKeyError(CryptoError):
    """Raised when no encryption key can be located."""
    pass


class DecryptionError(CryptoError):
    """Raised when decryption fails due to invalid key, corruption, or tampering."""
    pass


# ============================================================================
# Key Provider Interface & Implementations
# ============================================================================

class KeyProvider(ABC):
    """Abstract interface for retrieving and persisting encryption master keys."""

    @abstractmethod
    def get_key(self) -> bytes:
        """Retrieve the encryption key bytes."""
        pass

    @abstractmethod
    def set_key(self, key: bytes) -> None:
        """Persist the encryption key (if supported by provider)."""
        pass


class KeyringKeyProvider(KeyProvider):
    """
    Retrieves key from the host operating system credential vault via `keyring`
    (Windows Credential Manager, macOS Keychain, Linux SecretService).
    Checks Go 81 keyring service.
    """

    def __init__(
        self,
        service_name: str = KEYRING_SERVICE_NAME,
        username: str = KEYRING_USERNAME,
        fallback_service: Optional[str] = FALLBACK_KEYRING_SERVICE_NAME,
    ):
        self.service_name = service_name
        self.username = username
        self.fallback_service = fallback_service

    def get_key(self) -> bytes:
        try:
            import keyring
            stored = keyring.get_password(self.service_name, self.username)
            if not stored and self.fallback_service:
                stored = keyring.get_password(self.fallback_service, self.username)
            if not stored:
                raise MissingKeyError(
                    f"No key found in OS keyring for service='{self.service_name}', user='{self.username}'."
                )
            return stored.encode("utf-8")
        except MissingKeyError:
            raise
        except Exception as e:
            raise MissingKeyError(f"Failed to access OS keyring: {e}") from e

    def set_key(self, key: bytes) -> None:
        try:
            import keyring
            keyring.set_password(self.service_name, self.username, key.decode("utf-8"))
        except Exception as e:
            raise CryptoError(f"Failed to store key in OS keyring: {e}") from e


class EnvKeyProvider(KeyProvider):
    """Retrieves key from environment variable (GO81_ENCRYPTION_KEY)."""

    def __init__(self, env_var: str = ENV_KEY_VAR, fallback_var: Optional[str] = FALLBACK_ENV_KEY_VAR):
        self.env_var = env_var
        self.fallback_var = fallback_var

    def get_key(self) -> bytes:
        val = os.environ.get(self.env_var) or (os.environ.get(self.fallback_var) if self.fallback_var else None)
        if not val or not val.strip():
            raise MissingKeyError(
                f"Environment variable '{self.env_var}' is not set."
            )
        return val.strip().encode("utf-8")

    def set_key(self, key: bytes) -> None:
        os.environ[self.env_var] = key.decode("utf-8")


class TestKeyProvider(KeyProvider):
    """
    Test-only in-memory key provider.
    Guaranteed not to interact with OS keyring or disk.
    """
    __test__ = False

    def __init__(self, key: Optional[Union[bytes, str]] = None):
        if key is None:
            self._key = Fernet.generate_key()
        elif isinstance(key, str):
            self._key = key.encode("utf-8")
        else:
            self._key = key

    def get_key(self) -> bytes:
        return self._key

    def set_key(self, key: bytes) -> None:
        self._key = key


class CompositeKeyProvider(KeyProvider):
    """
    Tries Keyring first, then environment variable.
    Fails safely if neither is available.
    Never silently creates a random replacement key when accessing an existing vault.
    """

    def __init__(
        self,
        keyring_provider: Optional[KeyringKeyProvider] = None,
        env_provider: Optional[EnvKeyProvider] = None,
    ):
        self.keyring = keyring_provider or KeyringKeyProvider()
        self.env = env_provider or EnvKeyProvider()

    def get_key(self) -> bytes:
        # Try OS keyring
        try:
            return self.keyring.get_key()
        except MissingKeyError:
            pass

        # Try environment variable
        try:
            return self.env.get_key()
        except MissingKeyError:
            pass

        raise MissingKeyError(
            "Master encryption key not found. Checked OS Keyring and "
            f"environment variable '{self.env.env_var}'. "
            f"Please initialize a key or set {self.env.env_var}."
        )

    def set_key(self, key: bytes) -> None:
        try:
            self.keyring.set_key(key)
        except Exception:
            self.env.set_key(key)


# ============================================================================
# Encryption Service
# ============================================================================

class EncryptionService:
    """
    Authenticated JSON encryption using Fernet.
    All sensitive payloads are encrypted into base64 ciphertext tokens before writing to disk.
    Unencrypted metadata (UUIDs, timestamps, categories) are stored in SQLite columns for indexing.
    """

    def __init__(self, key_provider: KeyProvider):
        self.key_provider = key_provider
        self._cipher: Optional[Fernet] = None

    @classmethod
    def generate_key(cls) -> bytes:
        """Generates a new secure Fernet key (32 url-safe base64-encoded bytes)."""
        return Fernet.generate_key()

    @property
    def cipher(self) -> Fernet:
        """Lazily initialize Fernet cipher to ensure key is verified at runtime."""
        if self._cipher is None:
            key = self.key_provider.get_key()
            try:
                self._cipher = Fernet(key)
            except Exception as e:
                raise CryptoError(f"Invalid Fernet key format: {e}") from e
        return self._cipher

    def encrypt_json(self, payload: Dict[str, Any]) -> str:
        """
        Serializes dict to compact JSON and encrypts with Fernet.
        Returns URL-safe base64 ciphertext string.
        """
        try:
            raw_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            token = self.cipher.encrypt(raw_bytes)
            return token.decode("ascii")
        except Exception as e:
            if isinstance(e, CryptoError):
                raise
            raise CryptoError(f"Encryption failed: {e}") from e

    def decrypt_json(self, token: str) -> Dict[str, Any]:
        """
        Decrypts Fernet ciphertext string and deserializes JSON.
        Raises DecryptionError if token is invalid, corrupted, or signed with a different key.
        Never logs plaintext content.
        """
        try:
            token_bytes = token.encode("ascii")
            decrypted_bytes = self.cipher.decrypt(token_bytes)
            return json.loads(decrypted_bytes.decode("utf-8"))
        except InvalidToken as e:
            # Critical hackathon requirement: Fail safely on wrong key or tampered ciphertext
            raise DecryptionError(
                "Decryption failed: invalid key or tampered ciphertext token."
            ) from e
        except Exception as e:
            if isinstance(e, CryptoError):
                raise
            raise DecryptionError(f"Decryption failed: {e}") from e
