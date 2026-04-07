import asyncio
import os
from dotenv import load_dotenv
from services.gemini_casual_service import get_grandma_casual_reply

load_dotenv()

async def test_casual_flow():
    print("--- Multi-turn Context Test ---")
    
    # 1st turn
    user1 = "할매, 요즘 코인이 왜 이래?"
    print(f"User: {user1}")
    reply1 = await get_grandma_casual_reply(user1)
    print(f"Granny: {reply1}")
    
    history = [
        {"role": "user", "content": user1},
        {"role": "assistant", "content": reply1}
    ]
    
    # 2nd turn - relative to context
    user2 = "방금 그 말 진짜야? 믿어도 돼?"
    print(f"\nUser: {user2}")
    reply2 = await get_grandma_casual_reply(user2, history)
    print(f"Granny: {reply2}")
    
    # 3rd turn - tease her
    history.extend([
        {"role": "user", "content": user2},
        {"role": "assistant", "content": reply2}
    ])
    user3 = "할매 치매 온 거 아니지?"
    print(f"\nUser: {user3}")
    reply3 = await get_grandma_casual_reply(user3, history)
    print(f"Granny: {reply3}")

if __name__ == "__main__":
    if not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
        print("Error: API KEY not found in .env")
    else:
        asyncio.run(test_casual_flow())
