"""Logs por etapa con tiempos."""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger("alivia_edge.stages")


@contextmanager
def stage(name: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.info("etapa %s: %.0f ms", name, (time.perf_counter() - start) * 1000)
