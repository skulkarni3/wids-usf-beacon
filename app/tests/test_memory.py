"""
test_memory.py — run directly, not through pytest:

    cd /Users/shruti/WiDS/wildfire-exits
    python -m app.tests.test_memory

Requires QDRANT_URL, QDRANT_API_KEY, OPENAI_API_KEY, and ANTHROPIC_API_KEY
to be set in app/.env (loaded automatically).
"""

import asyncio
import sys
import os

# Ensure project root is on the path when run directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.memory_service import add_memory, search_memories

TEST_USER = "e13a9d7e-7ae1-40d1-a626-2cb7a7ab6393"


async def test():
    print(f"\n=== Beacon Memory Test ===")
    print(f"User: {TEST_USER}\n")

    # 1. Write a memory
    print("Step 1: Writing memory...")
    await add_memory(TEST_USER, [
        {"role": "user",      "content": "My grandad is visiting for the summer, he uses a walker"},
        {"role": "assistant", "content": "Thanks for letting me know. I'll keep that in mind for your evacuation plan — I'll make sure we account for his mobility needs."},
    ])
    print("  Write done.\n")

    # 2. Short pause so the vector write can propagate
    print("Step 2: Waiting 2s for Qdrant to index...")
    await asyncio.sleep(2)

    # 3. Read it back with a targeted query
    print("Step 3: Searching for household members and mobility needs...")
    result = await search_memories(TEST_USER, "household members and mobility needs")
    print(f"  Retrieved:\n{result or '  (no results)'}\n")

    # 4. Read with the default broad query (what session/start uses)
    print("Step 4: Searching with default session-start query...")
    result2 = await search_memories(TEST_USER)
    print(f"  Retrieved:\n{result2 or '  (no results)'}\n")

    print("=== Test complete ===")


if __name__ == "__main__":
    asyncio.run(test())
