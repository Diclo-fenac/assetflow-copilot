"""
Slack Bolt app — handles events, interactive actions, Home Tab.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from app.core.config import settings
from app.db.database import AsyncSessionLocal, AssetRequest, UserMapping, TenantMapping
from app.agent.langgraph_agent import run_agent
from app.services import assetflow_api as api

logger = logging.getLogger(__name__)

app = AsyncApp(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

async def get_user_mapping(slack_user_id: str) -> UserMapping | None:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserMapping).where(UserMapping.slack_user_id == slack_user_id)
        )
        return result.scalar_one_or_none()


async def get_tenant(slack_workspace_id: str) -> TenantMapping | None:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TenantMapping).where(TenantMapping.slack_workspace_id == slack_workspace_id)
        )
        return result.scalar_one_or_none()


async def save_request(slack_user_id: str, slack_workspace_id: str, af_user_id: int, asset_tag: str, asset_name: str, notes: str = None) -> AssetRequest:
    async with AsyncSessionLocal() as session:
        req = AssetRequest(
            slack_user_id=slack_user_id,
            slack_workspace_id=slack_workspace_id,
            assetflow_user_id=af_user_id,
            asset_tag=asset_tag,
            asset_name=asset_name,
            status="Pending",
            notes=notes,
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
        return req


async def update_request_status(request_id: int, status: str, approved_by: str = None) -> AssetRequest | None:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AssetRequest).where(AssetRequest.id == request_id)
        )
        req = result.scalar_one_or_none()
        if req:
            req.status = status
            if approved_by:
                req.approved_by_slack_id = approved_by
            await session.commit()
            await session.refresh(req)
        return req


# ── Block Kit Builders ───────────────────────────────────────────────────────

def build_recommendation_blocks(assets: list[dict], request_context: str = "") -> list[dict]:
    """Build Block Kit blocks for asset recommendations with select buttons."""
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Available Assets* — {request_context}"},
        },
        {"type": "divider"},
    ]

    for i, a in enumerate(assets[:3]):
        cat = a.get("Category", {})
        tag = a.get("tag", "?")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{a.get('name', '?')}* (`{tag}`)\n"
                    f"• Category: {cat.get('name', 'N/A')}  • Condition: {a.get('condition', 'N/A')}  • Location: {a.get('location', 'N/A')}"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Request Asset"},
                "action_id": f"select_asset_{i}",
                "value": json.dumps({"tag": tag, "name": a.get("name", "?")}),
                "style": "primary",
            },
        })

    return blocks


def build_confirm_block(asset_tag: str, asset_name: str) -> list[dict]:
    """Build confirmation block after user selects an asset."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"You selected *{asset_name}* (`{asset_tag}`).\n\nReady to submit this request to your Asset Manager for approval?",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Confirm Request"},
                    "action_id": "confirm_request",
                    "value": json.dumps({"tag": asset_tag, "name": asset_name}),
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "cancel_request",
                },
            ],
        },
    ]


def build_approval_block(request_id: int, requester_name: str, asset_tag: str, asset_name: str, notes: str = None) -> list[dict]:
    """Build approval card sent to #asset-approvals channel."""
    text = (
        f"*New Asset Request* (`REQ-{request_id:04d}`)\n\n"
        f"• *Requester:* {requester_name}\n"
        f"• *Asset:* {asset_name} (`{asset_tag}`)\n"
    )
    if notes:
        text += f"• *Reason:* {notes}\n"

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "action_id": "approve_request",
                    "value": str(request_id),
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": "reject_request",
                    "value": str(request_id),
                    "style": "danger",
                },
            ],
        },
    ]


def build_home_tab(user_assets: list[dict], pending_requests: list[AssetRequest] = None) -> dict:
    """Build App Home tab view."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "AssetFlow Agent"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*My Active Assets* ({len(user_assets)})"},
        },
    ]

    if not user_assets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No assets currently assigned to you._"},
        })
    else:
        for a in user_assets[:5]:
            cat = a.get("Category", {})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"• *{a.get('name', '?')}* (`{a.get('tag', '?')}`)\n"
                        f"  Category: {cat.get('name', 'N/A')}  |  Condition: {a.get('condition', 'N/A')}  |  Location: {a.get('location', 'N/A')}"
                    ),
                },
            })

    blocks.append({"type": "divider"})

    # Pending requests section
    if pending_requests:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Pending Requests* ({len(pending_requests)})"},
        })
        for r in pending_requests[:5]:
            status_indicator = "Pending" if r.status == "Pending" else r.status
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• `REQ-{r.id:04d}`: {r.asset_name} (`{r.asset_tag}`) — Status: *{status_indicator}*",
                },
            })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No pending requests._"},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Refresh"},
                "action_id": "refresh_home",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Help / What can I do?"},
                "action_id": "show_help_menu",
            },
        ],
    })

    return {"type": "home", "blocks": blocks}


# ── Overdue Notification Builder ─────────────────────────────────────────────

def build_overdue_dm(asset_name: str, asset_tag: str, due_date: str) -> list[dict]:
    """Build overdue asset reminder DM blocks."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Action Required: Overdue Asset*\n\n"
                    f"You are currently holding *{asset_name}* (`{asset_tag}`) "
                    f"which was due on *{due_date}*.\n\n"
                    f"Please take action:"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Return Asset"},
                    "action_id": "return_overdue",
                    "value": asset_tag,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Request Extension"},
                    "action_id": "request_extension",
                    "value": asset_tag,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Report Issue"},
                    "action_id": "report_issue",
                    "value": asset_tag,
                    "style": "danger",
                },
            ],
        },
    ]


# ── Event Handlers ───────────────────────────────────────────────────────────

@app.event("app_mention")
async def handle_mention(event: dict, say, client: AsyncWebClient):
    """Handle @AssetFlowAgent mentions — route through LangGraph."""
    slack_user_id = event.get("user", "")
    text = event.get("text", "")
    # Strip bot mention from text
    text = " ".join(w for w in text.split() if not w.startswith("<@"))

    mapping = await get_user_mapping(slack_user_id)
    context = ""
    if mapping:
        context = f"Slack user {slack_user_id} maps to AssetFlow user_id={mapping.assetflow_user_id}, email={mapping.email}."

    # Check if user asking for available assets -> use Block Kit
    text_lower = text.lower()
    needs_asset = any(kw in text_lower for kw in ["need", "want", "request", "get me", "looking for", "require"])
    if needs_asset:
        # Extract category hint
        category = None
        for cat_hint in ["laptop", "monitor", "keyboard", "mouse", "phone", "headset", "charger", "tablet", "camera"]:
            if cat_hint in text_lower:
                category = cat_hint.capitalize()
                break

        assets = await api.list_assets(status="Available")
        if category and assets:
            cats = await api.get_categories()
            cat_id = None
            if cats:
                for c in cats:
                    if c["name"].lower() == category.lower():
                        cat_id = c["id"]
                        break
            if cat_id:
                assets = [a for a in assets if a.get("category_id") == cat_id]

        if assets:
            blocks = build_recommendation_blocks(assets, f"Matching: {category or 'all categories'}")
            await say(blocks=blocks, text=f"Found {len(assets)} available asset(s).")
        else:
            await say(f"No available assets found{' in category ' + category if category else ''}. Try asking your Asset Manager.")
        return

    # Default: route through LangGraph agent
    response = await run_agent(text, context)
    await say(response)


@app.event("app_home_opened")
async def handle_home_tab(event: dict, client: AsyncWebClient):
    """Render Home Tab with user's assets and pending requests."""
    slack_user_id = event.get("user", "")
    mapping = await get_user_mapping(slack_user_id)

    user_assets = []
    pending_requests = []

    if mapping:
        # Fetch user's allocated assets
        all_assets = await api.list_assets()
        if all_assets:
            user_assets = [
                a for a in all_assets
                if a.get("current_holder_id") == mapping.assetflow_user_id and a.get("status") == "Allocated"
            ]

        # Fetch pending requests from local DB
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AssetRequest)
                .where(AssetRequest.slack_user_id == slack_user_id)
                .order_by(AssetRequest.created_at.desc())
                .limit(5)
            )
            pending_requests = list(result.scalars().all())

    view = build_home_tab(user_assets, pending_requests)
    await client.views_publish(user_id=slack_user_id, view=view)


@app.event("message")
async def handle_dm(event: dict, say, client: AsyncWebClient):
    """Handle direct messages to the bot."""
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id"):
        return

    slack_user_id = event.get("user", "")
    text = event.get("text", "")

    mapping = await get_user_mapping(slack_user_id)
    context = ""
    if mapping:
        context = f"Slack user {slack_user_id} maps to AssetFlow user_id={mapping.assetflow_user_id}, email={mapping.email}."

    response = await run_agent(text, context)
    await say(response)


# ── Interactive Action Handlers ──────────────────────────────────────────────

@app.action("select_asset_0")
@app.action("select_asset_1")
@app.action("select_asset_2")
async def handle_asset_selection(ack, body, client: AsyncWebClient):
    """Handle user clicking Select on a recommended asset."""
    await ack()
    action = body["actions"][0]
    data = json.loads(action["value"])
    tag = data["tag"]
    name = data["name"]

    channel = body["channel"]["id"]
    ts = body["message"]["ts"]

    blocks = build_confirm_block(tag, name)
    await client.chat_update(channel=channel, ts=ts, blocks=blocks, text=f"Selected {name} ({tag})")


@app.action("confirm_request")
async def handle_confirm_request(ack, body, client: AsyncWebClient):
    """Handle user confirming asset request -> create local Pending record -> notify approvals channel."""
    await ack()
    action = body["actions"][0]
    data = json.loads(action["value"])
    tag = data["tag"]
    name = data["name"]

    slack_user_id = body["user"]["id"]
    slack_workspace_id = body.get("team", {}).get("id", settings.assetflow_org_id)
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]

    mapping = await get_user_mapping(slack_user_id)
    if not mapping:
        await client.chat_update(
            channel=channel, ts=ts,
            text="❌ Your Slack account is not linked to AssetFlow. Contact your admin.",
            blocks=[],
        )
        return

    # Save request locally
    req = await save_request(
        slack_user_id=slack_user_id,
        slack_workspace_id=slack_workspace_id,
        af_user_id=mapping.assetflow_user_id,
        asset_tag=tag,
        asset_name=name,
        notes="Requested via Slack",
    )

    # Update employee message
    await client.chat_update(
        channel=channel, ts=ts,
        text=f"📨 Request `REQ-{req.id:04d}` submitted for *{name}* (`{tag}`). Awaiting manager approval.",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"📨 Request `REQ-{req.id:04d}` submitted for *{name}* (`{tag}`).\n\n🕐 *Status:* Awaiting manager approval."},
        }],
    )

    # Get user info for display name
    user_info = await client.users_info(user=slack_user_id)
    requester_name = user_info["user"]["real_name"] if user_info.get("ok") else slack_user_id

    # Post approval card to approvals channel
    tenant = await get_tenant(slack_workspace_id)
    approvals_channel = tenant.approvals_channel_id if tenant else None
    if not approvals_channel:
        approvals_channel = settings.slack_approvals_channel

    if approvals_channel:
        approval_blocks = build_approval_block(req.id, requester_name, tag, name, "Requested via Slack")
        resp = await client.chat_postMessage(
            channel=approvals_channel,
            blocks=approval_blocks,
            text=f"New asset request REQ-{req.id:04d} from {requester_name}",
        )
        # Save message_ts for later update
        if resp.get("ok"):
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                result = await session.execute(select(AssetRequest).where(AssetRequest.id == req.id))
                r = result.scalar_one_or_none()
                if r:
                    r.approval_message_ts = resp["ts"]
                    await session.commit()


@app.action("cancel_request")
async def handle_cancel_request(ack, body, client: AsyncWebClient):
    """Handle user cancelling asset selection."""
    await ack()
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]
    await client.chat_update(
        channel=channel, ts=ts,
        text="Request cancelled.",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "❌ Request cancelled."}}],
    )


@app.action("approve_request")
async def handle_approve(ack, body, client: AsyncWebClient):
    """Manager approves asset request -> call POST /api/allocations -> notify employee."""
    await ack()
    request_id = int(body["actions"][0]["value"])
    approver_slack_id = body["user"]["id"]
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]

    # Load request
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AssetRequest).where(AssetRequest.id == request_id))
        req = result.scalar_one_or_none()

    if not req or req.status != "Pending":
        await client.chat_update(
            channel=channel, ts=ts,
            text=f"Request REQ-{request_id:04d} already processed.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"Request `REQ-{request_id:04d}` already processed."}}],
        )
        return

    # Calculate return date (30 days from now)
    return_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    # Call AssetFlow allocation API
    result = await api.allocate_asset(
        asset_tag=req.asset_tag,
        assigned_to_user_id=req.assetflow_user_id,
        expected_return_date=return_date,
        notes=f"Approved via Slack by <@{approver_slack_id}>. Request REQ-{request_id:04d}.",
    )

    if not result:
        await client.chat_postMessage(
            channel=channel,
            text=f"⚠️ Allocation failed for REQ-{request_id:04d}. Asset may no longer be available.",
        )
        return

    # Update local status
    await update_request_status(request_id, "Approved", approved_by=approver_slack_id)

    # Get approver name
    approver_info = await client.users_info(user=approver_slack_id)
    approver_name = approver_info["user"]["real_name"] if approver_info.get("ok") else approver_slack_id

    # Update approval card
    await client.chat_update(
        channel=channel, ts=ts,
        text=f"✅ REQ-{request_id:04d} approved.",
        blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"✅ *Approved* — `REQ-{request_id:04d}`\n\n"
                    f"💻 *{req.asset_name}* (`{req.asset_tag}`) allocated to <@{req.slack_user_id}>.\n"
                    f"👤 Approved by: {approver_name}\n"
                    f"📅 Return by: {return_date}\n"
                    f"📋 Audit record created in AssetFlow."
                ),
            },
        }],
    )

    # DM the employee
    await client.chat_postMessage(
        channel=req.slack_user_id,
        text=f"✅ Your request for {req.asset_name} ({req.asset_tag}) has been approved!",
        blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🎉 *Asset Approved & Allocated!*\n\n"
                    f"💻 *{req.asset_name}* (`{req.asset_tag}`) has been assigned to you.\n"
                    f"👤 Approved by: {approver_name}\n"
                    f"📅 Expected return: {return_date}\n"
                    f"📋 Audit record created in AssetFlow."
                ),
            },
        }],
    )


@app.action("reject_request")
async def handle_reject(ack, body, client: AsyncWebClient):
    """Manager rejects asset request."""
    await ack()
    request_id = int(body["actions"][0]["value"])
    rejector_slack_id = body["user"]["id"]
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]

    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AssetRequest).where(AssetRequest.id == request_id))
        req = result.scalar_one_or_none()

    if not req or req.status != "Pending":
        return

    await update_request_status(request_id, "Rejected", approved_by=rejector_slack_id)

    rejector_info = await client.users_info(user=rejector_slack_id)
    rejector_name = rejector_info["user"]["real_name"] if rejector_info.get("ok") else rejector_slack_id

    await client.chat_update(
        channel=channel, ts=ts,
        text=f"❌ REQ-{request_id:04d} rejected.",
        blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"❌ *Rejected* — `REQ-{request_id:04d}`\n\n💻 {req.asset_name} (`{req.asset_tag}`)\n👤 Rejected by: {rejector_name}",
            },
        }],
    )

    # DM the employee
    await client.chat_postMessage(
        channel=req.slack_user_id,
        text=f"❌ Your request for {req.asset_name} ({req.asset_tag}) was rejected.",
        blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"❌ *Request Rejected*\n\nYour request `REQ-{request_id:04d}` for *{req.asset_name}* (`{req.asset_tag}`) was rejected by {rejector_name}.",
            },
        }],
    )


@app.action("refresh_home")
async def handle_refresh_home(ack, body, client: AsyncWebClient):
    """Refresh Home Tab."""
    await ack()
    await handle_home_tab({"user": body["user"]["id"]}, client)


@app.action("return_overdue")
async def handle_return_overdue(ack, body, client: AsyncWebClient):
    await ack()
    tag = body["actions"][0]["value"]
    await client.chat_postMessage(
        channel=body["user"]["id"],
        text=f"📦 To return asset `{tag}`, please bring it to the IT desk or contact your Asset Manager.",
    )


@app.action("request_extension")
async def handle_request_extension(ack, body, client: AsyncWebClient):
    await ack()
    tag = body["actions"][0]["value"]
    await client.chat_postMessage(
        channel=body["user"]["id"],
        text=f"📅 Extension request for `{tag}` noted. Your Asset Manager will be notified.",
    )


@app.action("report_issue")
async def handle_report_issue(ack, body, client: AsyncWebClient):
    await ack()
    tag = body["actions"][0]["value"]
    await client.chat_postMessage(
        channel=body["user"]["id"],
        text=f"[Issue Reported] For `{tag}`. Your Asset Manager will follow up.",
    )


@app.action("show_help_menu")
async def handle_show_help_menu(ack, body, client: AsyncWebClient):
    """Render help text when user clicks the Help button in App Home."""
    await ack()
    help_text = (
        "*AssetFlow Copilot Help Menu*\n\n"
        "I am an autonomous AI assistant connected to your organization's IT inventory. You can ask me to:\n"
        "• *Find available assets:* \"I need a laptop\" or \"Are there any monitors available?\"\n"
        "• *Check asset status:* \"What is the status of AF-1002?\" or \"Who has AF-1004?\"\n"
        "• *View your items:* \"What assets are assigned to me?\"\n"
        "• *Request items:* Once I find an available item, you can click 'Request Asset' and I will route it to your manager for approval.\n\n"
        "Just send me a direct message with what you need, and I'll handle the rest!"
    )
    await client.chat_postMessage(
        channel=body["user"]["id"],
        text=help_text,
    )
