from fastapi.testclient import TestClient
import pytest

from ui_server import create_ui_app


@pytest.mark.parametrize("marker", ["\n[E2E_TOOL_503_ONCE]", "\n[E2E_ALWAYS_FAIL]"])
def test_test_server_fault_markers_use_isolated_database_and_keep_input(marker, samples, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DB_PATH", str(tmp_path / "ui.sqlite3"))
    app = create_ui_app()
    with TestClient(app) as client:
        text = samples["S1"] + marker
        original = client.post("/api/tasks", json={"text": text}).json()
        result = client.get(f"/api/tasks/{original['id']}").json()
        assert result["status"] == "failed"
        assert result["error"]["code"] == "test_tool_503"
        assert result["text"] == text
        retry = client.post(f"/api/tasks/{original['id']}/retry").json()
        retried = client.get(f"/api/tasks/{retry['id']}").json()
        assert retried["text"] == text
        assert retried["input_version"] == result["input_version"]
        assert retried["status"] == ("pending_review" if "ONCE" in marker else "failed")
    app.state.store.close()


def test_test_server_grades_C_missing_fixture_without_model_network(samples, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DB_PATH", str(tmp_path / "ui.sqlite3"))
    app = create_ui_app()
    with TestClient(app) as client:
        task = client.post("/api/tasks", json={"text": samples["S2"]}).json()
        result = client.get(f"/api/tasks/{task['id']}").json()
        assert result["status"] == "pending_review"
        assert result["draft"]["total"] == 70
    app.state.store.close()
