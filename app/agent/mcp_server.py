"""AssetFlow Copilot — MCP server exposing asset-management tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.core.config import get_settings  # noqa: F401 (validates config loads)
from app.services import assetflow_api as api

mcp = FastMCP("AssetFlow Copilot")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def lookup_asset(tag: str) -> str:
    """Look up a single asset by its tag and return key details."""
    asset = await api.get_asset(tag)
    if not asset:
        return f"Asset '{tag}' not found or API error."

    category = asset.get("Category") or {}
    holder = asset.get("CurrentHolder") or {}

    lines = [
        f"Tag:        {asset.get('tag', 'N/A')}",
        f"Name:       {asset.get('name', 'N/A')}",
        f"Status:     {asset.get('status', 'N/A')}",
        f"Category:   {category.get('name', 'N/A')}",
        f"Holder:     {holder.get('name', 'None')} ({holder.get('email', '')})" if holder.get('name') else "Holder:     None",
        f"Location:   {asset.get('location', 'N/A')}",
        f"Condition:  {asset.get('condition', 'N/A')}",
    ]
    return "\n".join(lines)


@mcp.tool()
async def search_available_assets(
    category: str | None = None,
    search: str | None = None,
) -> str:
    """Search for available assets, optionally filtering by category name or search term."""
    category_id: int | None = None

    # Resolve category name → id if provided
    if category:
        cats = await api.get_categories()
        if cats:
            for c in cats:
                if c.get("name", "").lower() == category.lower():
                    category_id = c.get("id")
                    break
            if category_id is None:
                return f"Category '{category}' not found."

    assets = await api.list_assets(status="Available", category_id=category_id, search=search)
    if not assets:
        return "No available assets found."

    lines: list[str] = []
    for a in assets:
        cat_name = (a.get("Category") or {}).get("name", "N/A")
        lines.append(f"- {a.get('tag')} | {a.get('name')} | {cat_name} | {a.get('location', 'N/A')}")

    return f"Available assets ({len(lines)}):\n" + "\n".join(lines)


@mcp.tool()
async def get_user_assets(assetflow_user_id: int) -> str:
    """List assets currently allocated to a specific user."""
    assets = await api.list_assets()
    if not assets:
        return "Could not retrieve assets."

    user_assets = [
        a
        for a in assets
        if a.get("current_holder_id") == assetflow_user_id
        and a.get("status") == "Allocated"
    ]

    if not user_assets:
        return "No assets currently allocated to this user."

    lines: list[str] = []
    for a in user_assets:
        cat_name = (a.get("Category") or {}).get("name", "N/A")
        lines.append(f"- {a.get('tag')} | {a.get('name')} | {cat_name} | {a.get('condition', 'N/A')}")

    return f"Allocated assets ({len(lines)}):\n" + "\n".join(lines)


@mcp.tool()
async def get_overdue_assets() -> str:
    """Get all overdue asset allocations."""
    overdue = await api.get_overdue_allocations()
    if not overdue:
        return "No overdue allocations (or API error)."

    lines: list[str] = []
    for o in overdue:
        asset = o.get("Asset") or {}
        user = o.get("User") or o.get("AssignedTo") or {}
        lines.append(
            f"- {asset.get('tag', 'N/A')} | {asset.get('name', 'N/A')} "
            f"| Holder: {user.get('name', 'N/A')} "
            f"| Due: {o.get('expected_return_date', 'N/A')}"
        )

    return f"Overdue allocations ({len(lines)}):\n" + "\n".join(lines)


@mcp.tool()
async def create_allocation(
    asset_tag: str,
    user_id: int,
    return_date: str | None = None,
    notes: str | None = None,
) -> str:
    """Allocate an asset to a user."""
    result = await api.allocate_asset(
        asset_tag=asset_tag,
        assigned_to_user_id=user_id,
        expected_return_date=return_date,
        notes=notes,
    )
    if not result:
        return "Allocation failed. Check asset tag / user ID and try again."

    return (
        f"Allocation created.\n"
        f"  Asset: {result.get('asset_tag', asset_tag)}\n"
        f"  User ID: {result.get('assigned_to_user_id', user_id)}\n"
        f"  Return date: {result.get('expected_return_date', 'N/A')}"
    )
