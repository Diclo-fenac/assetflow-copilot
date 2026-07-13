import asyncio
from app.agent.langgraph_agent import run_agent

async def test():
    print("Testing lookup_asset...")
    response = await run_agent("What is the status of AF-0005?", context="Slack user U0BGW2TB23C maps to AssetFlow user_id=1")
    print("\n--- RESPONSE ---")
    print(response)

    print("\nTesting search_available_assets...")
    response = await run_agent("I need a laptop.", context="Slack user U0BGW2TB23C maps to AssetFlow user_id=1")
    print("\n--- RESPONSE ---")
    print(response)

if __name__ == "__main__":
    asyncio.run(test())
