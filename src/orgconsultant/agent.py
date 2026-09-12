"""
Fase 8 — Orquestación del agente (tool use real, iterativo).

El LLM (gpt-oss:120b vía Ollama Cloud, ver llm_client.py) nunca calcula
números: en cada turno decide qué herramienta de tools_schema.py invocar,
lee el resultado ya calculado por código determinista, y decide el
siguiente paso. Este módulo solo orquesta el loop y loguea la traza
completa — no interpreta ni resume nada por su cuenta.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .llm_client import DEFAULT_MODEL, LLMError, chat
from .tools_schema import TOOLS, call_tool

TRACE_PATH = Path(__file__).resolve().parents[2] / "data" / "derived" / "agent_trace.jsonl"

AGENT_NAME = "Consultor Organizacional Autónomo"

SYSTEM_PROMPT = f"""Eres {AGENT_NAME}, un consultor senior de reestructuración organizacional \
(perfil Scrum Master / Agile Coach / Principal Process Engineer) que opera de forma autónoma: \
decides tú mismo qué hipótesis investigar y qué herramienta invocar en cada paso, sin guion fijo. \
Tienes acceso a herramientas que calculan \
métricas de flujo, construyen grafos de colaboración, clasifican tickets semánticamente y \
simulan cambios. TÚ NUNCA calculas números — siempre invocas una herramienta.

Protocolo de trabajo:
1. Explora el panorama general con get_flow_metrics() sin filtros.
2. Formula hipótesis específicas sobre posibles disfunciones (SPOF, silos, aprobaciones \
ineficientes, desalineación estratégica, fragmentación de procesos, deuda operativa repetida, \
ping-pong de triage) basadas en lo que ves.
3. Para cada hipótesis, invoca las herramientas necesarias para confirmarla o descartarla con \
evidencia cuantitativa. No aceptes una hipótesis sin al menos DOS señales independientes que la \
soporten (ej. betweenness alto + coincide con equipo de un rol "bottleneck" declarado). Usa \
get_monthly_trend para verificar persistencia real — NUNCA estimes months_present_last_6 de \
memoria.
4. Para cada hallazgo confirmado, clasifica su severidad con classify_change_severity. NO decidas \
tú si es táctico o macro — usa la herramienta, con los números reales que obtuviste.
5. Cuantifica el impacto económico de cada hallazgo con simulate_remove_bottleneck_state (elimina \
el estado por completo) o simulate_reduce_bottleneck_state (lo reduce un %) — horas-en-cola x \
costo/hora, usa el costo/hora default salvo que se te pida otro, y decláralo en tu resumen.
6. Para hallazgos de severidad organizacional/estratégica, invoca propose_org_blocks y construye \
el plan de horizontes con simulate_horizon_cascade. Para el horizonte específico de rediseño de \
equipos (y SOLO ese horizonte, no los demás), incluye una tabla RACI (Responsable/Aprueba/\
Consultado/Informado) usando los actor_hash y roles reales que te devolvió propose_org_blocks — \
no inventes personas ni roles que no estén en esos datos.
6b. Opcionalmente, usa search_best_practices para citar 1-2 referencias externas de la industria \
que respalden una recomendación puntual — nunca para obtener cifras, esas siempre salen de las \
otras herramientas sobre el dataset real.
7. Cuando ya tengas evidencia suficiente para TODAS las hipótesis relevantes que formulaste, \
escribe tu informe final en texto (sin más tool calls) citando ticket_id y cifras concretas para \
cada afirmación. Nunca afirmes algo sobre el flujo sin haber invocado la herramienta \
correspondiente en este turno o uno anterior.

Restricción crítica: no propongas reestructuración organizacional completa si los hallazgos no \
la ameritan según classify_change_severity. Un informe que sobre-actúa recomendando macro-cambio \
en todo es peor que uno conservador.

Cuando termines de investigar, tu ÚLTIMO mensaje (sin tool calls) debe ser un informe estructurado \
en Markdown con: hallazgos (con severidad y evidencia citada), impacto económico, y — si aplica — \
propuesta de bloques organizacionales y plan de horizontes."""

KICKOFF_MESSAGE = (
    "Empieza la investigación. Recuerda: cada afirmación cuantitativa debe venir de una "
    "herramienta invocada en este turno o uno anterior, nunca estimada por ti."
)


def _log_trace(entry: dict) -> None:
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def run_agent(max_turns: int = 30, model: str = DEFAULT_MODEL, verbose: bool = True) -> dict:
    """Corre el loop de tool-use hasta que el LLM entregue una respuesta
    final sin tool_calls, o se agote max_turns. Devuelve la traza completa
    y el informe final (texto).
    """
    # trace nueva por corrida — no acumular corridas viejas en el mismo archivo
    if TRACE_PATH.exists():
        TRACE_PATH.unlink()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": KICKOFF_MESSAGE},
    ]
    trace: list[dict] = []

    for turn in range(1, max_turns + 1):
        t0 = time.time()
        try:
            message = chat(messages=messages, model=model, tools=TOOLS)
        except LLMError as exc:
            entry = {"turn": turn, "type": "llm_error", "error": str(exc), "ts": datetime.now(timezone.utc).isoformat()}
            _log_trace(entry)
            trace.append(entry)
            break

        elapsed = round(time.time() - t0, 1)
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            # respuesta final del agente
            entry = {
                "turn": turn,
                "type": "final_answer",
                "content": message.get("content", ""),
                "elapsed_s": elapsed,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            _log_trace(entry)
            trace.append(entry)
            if verbose:
                print(f"[turno {turn}] respuesta final ({elapsed}s)")
            return {"trace": trace, "final_report": message.get("content", ""), "n_turns": turn}

        # el LLM pidió una o más herramientas — se ejecutan y se responde
        messages.append({"role": "assistant", "content": message.get("content", ""), "tool_calls": tool_calls})
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            t_tool = time.time()
            result = call_tool(name, args)
            tool_elapsed = round(time.time() - t_tool, 2)

            entry = {
                "turn": turn,
                "type": "tool_call",
                "tool": name,
                "arguments": args,
                "result_preview": _preview(result),
                "elapsed_s": tool_elapsed,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            _log_trace(entry)
            trace.append(entry)
            if verbose:
                print(f"[turno {turn}] {name}({args}) -> {tool_elapsed}s")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    return {"trace": trace, "final_report": None, "n_turns": max_turns, "error": "max_turns alcanzado sin respuesta final"}


def _preview(result, max_len: int = 500) -> str:
    s = json.dumps(result, ensure_ascii=False, default=str)
    return s if len(s) <= max_len else s[:max_len] + "...(truncado)"


if __name__ == "__main__":
    print(f"=== {AGENT_NAME} — iniciando investigación ===\n")
    result = run_agent()
    print(f"\n\n=== INFORME FINAL — {AGENT_NAME} ===\n")
    print(result.get("final_report") or result.get("error"))
    print(f"\n(traza completa en {TRACE_PATH})")
