"""Local coordinator only; production invokes /internal/tick using Cloud Scheduler."""

import asyncio

import httpx

from .config import Settings


async def main():
    settings = Settings()
    async with httpx.AsyncClient(timeout=180) as client:
        while True:
            response = await client.post(
                "http://127.0.0.1:8000/internal/tick", headers={"X-Worker-Token": settings.worker_token}
            )
            print(f"Worker tick: HTTP {response.status_code}", flush=True)
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
