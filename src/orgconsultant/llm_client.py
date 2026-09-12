"""
Cliente LLM compartido — Ollama Cloud (https://ollama.com/api/chat).

Único punto de acceso al modelo de lenguaje en todo el proyecto. Se usa en
EXACTAMENTE dos lugares, ambos ya autorizados por la especificación:
  1. business_alignment.py (Capa 2.5) — clasificación semántica en batch de
     tipo de esfuerzo por ticket, con salida estructurada forzada.
  2. agent.py (orquestación, Fase 8) — el LLM que decide qué tool invocar
     e interpreta resultados (tool use / function calling real).

En ningún otro módulo del proyecto se debe importar este cliente — todas
las demás capas (flow_metrics, handoff_graph, clustering, severity,
org_blocks, simulation) son código determinista puro, sin LLM.

Nota sobre el proveedor: no había ninguna ANTHROPIC_API_KEY ni
OPENAI_API_KEY con crédito disponibles en este entorno. El usuario
proporcionó una API key de Ollama Cloud (ollama.com), que sí funciona real
y gratuitamente para tool use y salida estructurada (verificado con curl
antes de construir este cliente). Modelo usado: `gpt-oss:120b` (modelo
open-weight de OpenAI servido por Ollama Cloud). Esto debe declararse en el
Anexo Metodológico del informe final.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_CHAT_URL = "https://ollama.com/api/chat"
DEFAULT_MODEL = "gpt-oss:120b"
MAX_RETRIES = 5
RETRY_BASE_DELAY_SECONDS = 3.0


class LLMError(RuntimeError):
    pass


def _get_api_key() -> str:
    key = os.environ.get("OLLAMA_API_KEY")
    if not key:
        raise LLMError(
            "OLLAMA_API_KEY no está configurada (revisa .env). Este cliente "
            "es la única vía autorizada al LLM en el proyecto — no inventes "
            "un fallback silencioso en el código que lo llama."
        )
    return key


def chat(
    messages: list[dict[str, str]],
    model: str = DEFAULT_MODEL,
    response_schema: dict | None = None,
    tools: list[dict] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Llamada cruda al endpoint de chat de Ollama Cloud.

    Args:
        messages: lista de {"role": ..., "content": ...} estilo OpenAI/Ollama.
        response_schema: si se pasa, se envía como `format` (JSON Schema) —
            fuerza salida estructurada. IMPORTANTE (verificado empíricamente):
            para que el modelo respete el schema y no envuelva la respuesta
            en texto/markdown, el primer mensaje debe ser un system message
            que además pida explícitamente "SOLO JSON, sin texto adicional".
            No confiar solo en el parámetro `format`.
        tools: definiciones de herramientas estilo OpenAI function-calling
            (lista de {"type": "function", "function": {...}}).

    Devuelve el `message` completo de la respuesta (dict con role/content/
    tool_calls opcional), tal como lo entrega la API — no se interpreta aquí.
    """
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if response_schema is not None:
        payload["format"] = response_schema
    if tools is not None:
        payload["tools"] = tools

    # Ollama Cloud (tier gratuito) corta la conexión ocasionalmente bajo
    # carga sostenida (ConnectionError/RemoteDisconnected, visto en
    # producción al clasificar 6000 tickets en batch) — reintentar con
    # backoff exponencial en vez de abortar todo el trabajo ya cacheado.
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                OLLAMA_CHAT_URL,
                headers={"Authorization": f"Bearer {_get_api_key()}"},
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            last_exc = exc
        else:
            if resp.status_code == 200:
                return resp.json()["message"]
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = LLMError(f"Ollama Cloud devolvió {resp.status_code}: {resp.text[:300]}")
            else:
                # error no transitorio (400, 401, etc.) — no tiene sentido reintentar
                raise LLMError(f"Ollama Cloud devolvió {resp.status_code}: {resp.text[:500]}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))

    raise LLMError(f"Fallaron {MAX_RETRIES} intentos contra Ollama Cloud: {last_exc}")


def chat_structured(
    system_prompt: str,
    user_prompt: str,
    response_schema: dict,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Azúcar sintáctico para el caso de uso de business_alignment.py:
    fuerza salida JSON y la parsea. Lanza LLMError si el modelo no devuelve
    JSON válido (no se "adivina" ni se rellena con valores por defecto).
    """
    system_prompt_reforzado = (
        system_prompt.rstrip()
        + "\n\nRespondes SOLO con un objeto JSON válido que cumpla el schema dado, "
        "sin texto adicional antes o después, sin markdown, sin explicaciones."
    )
    message = chat(
        messages=[
            {"role": "system", "content": system_prompt_reforzado},
            {"role": "user", "content": user_prompt},
        ],
        model=model,
        response_schema=response_schema,
    )
    content = message.get("content", "")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"El modelo no devolvió JSON válido: {content[:300]!r}") from exc


if __name__ == "__main__":
    result = chat_structured(
        system_prompt="Eres un clasificador de tickets.",
        user_prompt='Clasifica: "Alerta de memoria en auth-service — reinicio requerido". '
        "effort_type debe ser uno de: valor_directo, deuda_operativa, deuda_tecnica, friccion_proceso",
        response_schema={
            "type": "object",
            "properties": {"effort_type": {"type": "string"}},
            "required": ["effort_type"],
        },
    )
    print(result)
