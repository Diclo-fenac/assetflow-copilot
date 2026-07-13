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
from app.db.database import AsyncSessionLocal, AssetRequest
from app.agent.langgraph_agent import run_agent
from app.services import assetflow_api as api

logger = logging.getLogger(__name__)

app = AsyncApp(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
)


import re

# ── Helpers ──────────────────────────────────────────────────────────────────

class MockUserMapping:
    def __init__(self, af_id, email):
        self.assetflow_user_id = af_id
        self.email = email

async def get_user_mapping(slack_user_id: str) -> MockUserMapping | None:
    logger.info(f"[DEBUG] get_user_mapping called for Slack user: {slack_user_id}")
    logger.info(f"[DEBUG] Bot calling backend URL: {settings.assetflow_api_url} with Org ID: {settings.assetflow_org_id}")
    members = await api.get_members()
    if not members:
        logger.error("[DEBUG] api.get_members() returned None or empty list")
        return None
    logger.info(f"[DEBUG] Successfully retrieved {len(members)} members from backend")
    for m in members:
        u = m.get("User")
        if u:
            db_slack_id = u.get("slack_user_id")
            logger.info(f"[DEBUG] Comparing Slack ID '{slack_user_id}' with DB User '{u.get('email')}' (Slack ID in DB: '{db_slack_id}')")
            if db_slack_id == slack_user_id:
                logger.info(f"[DEBUG] Success! Match found for user_id={u['id']}")
                return MockUserMapping(u["id"], u["email"])
    logger.warning(f"[DEBUG] No match found in DB for Slack user: {slack_user_id}")
    return None


async def get_tenant(slack_workspace_id: str):
    return None


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
                    "value": json.dumps({"transfer_id": request_id, "slack_user_id": requester_name.strip("<@>")}),
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": "reject_request",
                    "value": json.dumps({"transfer_id": request_id, "slack_user_id": requester_name.strip("<@>")}),
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

    # Check for Audit start request
    audit_match = re.search(r'start an audit for\s+(.+)', text_lower, re.IGNORECASE)
    if audit_match:
        dept_name = audit_match.group(1).strip().strip(".?!")
        await start_bot_auditor(slack_user_id, dept_name, say, client)
        return

    needs_asset = any(kw in text_lower for kw in ["need", "want", "request", "get me", "looking for", "require"])
    if needs_asset:
        # Extract category hint
        category = None
        db_category_name = None
        for hint, db_cat in [
            ("laptop", "Laptops"),
            ("monitor", "Monitors"),
            ("keyboard", "Accessories"),
            ("mouse", "Accessories"),
            ("trackpad", "Accessories"),
            ("hub", "Accessories"),
            ("charger", "Accessories"),
            ("phone", "Accessories"),
            ("tablet", "Accessories"),
            ("headset", "AV Equipment"),
            ("webcam", "AV Equipment"),
            ("microphone", "AV Equipment"),
            ("speakerphone", "AV Equipment"),
            ("av", "AV Equipment"),
            ("chair", "Furniture"),
            ("desk", "Furniture"),
            ("furniture", "Furniture")
        ]:
            if hint in text_lower:
                category = hint.capitalize()
                db_category_name = db_cat
                break

        assets = await api.list_assets(status="Available")
        if (db_category_name or category) and assets:
            cats = await api.get_categories()
            cat_id = None
            if cats:
                for c in cats:
                    target_name = (db_category_name or category).lower()
                    c_name_lower = c["name"].lower()
                    if c_name_lower == target_name or c_name_lower == target_name + "s" or target_name in c_name_lower:
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
    channel_id = event.get("channel", "default")
    thread_ts = event.get("thread_ts", event.get("ts", ""))
    thread_id = f"{channel_id}:{thread_ts}" if thread_ts else channel_id

    response = await run_agent(text, context, thread_id=thread_id)
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

    # Check if user asking for available assets -> use Block Kit
    text_lower = text.lower()

    # Check for Audit start request
    audit_match = re.search(r'start an audit for\s+(.+)', text_lower, re.IGNORECASE)
    if audit_match:
        dept_name = audit_match.group(1).strip().strip(".?!")
        await start_bot_auditor(slack_user_id, dept_name, say, client)
        return

    needs_asset = any(kw in text_lower for kw in ["need", "want", "request", "get me", "looking for", "require"])
    if needs_asset:
        # Extract category hint
        category = None
        db_category_name = None
        for hint, db_cat in [
            ("laptop", "Laptops"),
            ("monitor", "Monitors"),
            ("keyboard", "Accessories"),
            ("mouse", "Accessories"),
            ("trackpad", "Accessories"),
            ("hub", "Accessories"),
            ("charger", "Accessories"),
            ("phone", "Accessories"),
            ("tablet", "Accessories"),
            ("headset", "AV Equipment"),
            ("webcam", "AV Equipment"),
            ("microphone", "AV Equipment"),
            ("speakerphone", "AV Equipment"),
            ("av", "AV Equipment"),
            ("chair", "Furniture"),
            ("desk", "Furniture"),
            ("furniture", "Furniture")
        ]:
            if hint in text_lower:
                category = hint.capitalize()
                db_category_name = db_cat
                break

        assets = await api.list_assets(status="Available")
        if (db_category_name or category) and assets:
            cats = await api.get_categories()
            cat_id = None
            if cats:
                for c in cats:
                    target_name = (db_category_name or category).lower()
                    c_name_lower = c["name"].lower()
                    if c_name_lower == target_name or c_name_lower == target_name + "s" or target_name in c_name_lower:
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

    channel_id = event.get("channel", "default")
    thread_ts = event.get("thread_ts", event.get("ts", ""))
    thread_id = f"{channel_id}:{thread_ts}" if thread_ts else channel_id

    response = await run_agent(text, context, thread_id=thread_id)
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
            text="[Error] Your Slack account is not linked to AssetFlow. Contact your admin.",
            blocks=[],
        )
        return

    # Call Backend API to create TransferRequest
    transfer_res = await api.request_transfer(
        asset_tag=tag,
        requested_new_holder_id=mapping.assetflow_user_id,
        reason="Requested via Slack"
    )

    if not transfer_res or "transfer_request" not in transfer_res:
        await client.chat_update(
            channel=channel, ts=ts,
            text=f"[Error] Failed to create request. The asset may no longer be available.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"[Error] Failed to create request. The asset may no longer be available."}}],
        )
        return

    transfer_id = transfer_res["transfer_request"]["id"]

    # Save request locally (mostly for App Home tab)
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
        text=f"[Submitted] Request `TRF-{transfer_id}` submitted for *{name}* (`{tag}`). Awaiting manager approval.",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"[Submitted] Request `TRF-{transfer_id}` submitted for *{name}* (`{tag}`).\n\n*Status:* Awaiting manager approval."},
        }],
    )

    # Get user info for display name
    requester_name = f"<@{slack_user_id}>"
    try:
        user_info = await client.users_info(user=slack_user_id)
        if user_info.get("ok"):
            requester_name = user_info["user"]["real_name"]
    except Exception:
        pass

    # Post approval card to approvals channel
    tenant = await get_tenant(slack_workspace_id)
    approvals_channel = tenant.approvals_channel_id if tenant else None
    if not approvals_channel:
        approvals_channel = settings.slack_approvals_channel

    if approvals_channel:
        approval_blocks = build_approval_block(transfer_id, requester_name, tag, name, "Requested via Slack")
        resp = await client.chat_postMessage(
            channel=approvals_channel,
            blocks=approval_blocks,
            text=f"New asset request TRF-{transfer_id} from {requester_name}",
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
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "[Cancelled] Request cancelled."}}],
    )


@app.action("approve_request")
async def handle_approve(ack, body, client: AsyncWebClient):
    """Manager approves asset request -> call PATCH /api/allocations/transfers/:id/approve -> notify employee."""
    await ack()
    data = json.loads(body["actions"][0]["value"])
    transfer_id = data["transfer_id"]
    requester_slack_id = data.get("slack_user_id")
    
    approver_slack_id = body["user"]["id"]
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]

    # Call AssetFlow transfer approve API
    result = await api.approve_transfer(transfer_id)

    if not result:
        await client.chat_update(
            channel=channel, ts=ts,
            text=f"⚠️ Approval failed for TRF-{transfer_id}. Asset may no longer be available.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"⚠️ Approval failed for `TRF-{transfer_id}`. Asset may no longer be available, or the request was already processed in the frontend."}}],
        )
        return

    # Get approver name
    approver_name = f"<@{approver_slack_id}>"
    try:
        approver_info = await client.users_info(user=approver_slack_id)
        if approver_info.get("ok"):
            approver_name = approver_info["user"]["real_name"]
    except Exception:
        pass

    # Update approval card
    await client.chat_update(
        channel=channel, ts=ts,
        text=f"[Approved] TRF-{transfer_id} approved.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"[Approved] `TRF-{transfer_id}`\n\n"
                        f" Asset has been allocated/transferred to <@{requester_slack_id}>.\n"
                        f" Approved by: {approver_name}\n"
                        f" Audit record created in AssetFlow."
                    ),
                },
            },
        ],
    )

    # DM the employee
    if requester_slack_id:
        await client.chat_postMessage(
            channel=requester_slack_id,
            text=f"[Approved] Your transfer request TRF-{transfer_id} has been approved!",
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"[Asset Approved & Allocated]\n\n"
                        f" Your request `TRF-{transfer_id}` has been approved and assigned to you.\n"
                        f" Approved by: {approver_name}\n"
                        f" Audit record created in AssetFlow."
                    ),
                },
            }],
        )


@app.action("reject_request")
async def handle_reject(ack, body, client: AsyncWebClient):
    """Manager rejects asset request."""
    await ack()
    data = json.loads(body["actions"][0]["value"])
    transfer_id = data["transfer_id"]
    requester_slack_id = data.get("slack_user_id")
    
    rejector_slack_id = body["user"]["id"]
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]

    result = await api.reject_transfer(transfer_id, reason=f"Rejected via Slack by <@{rejector_slack_id}>")

    if not result:
        await client.chat_update(
            channel=channel, ts=ts,
            text=f"⚠️ Rejection failed for TRF-{transfer_id}.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"⚠️ Rejection failed for `TRF-{transfer_id}`. The request may have already been processed in the frontend."}}],
        )
        return

    rejector_name = f"<@{rejector_slack_id}>"
    try:
        rejector_info = await client.users_info(user=rejector_slack_id)
        if rejector_info.get("ok"):
            rejector_name = rejector_info["user"]["real_name"]
    except Exception:
        pass

    await client.chat_update(
        channel=channel, ts=ts,
        text=f"[Rejected] TRF-{transfer_id} rejected.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"[Rejected] `TRF-{transfer_id}`\n\n*Rejected by:* {rejector_name}",
                },
            },
        ],
    )

    # DM the employee
    if requester_slack_id:
        await client.chat_postMessage(
            channel=requester_slack_id,
            text=f"[Rejected] Your transfer request TRF-{transfer_id} was rejected.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"[Request Rejected]\n\nYour request `TRF-{transfer_id}` was rejected by {rejector_name}.",
                    },
                },
            ],
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
        text=f" To return asset `{tag}`, please bring it to the IT desk or contact your Asset Manager.",
    )


@app.action("request_extension")
async def handle_request_extension(ack, body, client: AsyncWebClient):
    await ack()
    tag = body["actions"][0]["value"]
    await client.chat_postMessage(
        channel=body["user"]["id"],
        text=f" Extension request for `{tag}` noted. Your Asset Manager will be notified.",
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

# ── Bot Auditor Functions ────────────────────────────────────────────────────

async def start_bot_auditor(slack_user_id: str, dept_name: str, say, client: AsyncWebClient):
    """Start an automated Slack audit for a given department."""
    await say(f"Starting an automated Slack Audit for the {dept_name.capitalize()} department... Please wait.")
    
    depts = await api.get_departments()
    dept = next((d for d in depts if d["name"].lower() == dept_name.lower()), None)
    if not dept:
        await say(f"Could not find department '{dept_name}'. Available: {', '.join([d['name'] for d in depts]) if depts else 'None'}")
        return
        
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
    
    cycle = await api.create_audit_cycle(
        name=f"{dept['name']} Slack Audit - {start_date}",
        department_id=dept["id"],
        start_date=start_date,
        end_date=end_date
    )
    if not cycle or "audit_cycle" not in cycle:
        await say("Failed to create audit cycle.")
        return
        
    cycle_id = cycle["audit_cycle"]["id"]
    
    mapping = await get_user_mapping(slack_user_id)
    if mapping:
        members = await api.get_members()
        admin_ids = [m['User']['id'] for m in members if m.get('role') == 'Admin']
        await api.assign_auditors(cycle_id, [mapping.assetflow_user_id] + admin_ids)
    
    all_assets = await api.list_assets()
    if not all_assets:
        await say("No assets found in the system.")
        return
    dept_assets = [a for a in all_assets if a.get("status") == "Allocated" and a.get("current_holder_id")]
    
    members = await api.get_members()
    dept_member_ids = [m["User"]["id"] for m in members if m.get("Department") and m["Department"]["id"] == dept["id"]]
    
    audit_assets = [a for a in dept_assets if a.get("current_holder_id") in dept_member_ids]
    
    if not audit_assets:
        await say(f"No allocated assets found for {dept['name']}.")
        return
        
    asset_tags = [a["tag"] for a in audit_assets]
    await api.bulk_add_audit_items(cycle_id, asset_tags)
    
    await api.activate_audit_cycle(cycle_id)
    
    cycle_details = await api.get_audit_cycle(cycle_id)
    if not cycle_details or "items" not in cycle_details:
        await say(f"Audit Cycle `#{cycle_id}` started, but failed to fetch items.")
        return
    audit_items = cycle_details["items"]
    
    ping_count = 0
    members = await api.get_members()
    member_map = {m["User"]["id"]: m["User"].get("slack_user_id") for m in members if m.get("User")}
    
    for item in audit_items:
        holder_id = item["Asset"]["current_holder_id"]
        tag = item["Asset"]["tag"]
        name = item["Asset"]["name"]
        item_id = item["id"]
        
        slack_id = member_map.get(holder_id)
        if slack_id:
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*IT Audit Check*\n\nHi! We are conducting an automated audit for {dept['name']}.\n\nDo you currently have this asset in your possession?\n\n*{name}* (`{tag}`)"}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Yes, I have it"}, "action_id": "audit_yes", "value": str(item_id), "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "No, I don't"}, "action_id": "audit_no", "value": str(item_id), "style": "danger"},
                ]}
            ]
            await client.chat_postMessage(channel=slack_id, blocks=blocks, text=f"Audit Check: Do you have {name} ({tag})?")
            ping_count += 1
                
    await say(f"Audit Cycle `#{cycle_id}` started successfully! 🚀\nSent {ping_count} Slack DMs to {dept['name']} employees.")


@app.action("audit_yes")
async def handle_audit_yes(ack, body, client: AsyncWebClient):
    await ack()
    item_id = int(body["actions"][0]["value"])
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]
    
    res = await api.mark_audit_item(item_id, "Verified", "Verified via Slack Bot")
    if res:
        await client.chat_update(
            channel=channel, ts=ts,
            text="Thanks for confirming! Asset verified.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "✅ *Verified!* Thanks for confirming you have this asset."}}]
        )
    else:
        await client.chat_update(
            channel=channel, ts=ts,
            text="⚠️ Failed to verify asset. It may have already been verified.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "⚠️ Failed to verify asset. It may have already been verified."}}]
        )

@app.action("audit_no")
async def handle_audit_no(ack, body, client: AsyncWebClient):
    await ack()
    item_id = int(body["actions"][0]["value"])
    channel = body["channel"]["id"]
    ts = body["message"]["ts"]
    
    res = await api.mark_audit_item(item_id, "Missing", "User reported missing via Slack Bot")
    if res:
        await client.chat_update(
            channel=channel, ts=ts,
            text="Asset marked as Missing.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "🚨 *Marked as Missing.* An IT Admin has been notified."}}]
        )
    else:
        await client.chat_update(
            channel=channel, ts=ts,
            text="⚠️ Failed to update asset status.",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "⚠️ Failed to update asset status. It may have already been verified."}}]
        )

@app.command("/link-account")
async def handle_link_account(ack, respond, command):
    await ack()
    text = command.get("text", "").strip()
    slack_user_id = command.get("user_id")
    
    if not text or "@" not in text:
        await respond("Usage: /link-account <your-email@example.com>")
        return
        
    res = await api.link_slack_account(text, slack_user_id)
    if res:
        await respond(f"✅ Successfully linked your Slack account to {text} in AssetFlow!")
    else:
        await respond("❌ Failed to link account. Please check the email and try again.")
