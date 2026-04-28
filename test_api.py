#!/usr/bin/env python3
"""Basic checks for the live stream API."""

import asyncio
import os

import httpx

BASE_URL = os.getenv("BASE_URL", "http://localhost:8335")


async def test_health() -> bool:
    print("Testing health endpoint...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{BASE_URL}/health")
        if response.status_code != 200:
            print(f"Health check failed: {response.status_code} - {response.text}")
            return False
        print(f"Health check passed: {response.json()}")
        return True
    except Exception as exc:
        print(f"Health check error: {exc}")
        return False


async def test_active_streams() -> bool:
    print("Testing active streams endpoint...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{BASE_URL}/camera/active-streams")
        if response.status_code != 200:
            print(f"Active streams failed: {response.status_code} - {response.text}")
            return False
        print(f"Active streams response: {response.json()}")
        return True
    except Exception as exc:
        print(f"Active streams error: {exc}")
        return False


async def test_stop_missing_stream() -> bool:
    print("Testing stop endpoint for missing client...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{BASE_URL}/camera/stop?client_id=test-user")
        if response.status_code == 404:
            print("Stop endpoint returned expected 404 for missing stream")
            return True
        print(f"Unexpected stop response: {response.status_code} - {response.text}")
        return False
    except Exception as exc:
        print(f"Stop endpoint error: {exc}")
        return False


async def test_stream_detail_missing() -> bool:
    print("Testing stream detail endpoint for missing client...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{BASE_URL}/camera/active-streams/test-user")
        if response.status_code == 404:
            print("Stream detail endpoint returned expected 404 for missing stream")
            return True
        print(f"Unexpected detail response: {response.status_code} - {response.text}")
        return False
    except Exception as exc:
        print(f"Stream detail endpoint error: {exc}")
        return False


async def test_stop_all() -> bool:
    print("Testing stop-all endpoint...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{BASE_URL}/camera/stop-all")
        if response.status_code != 200:
            print(f"Stop-all failed: {response.status_code} - {response.text}")
            return False
        print(f"Stop-all response: {response.json()}")
        return True
    except Exception as exc:
        print(f"Stop-all endpoint error: {exc}")
        return False


async def main():
    print("Starting Hikvision Live Stream API tests\n")
    tests = [
        ("Health", test_health()),
        ("Active Streams", test_active_streams()),
        ("Missing Stream Detail", test_stream_detail_missing()),
        ("Stop Missing Stream", test_stop_missing_stream()),
        ("Stop All", test_stop_all()),
    ]

    results = []
    for test_name, test_coro in tests:
        result = await test_coro
        results.append((test_name, result))
        print()

    passed = sum(1 for _, result in results if result)
    print("TEST SUMMARY")
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{status} {test_name}")
    print(f"\nTotal: {passed}/{len(results)} tests passed")


if __name__ == "__main__":
    asyncio.run(main())
