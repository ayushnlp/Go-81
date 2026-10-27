"""
Tests for Encryption at Rest, Key Providers, Tamper Detection, and Verifiable Disk Inspection.
Follows hackathon verification rule: inspect raw disk bytes to prove zero plaintext leakage.
"""

import os
import tempfile
import uuid
import pytest
from cryptography.fernet import Fernet
from app.memory.crypto import (
    CryptoError,
    DecryptionError,
    EncryptionService,
    EnvKeyProvider,
    KeyringKeyProvider,
    MissingKeyError,
    TestKeyProvider,
)
from app.memory.database import DatabaseManager
from app.memory.models import TaskCheckpoint, TaskStatus
from app.memory.recovery import TaskRecoveryManager
from app.memory.service import MemoryService


def test_verifiable_encryption_at_rest_raw_file_inspection():
    """
    HACKATHON VERIFICATION REQUIREMENT:
    Never claim SQLite is encrypted simply because the database file exists.
    Inspect the raw bytes of the SQLite database file on disk and verify that plain text
    is completely absent from the file.
    """
    secret_marker = "TOP_SECRET_ODIN_RAVEN_COORDINATES_XYZ999"

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "verifiable_storage.db")
        key_provider = TestKeyProvider()
        crypto = EncryptionService(key_provider)
        db = DatabaseManager(db_path)
        service = MemoryService(db, crypto)

        # Store encrypted episodic event
        service.store_event(
            session_id="session-001",
            event_type="user_message",
            content={"confidential_intel": secret_marker, "author": "Heimdall"},
            source_ref="secure_terminal_source",
        )

        # Also store encrypted task checkpoint with sensitive state
        recovery_mgr = TaskRecoveryManager(db, crypto)
        checkpoint = TaskCheckpoint(
            task_id="task-secure-99",
            workflow_id="wf-confidential",
            status=TaskStatus.RUNNING,
            current_step="execute_secret_mission",
            state_data={"mission_secret": secret_marker},
        )
        recovery_mgr.save_task_checkpoint(checkpoint)

        # Force checkpoint to flush WAL pages into main .db file
        db.checkpoint_wal()

        # Read raw database file from disk
        with open(db_path, "rb") as f:
            raw_disk_bytes = f.read()

        # Verify: Secret text MUST NOT be present in raw bytes of database file
        assert secret_marker.encode("utf-8") not in raw_disk_bytes

        # Verify unencrypted metadata IS visible (deliberately unencrypted columns for querying)
        assert b"secure_terminal_source" in raw_disk_bytes
        assert b"task-secure-99" in raw_disk_bytes


def test_synthetic_secret_persistence_raw_inspection_and_recovery():
    """
    Stores a synthetic secret, closes the database, checks the raw SQLite database bytes
    and WAL for plaintext leakage, reopens the database, and retrieves the original secret.
    """
    synthetic_secret = "SYNTHETIC_ALPHA_OMEGA_SECRET_REST_TEST_777"
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "isolated_secret.db")
        master_key_provider = TestKeyProvider()
        key_bytes = master_key_provider.get_key()

        crypto = EncryptionService(master_key_provider)
        db = DatabaseManager(db_path)
        service = MemoryService(db, crypto)
        recovery = TaskRecoveryManager(db, crypto)

        # Store memory with synthetic secret
        mem = service.store_event(
            session_id="session-synth-001",
            event_type="user_message",
            content={"secret_data": synthetic_secret},
            source_ref="synthetic_audit_ref",
        )

        # Store task checkpoint with synthetic secret
        chk = TaskCheckpoint(
            task_id="task-synth-001",
            workflow_id="wf-synth",
            status=TaskStatus.RUNNING,
            current_step="validate_keys",
            state_data={"checkpoint_secret": synthetic_secret},
        )
        recovery.save_task_checkpoint(chk)

        # Flush WAL and close handles
        db.checkpoint_wal()
        del service
        del recovery
        del db

        # Inspect raw disk bytes of .db
        with open(db_path, "rb") as f:
            raw_db = f.read()

        assert synthetic_secret.encode("utf-8") not in raw_db
        # Deliberately unencrypted metadata is visible
        assert b"synthetic_audit_ref" in raw_db
        assert b"task-synth-001" in raw_db

        # Check WAL if file exists
        wal_path = db_path + "-wal"
        if os.path.exists(wal_path) and os.path.getsize(wal_path) > 0:
            with open(wal_path, "rb") as f:
                raw_wal = f.read()
            assert synthetic_secret.encode("utf-8") not in raw_wal

        # Reopen database with fresh managers using correct key
        reopened_crypto = EncryptionService(TestKeyProvider(key_bytes))
        reopened_db = DatabaseManager(db_path)
        reopened_service = MemoryService(reopened_db, reopened_crypto)
        reopened_recovery = TaskRecoveryManager(reopened_db, reopened_crypto)

        # Retrieve and verify original secret
        recovered_mem = reopened_service.get_memory(mem.id)
        assert recovered_mem is not None
        assert recovered_mem.payload["content"]["secret_data"] == synthetic_secret

        recovered_chk = reopened_recovery.get_task_checkpoint("task-synth-001")
        assert recovered_chk is not None
        assert recovered_chk.state_data["checkpoint_secret"] == synthetic_secret


def test_correct_key_decryption_and_wrong_key_rejection():
    """Validates that right key decrypts, while a different key raises DecryptionError."""
    original_key_provider = TestKeyProvider()
    crypto = EncryptionService(original_key_provider)

    payload = {"message": "Authenticated sovereign memory", "code": 42}
    ciphertext = crypto.encrypt_json(payload)

    # Decrypt with correct key
    decrypted = crypto.decrypt_json(ciphertext)
    assert decrypted == payload

    # Attempt decryption with a completely different key
    wrong_key_provider = TestKeyProvider()  # Generates different random Fernet key
    wrong_crypto = EncryptionService(wrong_key_provider)

    with pytest.raises(DecryptionError) as exc_info:
        wrong_crypto.decrypt_json(ciphertext)

    assert "invalid key or tampered ciphertext" in str(exc_info.value).lower()


def test_tamper_detection():
    """Validates that modifying a single character in the ciphertext token raises DecryptionError."""
    key_provider = TestKeyProvider()
    crypto = EncryptionService(key_provider)

    payload = {"data": "Valhalla is sovereign"}
    token = crypto.encrypt_json(payload)

    # Tamper with the token string
    tampered_char = "A" if token[-5] != "A" else "B"
    tampered_token = token[:-5] + tampered_char + token[-4:]

    with pytest.raises(DecryptionError):
        crypto.decrypt_json(tampered_token)


def test_missing_key_behavior():
    """Validates fail-safe behavior when encryption key is not set."""
    # Test EnvKeyProvider with unset variable
    env_provider = EnvKeyProvider(env_var="NON_EXISTENT_GO81_KEY_VAR")
    crypto = EncryptionService(env_provider)

    with pytest.raises(MissingKeyError) as exc_info:
        crypto.encrypt_json({"test": "data"})

    assert "not set" in str(exc_info.value).lower()


def test_keyring_key_provider_missing_and_storage(monkeypatch):
    """Verifies KeyringKeyProvider raises MissingKeyError when key is absent and doesn't silently generate one."""
    class MockKeyring:
        def __init__(self):
            self.store = {}
        def get_password(self, service, username):
            return self.store.get((service, username))
        def set_password(self, service, username, password):
            self.store[(service, username)] = password

    mock_k = MockKeyring()
    monkeypatch.setattr("keyring.get_password", mock_k.get_password)
    monkeypatch.setattr("keyring.set_password", mock_k.set_password)

    kp = KeyringKeyProvider(service_name="test_service", username="test_user")

    # When key does not exist, MUST raise MissingKeyError, NEVER silently generate
    with pytest.raises(MissingKeyError):
        kp.get_key()

    # After saving key, retrieves exact key
    test_key = Fernet.generate_key()
    kp.set_key(test_key)
    assert kp.get_key() == test_key


def test_no_silent_key_replacement():
    """
    CRITICAL REQUIREMENT:
    Never silently generate a replacement key if an existing encrypted database cannot be unlocked.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "vault.db")

        # 1. Store record with key A
        key_a_provider = TestKeyProvider()
        crypto_a = EncryptionService(key_a_provider)
        db = DatabaseManager(db_path)
        service_a = MemoryService(db, crypto_a)

        mem = service_a.store_memory(
            category="fact",
            subject="Valhalla",
            predicate="location",
            object_value="Asgard",
        )

        # 2. Try accessing with key B
        key_b_provider = TestKeyProvider()
        crypto_b = EncryptionService(key_b_provider)
        service_b = MemoryService(db, crypto_b)

        # Attempting to inspect or search must fail safely with DecryptionError
        with pytest.raises(DecryptionError):
            service_b.get_memory(mem.id)
