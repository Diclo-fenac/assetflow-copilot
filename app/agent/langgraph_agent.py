"""
LangGraph agent for AssetFlow Slack interactions.
Manages conversational state + MCP tool invocations via Gemini.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.core.config import settings
from app.services import assetflow_api as api


# ── Tools (MCP-style, called by LangGraph) ───────────────────────────────────


@tool
async def lookup_asset(tag: str) -> str:
    """Look up a specific asset by its tag (e.g. AF-0005). Returns owner, status, category, location, condition."""
    data = await api.get_asset(tag)
    if not data:
        return f"Asset {tag} not found."
    holder = data.get("CurrentHolder")
    cat = data.get("Category")
    return (
        f"**{data['name']}** ({data['tag']})\n"
        f"• Status: {data['status']}\n"
        f"• Category: {cat['name'] if cat else 'N/A'}\n"
        f"• Location: {data.get('location', 'N/A')}\n"
        f"• Condition: {data.get('condition', 'N/A')}\n"
        f"• Current Holder: {holder['name'] + ' (' + holder['email'] + ')' if holder else 'Unassigned'}\n"
        f"• Serial: {data.get('serial_number', 'N/A')}"
    )


@tool
async def search_available_assets(search: str | None = None, category_name: str | None = None) -> str:
    """Search for available assets. Optionally filter by search term or category name (e.g. 'Laptop')."""
    # Resolve category_id if category_name given
    category_id = None
    if category_name:
        cats = await api.get_categories()
        if cats:
            for c in cats:
                if c["name"].lower() == category_name.lower():
                    category_id = c["id"]
                    break

    assets = await api.list_assets(status="Available", category_id=category_id, search=search)
    if not assets:
        return "No available assets found matching criteria."

    lines = [f"Found {len(assets)} available asset(s):\n"]
    for a in assets[:10]:  # cap at 10
        cat = a.get("Category")
        lines.append(
            f"• **{a['name']}** ({a['tag']}) — "
            f"Category: {cat['name'] if cat else 'N/A'}, "
            f"Condition: {a.get('condition', 'N/A')}, "
            f"Location: {a.get('location', 'N/A')}"
        )
    return "\n".join(lines)


@tool
async def get_user_assets(assetflow_user_id: int) -> str:
    """Get all assets currently allocated to a specific user by their AssetFlow user ID."""
    assets = await api.list_assets(status=None)
    if not assets:
        return "No assets found."

    user_assets = [a for a in assets if a.get("current_holder_id") == assetflow_user_id and a.get("status") == "Allocated"]
    if not user_assets:
        return "No assets currently allocated to this user."

    lines = [f"User has {len(user_assets)} allocated asset(s):\n"]
    for a in user_assets:
        cat = a.get("Category")
        lines.append(
            f"• **{a['name']}** ({a['tag']}) — "
            f"Category: {cat['name'] if cat else 'N/A'}, "
            f"Condition: {a.get('condition', 'N/A')}, "
            f"Location: {a.get('location', 'N/A')}"
        )
    return "\n".join(lines)


@tool
async def get_overdue_assets() -> str:
    """Get all overdue asset allocations (assets past their expected return date)."""
    data = await api.get_overdue_allocations()
    if not data:
        return "No overdue allocations found."

    lines = [f"Found {len(data)} overdue allocation(s):\n"]
    for al in data:
        asset = al.get("Asset", {})
        user = al.get("User", {})
        lines.append(
            f"• **{asset.get('name', '?')}** ({asset.get('tag', '?')}) — "
            f"Held by: {user.get('name', '?')}, "
            f"Due: {al.get('expected_return_date', '?')}"
        )
    return "\n".join(lines)


@tool
async def create_allocation(asset_tag: str, user_id: int, return_date: str | None = None, notes: str | None = None) -> str:
    """Allocate an asset to a user. Only call after manager approval. Returns confirmation or error."""
    result = await api.allocate_asset(
        asset_tag=asset_tag,
        assigned_to_user_id=user_id,
        expected_return_date=return_date,
        notes=notes,
    )
    if not result:
        return "Allocation failed. Asset may be unavailable or user invalid."
    return f"Allocation successful. {result.get('message', 'Asset assigned.')}"


# ── Agent State ──────────────────────────────────────────────────────────────

TOOLS = [lookup_asset, search_available_assets, get_user_assets, get_overdue_assets, create_allocation]

SYSTEM_PROMPT = """You are AssetFlow Copilot, a professional IT asset management assistant inside Slack.

You help employees with:
1. Looking up assets by tag (e.g. "Who owns AF-0005?")
2. Finding available assets when they need equipment ("I need a laptop")
3. Showing what assets are allocated to them ("What assets do I have?")
4. Checking overdue allocations

RULES:
- Always use the provided tools to get real data. Never make up asset information.
- Use a professional, clean tone. Avoid excessive emojis. Use standard markdown like bolding or bullet points (•).
- When a user asks for an asset, search available ones and recommend up to 3 options.
- You CANNOT directly allocate assets. Asset requests go through a manager approval workflow.
- When recommending assets, list them clearly with tag, name, condition, and location.
- If the user asks for help or is confused, provide a clean, professional list of what you can do (lookup, search, view assigned, request).
- For asset requests, after showing options, tell the user to select one using the interactive buttons below your message.

CONTEXT (injected per request):
{context}
"""


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    context: str


# ── Graph Construction ───────────────────────────────────────────────────────

def build_agent() -> StateGraph:
    """Build and compile the LangGraph agent."""

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.google_api_key,
        temperature=0.3,
    )
    llm_with_tools = llm.bind_tools(TOOLS)

    async def agent_node(state: AgentState) -> dict:
        sys_msg = SystemMessage(content=SYSTEM_PROMPT.format(context=state.get("context", "No additional context.")))
        messages = [sys_msg] + state["messages"]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "__end__"

    tool_node = ToolNode(TOOLS)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "__end__": END})
    graph.add_edge("tools", "agent")

    return graph.compile()


# Singleton compiled agent
agent = build_agent()


async def run_agent(user_message: str, context: str = "") -> str:
    """Run the agent with a user message and optional context. Returns the final text response."""
    result = await agent.ainvoke({
        "messages": [HumanMessage(content=user_message)],
        "context": context,
    })
    # Extract last AI message text
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
    return "I couldn't process that request. Please try again."
