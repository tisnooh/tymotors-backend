from fastapi.testclient import TestClient
from tests.test_email_system import settings
import server

def test_actual_backend_lifespan_opens_and_closes_dependencies(monkeypatch):
    # No database network call or hosted credential: validate real initialization locally.
    monkeypatch.setattr(server, 'settings', settings(email_enabled=False))
    with TestClient(server.app) as client:
        assert server.db._client is not None
        response = client.get('/api/')
        assert response.status_code == 200 and response.json()['database'] == 'supabase'
    assert server.db._client is None
