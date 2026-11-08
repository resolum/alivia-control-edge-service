"""Intérprete con Qwen2.5 en Ollama. Usa solo la stdlib para HTTP; se invoca desde un executor."""

import json
import logging
import urllib.error
import urllib.request

from alivia_edge.devices.catalog import DeviceCatalog
from alivia_edge.logs import stage
from alivia_edge.nlu.contract import (
    InterpreterError,
    LlmResult,
    ProposedAction,
    parse_llm_output,
    response_schema,
)
from alivia_edge.nlu.prompt import build_messages

logger = logging.getLogger(__name__)


class OllamaInterpreter:
    def __init__(self, url: str, model: str, timeout_s: float, catalog: DeviceCatalog):
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout_s
        self._catalog = catalog
        self._schema = response_schema(catalog)

    def interpret(
        self,
        text: str,
        states: dict[str, str],
        pending: tuple[ProposedAction, ...] = (),
        earlier_request: str = "",
    ) -> LlmResult:
        messages = build_messages(self._catalog, states, text, pending, earlier_request)
        with stage("llm"):
            raw = self._chat(messages)
        logger.info("llm respondió: %s", raw)
        return parse_llm_output(raw, self._catalog)

    def warm_up(self) -> None:
        """Carga el modelo en memoria (keep_alive=-1) para que la primera orden no espere."""
        self._chat([{"role": "user", "content": "{}"}])

    def _chat(self, messages: list[dict[str, str]]) -> str:
        body = json.dumps(
            {
                "model": self._model,
                "messages": messages,
                "stream": False,
                "format": self._schema,
                "keep_alive": -1,
                "options": {"temperature": 0.15},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.load(response)["message"]["content"]
        except (
            urllib.error.URLError,
            TimeoutError,
            KeyError,
            json.JSONDecodeError,
        ) as error:
            raise InterpreterError(f"Ollama no respondió: {error}") from error
