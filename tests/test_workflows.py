import csv
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import StringIO
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from conftest import ADMIN_PASSWORD, WRITE_HEADERS


def successful(response):
    assert response.is_success, f"{response.status_code}: {response.text}"
    return response.json()


def rejected(response):
    assert response.status_code in {400, 401, 403, 404, 409, 422}, response.text


def catalog_input(record, **changes):
    data = {key: value for key, value in record.items() if key != "id"}
    if "individualizable" in data:
        data["individualizable"] = bool(data["individualizable"])
    return {**data, **changes}


def movement(client, catalog, kind, quantity, *, material=None, **fields):
    data = {
        "type": kind,
        "material_id": (material or catalog["material"])["id"],
        "quantity": quantity,
    }
    if kind == "ENTRADA":
        data["destination_id"] = catalog["origin"]["id"]
    elif kind == "SAIDA":
        data.update(origin_id=catalog["origin"]["id"], employee_id=catalog["employee"]["id"])
    elif kind == "DEVOLUCAO":
        data.update(destination_id=catalog["origin"]["id"], employee_id=catalog["employee"]["id"])
    elif kind == "TRANSFERENCIA":
        data.update(origin_id=catalog["origin"]["id"], destination_id=catalog["destination"]["id"])
    elif kind == "AJUSTE":
        data["destination_id"] = catalog["origin"]["id"]
    data.update(fields)
    return client.post("/api/movements", json=data)


def stock(client, material_id, location_id=None):
    rows = successful(client.get("/api/stock"))
    return sum(
        (Decimal(str(row["quantity"])) for row in rows
         if row["material_id"] == material_id
         and (location_id is None or row["location_id"] == location_id)),
        Decimal("0"),
    )


def outstanding(client, catalog):
    rows = successful(client.get("/api/loans"))
    return sum(
        (Decimal(str(row["quantity"])) for row in rows
         if row["material_id"] == catalog["material"]["id"]
         and row["employee_id"] == catalog["employee"]["id"]),
        Decimal("0"),
    )


def test_bootstrap_requires_configured_token_and_secure_cookie(client_factory):
    public_url = "https://compac.example"
    client = client_factory(
        environment={
            "RENDER": "true", "COMPAC_SETUP_TOKEN": "segredo-de-inicializacao",
            "COMPAC_COOKIE_SECURE": "1", "COMPAC_PUBLIC_URL": public_url,
        },
        base_url="https://internal.example",
    )
    status = successful(client.get("/api/auth/status"))
    assert status["needs_setup"] is True
    assert status["setup_token_required"] is True
    user = {"name": "Admin", "username": "admin", "password": ADMIN_PASSWORD}
    origin = {"Origin": public_url}
    rejected(client.post("/api/auth/setup", json=user, headers=origin))
    rejected(client.post("/api/auth/setup", json={**user, "setup_token": "errado"}, headers=origin))
    response = client.post(
        "/api/auth/setup", json={**user, "setup_token": "segredo-de-inicializacao"},
        headers=origin,
    )
    successful(response)
    cookies = "; ".join(response.headers.get_list("set-cookie")).lower()
    assert "httponly" in cookies
    assert "secure" in cookies
    assert "samesite=strict" in cookies
    assert successful(client.get("/api/auth/me"))["role"] == "ADMIN"
    assert successful(client.get("/api/auth/status"))["needs_setup"] is False
    rejected(client.post("/api/auth/setup", json={**user, "setup_token": "segredo-de-inicializacao"}, headers=origin))


def test_render_refuses_unprotected_first_admin(client_factory):
    with pytest.raises(RuntimeError, match="COMPAC_SETUP_TOKEN"):
        client_factory(environment={"RENDER": "true"})


def test_session_login_logout_and_private_reads(client, admin):
    successful(admin.post("/api/auth/logout"))
    assert client.get("/api/stock").status_code == 401
    rejected(client.post("/api/auth/login", json={"username": "admin", "password": "invalida"}))
    successful(client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}))
    assert successful(client.get("/api/auth/me"))["username"] == "admin"
    successful(client.get("/api/stock"))


def test_writes_require_client_header_and_trusted_public_origin(client_factory):
    public_url = "https://compac.example"
    client = client_factory(environment={"COMPAC_PUBLIC_URL": public_url})
    user = {"name": "Admin", "username": "admin", "password": ADMIN_PASSWORD}
    successful(client.post("/api/auth/setup", json=user, headers={"Origin": public_url}))
    data = {"name": "Categoria segura"}
    assert client.post("/api/catalog/categories", json=data, headers={"Origin": "https://outro.example"}).status_code == 403
    assert client.post("/api/catalog/categories", json=data, headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/catalog/categories", json=data, headers={"Origin": public_url, "X-Compac-Client": ""}).status_code == 403
    successful(client.post("/api/catalog/categories", json=data, headers={"Origin": public_url}))


def test_three_decimal_stock_and_negative_balance_rollback(admin, catalog):
    successful(movement(admin, catalog, "ENTRADA", 0.100))
    successful(movement(admin, catalog, "ENTRADA", 0.200))
    assert stock(admin, catalog["material"]["id"]) == Decimal("0.300")
    before = len(successful(admin.get("/api/movements")))
    rejected(movement(admin, catalog, "SAIDA", 0.301))
    assert len(successful(admin.get("/api/movements"))) == before
    assert stock(admin, catalog["material"]["id"]) == Decimal("0.300")
    successful(movement(admin, catalog, "SAIDA", 0.300))
    assert stock(admin, catalog["material"]["id"]) == 0
    assert outstanding(admin, catalog) == Decimal("0.300")


def test_concurrent_outbound_movements_cannot_overspend(admin, catalog):
    successful(movement(admin, catalog, "ENTRADA", 1))
    barrier = Barrier(2)
    with TestClient(admin.app, headers=WRITE_HEADERS) as first, TestClient(admin.app, headers=WRITE_HEADERS) as second:
        for session in (first, second):
            successful(session.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}))

        def withdraw(session):
            barrier.wait(timeout=10)
            return movement(session, catalog, "SAIDA", 0.600)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(withdraw, (first, second)))
    assert sum(response.is_success for response in responses) == 1
    for response in responses:
        if not response.is_success:
            rejected(response)
    assert stock(admin, catalog["material"]["id"]) == Decimal("0.400")
    assert outstanding(admin, catalog) == Decimal("0.600")
    assert len(successful(admin.get("/api/movements"))) == 2


def test_partial_returns_reject_excess_and_allow_inactive_records(admin, catalog):
    successful(movement(admin, catalog, "ENTRADA", 2))
    successful(movement(admin, catalog, "SAIDA", 1))
    successful(movement(admin, catalog, "DEVOLUCAO", 0.250))
    assert outstanding(admin, catalog) == Decimal("0.750")
    before = stock(admin, catalog["material"]["id"])
    rejected(movement(admin, catalog, "DEVOLUCAO", 0.751))
    assert stock(admin, catalog["material"]["id"]) == before
    assert outstanding(admin, catalog) == Decimal("0.750")
    for entity in ("employees", "materials"):
        record = catalog["employee" if entity == "employees" else "material"]
        successful(admin.put(f"/api/catalog/{entity}/{record['id']}", json=catalog_input(record, status="INATIVO")))
    successful(movement(admin, catalog, "DEVOLUCAO", 0.750))
    assert outstanding(admin, catalog) == 0
    assert stock(admin, catalog["material"]["id"]) == Decimal("2")


def test_transfer_conserves_stock_and_adjustment_sets_balance(admin, catalog):
    successful(movement(admin, catalog, "ENTRADA", 4))
    successful(movement(admin, catalog, "TRANSFERENCIA", 1.125))
    material_id = catalog["material"]["id"]
    assert stock(admin, material_id, catalog["origin"]["id"]) == Decimal("2.875")
    assert stock(admin, material_id, catalog["destination"]["id"]) == Decimal("1.125")
    assert stock(admin, material_id) == 4
    rejected(movement(admin, catalog, "AJUSTE", 0.500))
    successful(movement(admin, catalog, "AJUSTE", 0.500, notes="Contagem física conferida"))
    assert stock(admin, material_id, catalog["origin"]["id"]) == Decimal("0.500")
    successful(movement(admin, catalog, "AJUSTE", 0, notes="Saldo físico zerado"))
    assert stock(admin, material_id, catalog["origin"]["id"]) == 0


def test_expense_total_and_forecast_aggregate_material_coefficients(admin, catalog):
    expense = catalog["create"](
        "expenses", supplier="Fornecedor", document_number="NF-123",
        purchase_date="2026-10-31", material_id=catalog["material"]["id"],
        work_id=catalog["work"]["id"], quantity=1.250, unit_cost=12.40,
    )
    assert Decimal(str(expense["total_cost"])) == Decimal("15.50")
    for coefficient, team in ((1.25, "Equipe A"), (0.75, "Equipe B")):
        catalog["create"](
            "consumption_profiles", work_id=catalog["work"]["id"], activity="Concretagem",
            material_id=catalog["material"]["id"], consumption_per_unit=coefficient,
            team=team, shift="DIURNO",
        )
    result = successful(admin.get("/api/forecast", params={
        "work_id": catalog["work"]["id"], "activity": "Concretagem", "quantity_produced": 10,
    }))
    rows = result["items"] if isinstance(result, dict) else result
    assert len(rows) == 1
    assert rows[0]["material_id"] == catalog["material"]["id"]
    assert Decimal(str(rows[0]["expected"])) == Decimal("20")


def create_requisition(admin, catalog, items):
    return successful(admin.post("/api/requisitions", json={
        "work_id": catalog["work"]["id"], "priority": "NORMAL", "notes": "Material para frente",
        "items": items,
    }))


def requisition_action(admin, requisition, action, **data):
    return admin.post(f"/api/requisitions/{requisition['id']}/action", json={"action": action, **data})


def test_requisition_fulfillment_is_atomic_and_checks_destination_work(admin, catalog):
    successful(movement(admin, catalog, "ENTRADA", 5))
    successful(movement(admin, catalog, "ENTRADA", 1, material=catalog["second_material"]))
    request = create_requisition(admin, catalog, [
        {"material_id": catalog["material"]["id"], "quantity": 2},
        {"material_id": catalog["second_material"]["id"], "quantity": 3},
    ])
    successful(requisition_action(admin, request, "APROVAR"))
    before = successful(admin.get("/api/requisitions"))
    movement_count = len(successful(admin.get("/api/movements")))
    rejected(requisition_action(admin, request, "ATENDER", origin_id=catalog["origin"]["id"], destination_id=catalog["destination"]["id"]))
    assert stock(admin, catalog["material"]["id"], catalog["origin"]["id"]) == 5
    assert stock(admin, catalog["second_material"]["id"], catalog["origin"]["id"]) == 1
    assert stock(admin, catalog["material"]["id"], catalog["destination"]["id"]) == 0
    assert len(successful(admin.get("/api/movements"))) == movement_count
    assert successful(admin.get("/api/requisitions")) == before
    successful(movement(admin, catalog, "ENTRADA", 2, material=catalog["second_material"]))
    rejected(requisition_action(admin, request, "ATENDER", origin_id=catalog["origin"]["id"], destination_id=catalog["other_location"]["id"]))
    successful(requisition_action(admin, request, "ATENDER", origin_id=catalog["origin"]["id"], destination_id=catalog["destination"]["id"]))
    assert stock(admin, catalog["material"]["id"], catalog["destination"]["id"]) == 2
    assert stock(admin, catalog["second_material"]["id"], catalog["destination"]["id"]) == 3
    assert stock(admin, catalog["material"]["id"]) == 5
    rejected(requisition_action(admin, request, "ATENDER", origin_id=catalog["origin"]["id"], destination_id=catalog["destination"]["id"]))


def test_cancelled_requisition_does_not_move_stock(admin, catalog):
    successful(movement(admin, catalog, "ENTRADA", 5))
    request = create_requisition(admin, catalog, [{"material_id": catalog["material"]["id"], "quantity": 2}])
    successful(requisition_action(admin, request, "CANCELAR"))
    rejected(requisition_action(admin, request, "APROVAR"))
    assert stock(admin, catalog["material"]["id"]) == 5
    assert len(successful(admin.get("/api/movements"))) == 1


def test_ticket_transitions_comments_and_history(admin, catalog):
    ticket = successful(admin.post("/api/tickets", json={
        "title": "Bomba sem pressão", "description": "Verificar alimentação",
        "priority": "NORMAL", "work_id": catalog["work"]["id"],
    }))
    path = f"/api/tickets/{ticket['id']}"
    rejected(admin.patch(path, json={"status": "RESOLVIDO"}))
    successful(admin.post(f"{path}/comments", json={"body": "Inspeção iniciada"}))
    for status in ("EM_ANDAMENTO", "RESOLVIDO", "ABERTO", "CANCELADO"):
        successful(admin.patch(path, json={"status": status}))
    detail = successful(admin.get(path))
    assert detail["status"] == "CANCELADO"
    assert any(comment["body"] == "Inspeção iniciada" for comment in detail["comments"])
    assert len(detail["history"]) >= 4


def test_maintenance_changes_equipment_availability(admin, catalog):
    material = catalog["create"](
        "materials", code="EQP-001", description="Furadeira", category_id=catalog["category"]["id"],
        unit="UN", minimum_stock=0, individualizable=True, status="ATIVO",
    )
    equipment = catalog["create"](
        "equipment", asset_tag="PAT-001", material_id=material["id"],
        location_id=catalog["origin"]["id"], condition="BOA", status="DISPONIVEL",
    )
    service = successful(admin.post("/api/maintenance", json={"equipment_id": equipment["id"], "defect": "Cabo rompido"}))

    def equipment_status():
        rows = successful(admin.get("/api/catalog/equipment"))
        return next(row["status"] for row in rows if row["id"] == equipment["id"])

    assert equipment_status() == "MANUTENCAO"
    successful(admin.post(f"/api/maintenance/{service['id']}/close", json={"resolution": "Cabo substituído", "condition": "BOA"}))
    assert equipment_status() == "DISPONIVEL"
    rejected(admin.post(f"/api/maintenance/{service['id']}/close", json={"resolution": "Repetição", "condition": "BOA"}))


@pytest.mark.parametrize("role", ["OPERADOR", "CONSULTA"])
def test_roles_restrict_writes_adjustments_approval_and_audit(admin, catalog, role):
    successful(admin.post("/api/users", json={"name": role, "username": role.lower(), "password": ADMIN_PASSWORD, "role": role}))
    request = create_requisition(admin, catalog, [{"material_id": catalog["material"]["id"], "quantity": 1}])
    with TestClient(admin.app, headers=WRITE_HEADERS) as session:
        successful(session.post("/api/auth/login", json={"username": role.lower(), "password": ADMIN_PASSWORD}))
        successful(session.get("/api/stock"))
        assert movement(session, catalog, "AJUSTE", 1, notes="Contagem").status_code == 403
        assert requisition_action(session, request, "APROVAR").status_code == 403
        assert session.get("/api/audit").status_code == 403
        response = session.post("/api/catalog/categories", json={"name": f"Categoria {role}"})
        if role == "CONSULTA":
            assert response.status_code == 403
        else:
            successful(response)
    successful(admin.get("/api/audit"))


@pytest.mark.parametrize("change", [{"password": "Nova-Senha-Segura-2026"}, {"role": "CONSULTA"}, {"active": False}])
def test_user_security_changes_revoke_existing_sessions(admin, change):
    user = successful(admin.post("/api/users", json={"name": "Operador", "username": "operador", "password": ADMIN_PASSWORD, "role": "OPERADOR"}))
    with TestClient(admin.app, headers=WRITE_HEADERS) as session:
        successful(session.post("/api/auth/login", json={"username": "operador", "password": ADMIN_PASSWORD}))
        successful(session.get("/api/auth/me"))
        successful(admin.patch(f"/api/users/{user['id']}", json=change))
        assert session.get("/api/auth/me").status_code == 401


def test_csv_exports_neutralize_spreadsheet_formulas(admin, catalog):
    marker = "=1+1"
    material = catalog["material"]
    successful(admin.put(f"/api/catalog/materials/{material['id']}", json=catalog_input(material, description=marker)))
    successful(movement(admin, catalog, "ENTRADA", 5, notes=marker))
    catalog["create"](
        "expenses", supplier=marker, purchase_date="2026-10-31",
        material_id=material["id"], quantity=1, unit_cost=2,
    )
    successful(admin.post("/api/tickets", json={"title": marker, "description": "Exportação", "priority": "NORMAL"}))
    successful(admin.post("/api/requisitions", json={"work_id": catalog["work"]["id"], "priority": "NORMAL", "notes": marker, "items": [{"material_id": material["id"], "quantity": 1}]}))
    catalog["create"]("production", work_id=catalog["work"]["id"], activity=marker, quantity_produced=1, produced_at="2026-10-31")
    for resource in ("stock", "movements", "expenses", "tickets", "requisitions", "production"):
        response = admin.get(f"/api/export/{resource}")
        assert response.is_success, response.text
        assert "text/csv" in response.headers["content-type"]
        rows = list(csv.reader(StringIO(response.text.lstrip("\ufeff")), delimiter=";"))
        assert len(rows) >= 2, resource
        cells = [cell for row in rows[1:] for cell in row]
        assert marker not in cells, resource
        assert f"'{marker}" in cells, resource


def test_health_and_pwa_public_assets(client):
    assert client.get("/health").is_success
    manifest = successful(client.get("/manifest.webmanifest"))
    assert manifest["start_url"].startswith("/")
    assert manifest["scope"] == "/"
    worker = client.get("/sw.js")
    assert worker.is_success
    assert "javascript" in worker.headers["content-type"]
    assert client.get("/offline.html").is_success
