from __future__ import annotations

import asyncio

from main import main as app_main


async def main():
    await app_main()


if __name__ == "__main__":
    asyncio.run(main())
