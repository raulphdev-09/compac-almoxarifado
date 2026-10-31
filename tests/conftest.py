from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient


WRITE_HEADERS = {"X-Compac-Client": "web"}
ADMIN_PASSWORD = "Admin-Seguro-2026"


@pytest.fixture
def client_factory(tmp_path, monkeypatch):
    """Each test owns its database and runs the application's lifespan."""
    for name in ("RENDER", "COMPAC_SETUP_TOKEN", "COMPAC_PUBLIC_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COMPAC_DB", str(tmp_path / "compac.db"))
    monkeypatch.setenv("COMPAC_COOKIE_SECURE", "0")

    with ExitStack() as stack:
        def make_client(*, environment=None, base_url="http://testserver"):
            for name, value in (environment or {}).items():
                if value is None:
                    monkeypatch.delenv(name, raising=False)
                else:
                    monkeypatch.setenv(name, str(value))

            from app.main import app, login_attempts

            login_attempts.clear()
            return stack.enter_context(
                TestClient(app, base_url=base_url, headers=WRITE_HEADERS)
            )

        yield make_client


@pytest.fixture
def client(client_factory):
    return client_factory()


@pytest.fixture
def admin(client):
    response = client.post(
        "/api/auth/setup",
        json={
            "name": "Administrador",
            "username": "admin",
            "password": ADMIN_PASSWORD,
        },
    )
    assert response.is_success, response.text
    return client


@pytest.fixture
def catalog(admin):
    def create(resource, **data):
        response = admin.post(f"/api/catalog/{resource}", json=data)
        assert response.is_success, response.text
        return response.json()

    work = create("works", code="OBRA-01", name="Obra principal", status="ATIVA")
    other_work = create("works", code="OBRA-02", name="Outra obra", status="ATIVA")
    category = create("categories", name="Materiais gerais", description="Estoque")
    origin = create("locations", name="Almoxarifado", work_id=work["id"])
    destination = create("locations", name="Frente de serviço", work_id=work["id"])
    other_location = create("locations", name="Outra obra", work_id=other_work["id"])
    employee = create(
        "employees", registration="MAT-001", name="Maria Silva",
        job_title="Operadora", work_id=work["id"], status="ATIVO",
    )
    material = create(
        "materials", code="MAT-001", description="Material de teste",
        category_id=category["id"], unit="UN", minimum_stock=0,
        individualizable=False, status="ATIVO",
    )
    second_material = create(
        "materials", code="MAT-002", description="Segundo material",
        category_id=category["id"], unit="UN", minimum_stock=0,
        individualizable=False, status="ATIVO",
    )
    return {
        "create": create, "work": work, "other_work": other_work,
        "category": category, "origin": origin, "destination": destination,
        "other_location": other_location, "employee": employee,
        "material": material, "second_material": second_material,
    }
