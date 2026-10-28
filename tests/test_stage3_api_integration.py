"""
Integration tests for Stage 3 FastAPI Endpoints & Gateway Integration.
Tests:
- GET /api/skills discovery
- GET /api/skills/{skill_id} inspection
- POST /api/skills/{skill_id}/disable and /enable
- POST /api/skills/propose pre-execution risk and action-hash calculation
- POST /api/skills/{skill_id}/execute low-risk execution
- POST /api/skills/{skill_id}/execute high-risk approval enforcement
- GET /api/skills/audit/records audit trail inspection
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from backend.main import app


@pytest.fixture
def client_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "api_integration.db")
        SubsystemContainer.initialize(db_path=db_path)
        from app.skills.routes import SkillContainer
        SkillContainer.initialize(SubsystemContainer.db, project_root=tmp_dir)

        client = TestClient(app)
        yield client, tmp_dir, SkillContainer


def test_api_list_skills(client_env):
    client, _, _ = client_env
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    skills = resp.json()
    assert isinstance(skills, list)
    assert len(skills) >= 6

    # Verify key builtins exist and have required schema attributes matching frontend types
    skill_ids = [s["id"] for s in skills]
    assert "filesystem.read" in skill_ids
    assert "filesystem.write" in skill_ids
    assert "system.info" in skill_ids
    assert "memory.search" in skill_ids

    # Structure check
    first = skills[0]
    assert "id" in first
    assert "name" in first
    assert "displayName" in first
    assert "risk_level" in first
    assert "enabled" in first
    assert "parameters" in first


def test_api_get_skill_details(client_env):
    client, _, _ = client_env
    resp = client.get("/api/skills/filesystem.read")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "filesystem.read"
    assert data["category"] == "filesystem"
    assert len(data["parameters"]) >= 1

    # 404 for nonexistent skill
    resp_404 = client.get("/api/skills/nonexistent.tool")
    assert resp_404.status_code == 404


def test_api_enable_disable_skill(client_env):
    client, _, _ = client_env

    # 1. Disable skill
    resp_dis = client.post("/api/skills/filesystem.read/disable")
    assert resp_dis.status_code == 200
    assert resp_dis.json()["enabled"] is False

    # Check status via get
    assert client.get("/api/skills/filesystem.read").json()["enabled"] is False

    # 2. Enable skill back
    resp_en = client.post("/api/skills/filesystem.read/enable")
    assert resp_en.status_code == 200
    assert resp_en.json()["enabled"] is True
    assert client.get("/api/skills/filesystem.read").json()["enabled"] is True


def test_api_propose_skill_action(client_env):
    client, _, _ = client_env

    # Propose low risk action
    prop_low = client.post(
        "/api/skills/propose",
        json={"skill_id": "system.info", "parameters": {}},
    )
    assert prop_low.status_code == 200
    data_low = prop_low.json()
    assert data_low["skill_id"] == "system.info"
    assert data_low["requires_approval"] is False
    assert data_low["allowed"] is True
    assert len(data_low["action_hash"]) == 64

    # Propose high risk action requiring approval
    prop_high = client.post(
        "/api/skills/propose",
        json={"skill_id": "filesystem.write", "parameters": {"path": "test.txt", "content": "data"}},
    )
    assert prop_high.status_code == 200
    data_high = prop_high.json()
    assert data_high["skill_id"] == "filesystem.write"
    assert data_high["requires_approval"] is True
    assert data_high["approval_id"] is not None
    assert data_high["allowed"] is False


def test_api_execute_low_risk_skill(client_env):
    client, _, _ = client_env
    resp = client.post(
        "/api/skills/system.info/execute",
        json={"parameters": {}},
    )
    assert resp.status_code == 200
    res = resp.json()
    assert res["success"] is True
    assert "os" in res["output"]
    assert "sovereign_identity" in res["output"]
    assert res["audit_id"] is not None


def test_api_execute_sensitive_skill_requires_approval_and_succeeds_with_token(client_env):
    client, tmp_dir, skill_container = client_env
    gateway = skill_container.gateway

    write_params = {"path": "notes.md", "content": "# Sovereign Agent Notes"}

    # 1. Attempt execution without approval token -> BLOCKED with approval requirement
    resp_blocked = client.post(
        "/api/skills/filesystem.write/execute",
        json={"parameters": write_params},
    )
    assert resp_blocked.status_code == 200
    res_blocked = resp_blocked.json()
    assert res_blocked["success"] is False
    assert "requires explicit human confirmation" in res_blocked["error"].lower()

    # 2. Grant approval token for these parameters
    _, token = gateway.create_approval_token("filesystem.write", write_params)

    # 3. Execute with valid approval token -> SUCCEEDS
    resp_allowed = client.post(
        "/api/skills/filesystem.write/execute",
        json={"parameters": write_params, "approval_token": token},
    )
    assert resp_allowed.status_code == 200
    res_allowed = resp_allowed.json()
    assert res_allowed["success"] is True
    assert res_allowed["output"]["status"] == "success"

    # Verify file was written to disk
    full_path = os.path.join(tmp_dir, "notes.md")
    assert os.path.exists(full_path)
    assert open(full_path).read() == "# Sovereign Agent Notes"


def test_api_get_audit_records(client_env):
    client, _, _ = client_env
    # Trigger an execution
    client.post("/api/skills/system.info/execute", json={"parameters": {}})

    resp = client.get("/api/skills/audit/records?limit=10")
    assert resp.status_code == 200
    records = resp.json()
    assert isinstance(records, list)
    assert len(records) >= 1
    rec = records[0]
    assert "audit_id" in rec
    assert "skill_id" in rec
    assert "policy_outcome" in rec
    assert "execution_status" in rec
