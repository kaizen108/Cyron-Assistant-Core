#!/usr/bin/env python3
"""Quick setup verification script for Phase 1."""

import sys
import asyncio
import aiohttp


async def test_backend_health() -> bool:
    """Test backend health endpoint."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8000/health") as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Backend health check passed: {data}")
                    return True
                else:
                    print(f"❌ Backend health check failed: Status {response.status}")
                    return False
    except Exception as e:
        print(f"❌ Backend health check failed: {e}")
        return False


async def test_backend_relay() -> bool:
    """Test backend relay endpoint."""
    try:
        payload = {
            "guild_id": "123456789012345678",
            "channel_id": "987654321098765432",
            "user_id": "111222333444555666",
            "content": "Test message",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:8000/relay",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Backend relay test passed: {data}")
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ Backend relay test failed: Status {response.status}, {error_text}")
                    return False
    except Exception as e:
        print(f"❌ Backend relay test failed: {e}")
        return False


def check_env_file() -> bool:
    """Check if .env file exists."""
    import os
    if os.path.exists(".env"):
        print("✅ .env file exists")
        return True
    else:
        print("⚠️  .env file not found. Please create it from .env.example")
        return False


def main() -> None:
    """Run all tests."""
    print("=" * 50)
    print("Phase 1 Setup Verification")
    print("=" * 50)
    print()

    # Check .env file
    env_ok = check_env_file()
    print()

    # Test backend (only if running)
    print("Testing backend endpoints (make sure backend is running)...")
    try:
        results = asyncio.run(
            asyncio.gather(
                test_backend_health(),
                test_backend_relay(),
                return_exceptions=True,
            )
        )
        health_ok = results[0] if isinstance(results[0], bool) else False
        relay_ok = results[1] if isinstance(results[1], bool) else False

        print()
        if health_ok and relay_ok:
            print("✅ All backend tests passed!")
        else:
            print("❌ Some backend tests failed. Make sure backend is running:")
            print("   uvicorn backend.main:app --reload")
    except Exception as e:
        print(f"⚠️  Could not test backend: {e}")
        print("   Make sure backend is running first")

    print()
    print("=" * 50)
    print("Next steps:")
    print("1. Create .env file with your DISCORD_TOKEN")
    print("2. Start backend: uvicorn backend.main:app --reload")
    print("3. Start bot: python bot/main.py")
    print("4. Invite bot to Discord server")
    print("5. Run /setup command in Discord")
    print("6. Run /create-ticket command")
    print("7. Send a message in the ticket channel")
    print("=" * 50)


if __name__ == "__main__":
    main()

