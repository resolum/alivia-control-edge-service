"""Prompt del sistema para Qwen: dispositivos con su estado, los dos modos y ejemplos en español."""

import json

from alivia_edge.devices.catalog import DeviceCatalog
from alivia_edge.nlu.contract import ProposedAction

EXAMPLES = (
    (
        '"abre la puerta"',
        {
            "mode": "propose",
            "speech": "¿Abro la puerta?",
            "actions": [{"device": "puerta", "action": "open"}],
        },
    ),
    (
        '"prende la luz"',
        {
            "mode": "propose",
            "speech": "¿Enciendo la luz?",
            "actions": [{"device": "luz_cuarto", "action": "on"}],
        },
    ),
    (
        '"apaga la luz y cierra la ventana"',
        {
            "mode": "propose",
            "speech": "¿Apago la luz y cierro la ventana?",
            "actions": [
                {"device": "luz_cuarto", "action": "off"},
                {"device": "ventana", "action": "close"},
            ],
        },
    ),
    (
        '"hace mucho calor"',
        {"mode": "clarify", "speech": "¿Quieres que abra la ventana?", "actions": []},
    ),
    (
        '"ábrela"',
        {
            "mode": "clarify",
            "speech": "¿Qué quieres abrir, la puerta o la ventana?",
            "actions": [],
        },
    ),
    (
        '"ya me voy a dormir"',
        {
            "mode": "propose",
            "speech": "¿Apago la luz, cierro la ventana y la puerta?",
            "actions": [
                {"device": "luz_cuarto", "action": "off"},
                {"device": "ventana", "action": "close"},
                {"device": "puerta", "action": "close"},
            ],
        },
    ),
    (
        '"cierra todo"',
        {
            "mode": "propose",
            "speech": "¿Cierro la puerta y la ventana?",
            "actions": [
                {"device": "puerta", "action": "close"},
                {"device": "ventana", "action": "close"},
            ],
        },
    ),
    (
        '"cuéntame un chiste"',
        {
            "mode": "clarify",
            "speech": "Solo puedo controlar la puerta, la ventana y la luz del cuarto.",
            "actions": [],
        },
    ),
)

REFINE_EXAMPLE = (
    (
        'Acciones pendientes: [{"device":"puerta","action":"open"},{"device":"luz_cuarto","action":"on"}]. '
        'La persona respondió: "sí, pero la puerta no"'
    ),
    {
        "mode": "propose",
        "speech": "¿Enciendo la luz?",
        "actions": [{"device": "luz_cuarto", "action": "on"}],
    },
)


def build_system_prompt(catalog: DeviceCatalog, states: dict[str, str]) -> str:
    device_lines = "\n".join(
        f"- {device.name}: acciones {', '.join(device.actions)}; estado actual: {states.get(device.name, 'desconocido')}"
        for device in catalog.devices
    )
    examples = "\n".join(
        f"Persona: {text}\nRespuesta: {json.dumps(answer, ensure_ascii=False)}"
        for text, answer in EXAMPLES
    )
    refine_text, refine_answer = REFINE_EXAMPLE
    return (
        "Eres el intérprete de órdenes de voz de Alivia, un asistente de hogar. "
        "Conviertes lo que dice la persona en un JSON. Responde SOLO con JSON.\n\n"
        f"Dispositivos que existen (no existe ningún otro):\n{device_lines}\n\n"
        'Formato: {"mode": "propose" | "clarify", "speech": "frase corta en español, máximo 15 palabras", '
        '"actions": [{"device": "...", "action": "..."}]}\n'
        "- propose: la intención es clara. Lista las acciones; no ejecutas nada, el sistema pedirá confirmación.\n"
        "- clarify: tienes una duda o no hay acción posible. speech es la pregunta o aviso; actions va vacío.\n"
        "Usa solo los dispositivos y acciones de la lista. Si pide algo fuera de la lista, usa clarify.\n"
        "Si te dan acciones pendientes y la persona corrige algo, devuelve la lista final en propose.\n\n"
        f"Ejemplos:\n{examples}\n\n"
        f"Corrección:\nPersona: {refine_text}\nRespuesta: {json.dumps(refine_answer, ensure_ascii=False)}"
    )


def build_messages(
    catalog: DeviceCatalog,
    states: dict[str, str],
    text: str,
    pending: tuple[ProposedAction, ...] = (),
    earlier_request: str = "",
) -> list[dict[str, str]]:
    if pending:
        listed = json.dumps(
            [{"device": a.device, "action": a.action} for a in pending],
            ensure_ascii=False,
        )
        user = f'Acciones pendientes: {listed}. La persona respondió: "{text}"'
    elif earlier_request:
        user = f'La persona {earlier_request}. Ahora respondió: "{text}"'
    else:
        user = f'Persona: "{text}"'
    return [
        {"role": "system", "content": build_system_prompt(catalog, states)},
        {"role": "user", "content": user},
    ]
