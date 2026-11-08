"""`python -m alivia_edge` arranca el pipeline de voz."""

import asyncio
import logging

from alivia_edge.runtime import run

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run())
