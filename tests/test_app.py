from __future__ import annotations

from app import ITConta, app, db
from security_utils import decrypt_secret, encrypt_secret


def test_healthcheck_and_security_headers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {
        "service": "helpdesk-it-operations",
        "status": "ok",
    }
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_protected_api_rejects_anonymous_requests(client):
    response = client.get("/api/tickets")
    assert response.status_code == 401
    assert response.get_json()["error"] == "Autenticação necessária"


def test_demo_login_and_ticket_flow(authenticated_client):
    created = authenticated_client.post(
        "/api/tickets",
        json={
            "nome": "Usuário Demo",
            "titulo": "Falha de acesso",
            "descricao": "O acesso ao sistema de homologação não foi concluído.",
            "prioridade": "media",
        },
    )
    assert created.status_code == 201
    ticket_id = created.get_json()["ticket_id"]

    listing = authenticated_client.get("/api/tickets")
    assert listing.status_code == 200
    assert any(ticket["id"] == ticket_id for ticket in listing.get_json())


def test_login_rejects_external_redirect(client):
    response = client.post(
        "/login?next=https://example.com",
        json={"username": "demo_admin", "password": "change-me-local"},
    )
    assert response.status_code == 200
    assert response.get_json()["redirect"] == "/"


def test_cross_origin_write_is_rejected(client):
    response = client.post(
        "/login",
        headers={"Origin": "https://attacker.example"},
        json={"username": "demo_admin", "password": "change-me-local"},
    )
    assert response.status_code == 403


def test_secret_is_encrypted_and_not_exposed_in_payload():
    encrypted = encrypt_secret("temporary-password")
    assert encrypted and encrypted != "temporary-password"
    assert decrypt_secret(encrypted) == "temporary-password"

    with app.app_context():
        record = ITConta(
            it_user_id=1,
            sistema="Demo",
            login="demo@example.local",
            senha=encrypted,
        )
        payload = record.to_dict()
    assert payload["senha"] is None
    assert payload["has_secret"] is True


def test_inventory_api_requires_admin(regular_user_client):
    response = regular_user_client.get("/api/it/users")
    assert response.status_code == 403
    assert response.get_json()["error"] == "Acesso negado"


def test_local_ai_is_disabled_by_default(authenticated_client):
    response = authenticated_client.post(
        "/api/ia/chat",
        json={"pergunta": "Resuma o inventário"},
    )
    assert response.status_code == 503
    assert response.get_json()["error"] == "Integração local de IA desabilitada"
