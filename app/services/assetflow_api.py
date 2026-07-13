"""Async HTTP client for the AssetFlow backend API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton async client
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return (and lazily create) a module-level async HTTP client."""
    global _client
    if _client is None or _client.is_closed:
        settings = get_settings()
        _client = httpx.AsyncClient(
            base_url=settings.assetflow_api_url,
            headers={
                "Authorization": f"Bearer {settings.assetflow_admin_token}",
                "x-organization-id": str(settings.assetflow_org_id),
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    return _client


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


async def get_asset(tag: str) -> dict[str, Any] | None:
    """GET /api/assets/{tag} — single asset by tag."""
    try:
        resp = await _get_client().get(f"/api/assets/{tag}")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("get_asset failed for tag=%s", tag)
        return None


async def list_assets(
    status: str | None = None,
    category_id: int | None = None,
    search: str | None = None,
) -> list[dict[str, Any]] | None:
    """GET /api/assets — list with optional filters."""
    params: dict[str, Any] = {}
    if status:
        params["status"] = status
    if category_id is not None:
        params["category_id"] = category_id
    if search:
        params["search"] = search
    try:
        resp = await _get_client().get("/api/assets", params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("list_assets failed")
        return None


async def get_my_allocations(user_id: int) -> list[dict[str, Any]] | None:
    """Return active allocations for *user_id*.

    The admin token doesn't scope ``/api/allocations/my`` to a specific user,
    so we fetch all active allocations and filter client-side.
    """
    try:
        resp = await _get_client().get(
            "/api/allocations", params={"status": "Active"}
        )
        resp.raise_for_status()
        data = resp.json()
        allocations = data if isinstance(data, list) else data.get("data", data)
        return [
            a
            for a in allocations
            if a.get("assigned_to_user_id") == user_id
        ]
    except Exception:
        logger.exception("get_my_allocations failed for user_id=%s", user_id)
        return None


async def allocate_asset(
    asset_tag: str,
    assigned_to_user_id: int,
    expected_return_date: str | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    """POST /api/allocations — create a new allocation."""
    body: dict[str, Any] = {
        "asset_tag": asset_tag,
        "assigned_to_user_id": assigned_to_user_id,
    }
    if expected_return_date:
        body["expected_return_date"] = expected_return_date
    if notes:
        body["notes"] = notes
    try:
        resp = await _get_client().post("/api/allocations", json=body)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("allocate_asset failed")
        return None


async def get_overdue_allocations() -> list[dict[str, Any]] | None:
    """GET /api/allocations/overdue — requires Admin/Asset Manager role."""
    try:
        resp = await _get_client().get("/api/allocations/overdue")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("get_overdue_allocations failed")
        return None


async def get_categories() -> list[dict[str, Any]] | None:
    """GET /api/categories."""
    try:
        resp = await _get_client().get("/api/categories")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("get_categories failed")
        return None


async def get_members() -> list[dict[str, Any]] | None:
    """GET /api/org/members."""
    try:
        resp = await _get_client().get("/api/org/members")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("get_members failed")
        return None


async def login(email: str, password: str) -> dict[str, Any] | None:
    """POST /api/auth/login — returns {token, user}."""
    try:
        resp = await _get_client().post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("login failed for email=%s", email)
        return None

async def request_transfer(
    asset_tag: str,
    requested_new_holder_id: int,
    reason: str,
    urgency: str = "Normal",
) -> dict[str, Any] | None:
    """POST /api/allocations/transfers."""
    body = {
        "asset_tag": asset_tag,
        "requested_new_holder_id": requested_new_holder_id,
        "reason": reason,
        "urgency": urgency,
    }
    try:
        resp = await _get_client().post("/api/allocations/transfers", json=body)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("request_transfer failed")
        return None


async def approve_transfer(transfer_id: int) -> dict[str, Any] | None:
    """PATCH /api/allocations/transfers/{id}/approve."""
    try:
        resp = await _get_client().patch(f"/api/allocations/transfers/{transfer_id}/approve")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("approve_transfer failed")
        return None


async def reject_transfer(transfer_id: int, reason: str = "") -> dict[str, Any] | None:
    """PATCH /api/allocations/transfers/{id}/reject."""
    try:
        resp = await _get_client().patch(
            f"/api/allocations/transfers/{transfer_id}/reject",
            json={"reason": reason}
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("reject_transfer failed")
        return None

async def report_hardware_issue(asset_tag: str, issue_description: str, priority: str = "Medium") -> dict[str, Any] | None:
    """POST /api/maintenance."""
    body = {
        "asset_tag": asset_tag,
        "issue_description": issue_description,
        "priority": priority
    }
    try:
        resp = await _get_client().post("/api/maintenance", json=body)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("report_hardware_issue failed")
        return None


async def create_audit_cycle(name: str, department_id: int, start_date: str, end_date: str) -> dict[str, Any] | None:
    """POST /api/audit/cycles."""
    body = {
        "name": name,
        "target_department_id": department_id,
        "start_date": start_date,
        "end_date": end_date
    }
    try:
        resp = await _get_client().post("/api/audit/cycles", json=body)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("create_audit_cycle failed")
        return None

async def assign_auditors(cycle_id: int, user_ids: list[int]) -> dict[str, Any] | None:
    """POST /api/audit/cycles/{id}/auditors."""
    try:
        resp = await _get_client().post(f"/api/audit/cycles/{cycle_id}/auditors", json={"user_ids": user_ids})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("assign_auditors failed")
        return None

async def bulk_add_audit_items(cycle_id: int, asset_tags: list[str]) -> dict[str, Any] | None:
    """POST /api/audit/cycles/{id}/items/bulk."""
    try:
        resp = await _get_client().post(f"/api/audit/cycles/{cycle_id}/items/bulk", json={"asset_tags": asset_tags})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("bulk_add_audit_items failed")
        return None

async def activate_audit_cycle(cycle_id: int) -> dict[str, Any] | None:
    """PATCH /api/audit/cycles/{id}/activate."""
    try:
        resp = await _get_client().patch(f"/api/audit/cycles/{cycle_id}/activate")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("activate_audit_cycle failed")
        return None

async def get_audit_cycle(cycle_id: int) -> dict[str, Any] | None:
    """GET /api/audit/cycles/{id}."""
    try:
        resp = await _get_client().get(f"/api/audit/cycles/{cycle_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("get_audit_cycle failed")
        return None

async def mark_audit_item(item_id: int, status: str, notes: str = "") -> dict[str, Any] | None:
    """PATCH /api/audit/items/{id}."""
    try:
        resp = await _get_client().patch(f"/api/audit/items/{item_id}", json={"verification_status": status, "notes": notes})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("mark_audit_item failed")
        return None

async def get_departments() -> list[dict[str, Any]] | None:
    """GET /api/departments."""
    try:
        resp = await _get_client().get("/api/departments")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("get_departments failed")
        return None

async def get_members() -> list[dict[str, Any]] | None:
    """GET /api/org/members."""
    try:
        resp = await _get_client().get("/api/org/members")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("get_members failed")
        return None




async def link_slack_account(email: str, slack_user_id: str) -> dict[str, Any] | None:
    """POST /api/auth/link-slack"""
    try:
        resp = await _get_client().post("/api/auth/link-slack", json={"email": email, "slack_user_id": slack_user_id})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("link_slack_account failed")
        return None
