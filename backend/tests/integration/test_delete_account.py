import pytest

from tests.helpers import (
    FIXED_PIN,
    auth_headers,
    create_household,
    create_invite,
    signup,
    signup_and_login,
)

pytestmark = pytest.mark.asyncio


async def test_delete_account_requires_correct_pin(client, monkeypatch):
    await signup(client, monkeypatch, "ada@example.com")
    resp = await client.post(
        "/auth/delete-account", json={"email": "ada@example.com", "pin": "000000"}
    )
    assert resp.status_code == 401


async def test_delete_account_unknown_email_fails(client, monkeypatch):
    resp = await client.post(
        "/auth/delete-account", json={"email": "nobody@example.com", "pin": FIXED_PIN}
    )
    assert resp.status_code == 401


async def test_delete_account_with_no_household_locks_out_future_login(client, monkeypatch):
    await signup(client, monkeypatch, "solo@example.com")

    resp = await client.post(
        "/auth/delete-account", json={"email": "solo@example.com", "pin": FIXED_PIN}
    )
    assert resp.status_code == 204

    login_resp = await client.post(
        "/auth/login", json={"email": "solo@example.com", "pin": FIXED_PIN}
    )
    assert login_resp.status_code == 401


async def test_delete_account_frees_the_email_for_reuse(client, monkeypatch):
    await signup(client, monkeypatch, "reuse@example.com")
    await client.post(
        "/auth/delete-account", json={"email": "reuse@example.com", "pin": FIXED_PIN}
    )

    resp = await signup(client, monkeypatch, "reuse@example.com")
    assert resp.status_code == 201


async def test_delete_account_as_sole_household_member_deletes_household(client, monkeypatch):
    token, _ = await signup_and_login(client, monkeypatch, "owner@example.com")
    household = await create_household(client, token, "Solo House")

    resp = await client.post(
        "/auth/delete-account", json={"email": "owner@example.com", "pin": FIXED_PIN}
    )
    assert resp.status_code == 204

    other_token, _ = await signup_and_login(client, monkeypatch, "checker@example.com")
    check_resp = await client.get(
        f"/households/{household['id']}", headers=auth_headers(other_token)
    )
    assert check_resp.status_code in (403, 404)


async def test_delete_account_as_owner_auto_transfers_to_admin(client, monkeypatch):
    owner_token, _ = await signup_and_login(client, monkeypatch, "owner@example.com")
    household = await create_household(client, owner_token, "Shared House")

    _, invite_token = await create_invite(client, owner_token, household["id"])
    admin_token, admin_user = await signup_and_login(client, monkeypatch, "admin@example.com")
    await client.post(
        "/households/join", json={"token": invite_token}, headers=auth_headers(admin_token)
    )
    household_resp = await client.get(
        f"/households/{household['id']}", headers=auth_headers(owner_token)
    )
    admin_member_id = next(
        m["id"] for m in household_resp.json()["members"] if m["user"]["id"] == admin_user["id"]
    )
    await client.patch(
        f"/households/{household['id']}/members/{admin_member_id}/role",
        json={"role": "admin"},
        headers=auth_headers(owner_token),
    )

    resp = await client.post(
        "/auth/delete-account", json={"email": "owner@example.com", "pin": FIXED_PIN}
    )
    assert resp.status_code == 204

    members_resp = await client.get(
        f"/households/{household['id']}", headers=auth_headers(admin_token)
    )
    assert members_resp.status_code == 200
    roles = {m["user"]["id"]: m["role"] for m in members_resp.json()["members"]}
    assert roles[admin_user["id"]] == "owner"
    assert len(roles) == 1
