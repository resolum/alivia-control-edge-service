"""Máquina de estados explícita de una sesión de voz."""

import logging
import time
from collections.abc import Callable
from enum import StrEnum

logger = logging.getLogger(__name__)


class State(StrEnum):
    IDLE = "IDLE"
    GRABANDO = "GRABANDO"
    PROCESANDO = "PROCESANDO"
    ESPERANDO_CONFIRMACION = "ESPERANDO_CONFIRMACION"
    EJECUTANDO = "EJECUTANDO"


ALLOWED = {
    State.IDLE: {State.GRABANDO, State.PROCESANDO},
    State.GRABANDO: {State.PROCESANDO},
    State.PROCESANDO: {State.ESPERANDO_CONFIRMACION, State.EJECUTANDO},
    State.ESPERANDO_CONFIRMACION: {State.PROCESANDO, State.EJECUTANDO},
    State.EJECUTANDO: set(),
}


class InvalidTransition(RuntimeError):
    pass


class StateMachine:
    """Cualquier estado puede volver a IDLE (error, timeout, desconexión o emergencia)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.state = State.IDLE
        self.entered_at = clock()

    def transition(self, target: State, reason: str = "") -> None:
        if (
            target is not State.IDLE
            and target not in ALLOWED[self.state]
            and target is not self.state
        ):
            raise InvalidTransition(f"{self.state} -> {target} no está permitido")
        if target is not self.state:
            logger.info("estado %s -> %s %s", self.state, target, reason)
            self.state = target
            self.entered_at = self._clock()
