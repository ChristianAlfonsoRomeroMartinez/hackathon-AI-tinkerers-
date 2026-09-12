"""
Definiciones de herramientas (JSON Schema, estilo OpenAI function-calling —
mismo formato que acepta el endpoint /api/chat de Ollama Cloud) + registro
de despacho name -> función Python real.

Este es el único lugar donde se listan las herramientas que el LLM puede
invocar. Si agregas una función nueva en alguna capa, regístrala aquí para
que el agente pueda usarla — el LLM nunca llama directamente a Python, solo
a través de este contrato.
"""

from __future__ import annotations

from typing import Any, Callable

from . import (
    business_alignment,
    clustering,
    handoff_graph,
    org_blocks,
    severity,
    simulation,
    web_research,
)
from .data_loader import CANONICAL_STATES, load_dataset
from .flow_metrics import get_flow_metrics, get_monthly_trend, get_state_queue_times

_ds = load_dataset()
VALID_CATEGORIES = sorted(_ds.tickets["category"].unique().tolist())
VALID_TEAMS = sorted(_ds.tickets["declared_team"].unique().tolist())
VALID_STATES = CANONICAL_STATES

_CATEGORY_DESC = f"Una de: {', '.join(VALID_CATEGORIES)}. Opcional — omite el campo si no filtras por categoría (no envíes string vacío)."
_TEAM_DESC = f"Una de: {', '.join(VALID_TEAMS)}. Opcional — omite el campo si no filtras por equipo (no envíes string vacío)."
_STATE_DESC = f"Uno de: {', '.join(VALID_STATES)}. Opcional — omite el campo si no filtras por estado (no envíes string vacío)."

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_flow_metrics",
            "description": (
                "Panorama de flujo: lead time (p50/p90), tasa de reapertura, "
                "reasignaciones promedio, aging de WIP actual y tiempos de cola "
                "por estado. Filtrable por equipo y/o categoría. Úsalo primero, "
                "sin filtros, para explorar el panorama general."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {"type": "string", "enum": VALID_TEAMS, "description": _TEAM_DESC},
                    "category": {"type": "string", "enum": VALID_CATEGORIES, "description": _CATEGORY_DESC},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_state_queue_times",
            "description": (
                "Tiempo mediano/p90 en cada estado del flujo, ordenado de mayor "
                "a menor p90 — para detectar dónde se muere el trabajo (cuellos "
                "de botella de aprobación, colas de triage, etc)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "enum": VALID_STATES, "description": _STATE_DESC},
                    "category": {"type": "string", "enum": VALID_CATEGORIES, "description": _CATEGORY_DESC},
                    "declared_team": {"type": "string", "enum": VALID_TEAMS, "description": _TEAM_DESC},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_trend",
            "description": (
                "Conteo de eventos por MES calendario (últimos hasta 6 meses del dataset) "
                "que cumplen los filtros dados. ÚSALA para verificar persistencia real de "
                "un patrón antes de llamar classify_change_severity con "
                "months_present_last_6 — NUNCA estimes ese número de memoria, cuéntalo con "
                "esta herramienta (cuenta cuántos de los meses devueltos tienen conteo > 0, "
                "o por encima del umbral que definas como 'presencia estable')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "enum": VALID_STATES, "description": _STATE_DESC + " Filtra por to_state del evento."},
                    "category": {"type": "string", "enum": VALID_CATEGORIES, "description": _CATEGORY_DESC},
                    "declared_team": {"type": "string", "enum": VALID_TEAMS, "description": _TEAM_DESC},
                    "actor_hash": {"type": "string", "description": "opcional, para medir la presencia de un actor específico (ej. un SPOF) mes a mes"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_handoff_graph",
            "description": (
                "Grafo de handoffs actor-a-actor: betweenness centrality (busca "
                "héroes/SPOF — actores por los que pasa desproporcionadamente el "
                "trabajo) y comunidades Louvain (topología real de colaboración, "
                "para contrastar TÚ MISMO contra los equipos declarados en "
                "org_chart_declared.json y detectar silos mal cortados)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_weight": {"type": "integer", "description": "filtra aristas con menos de N handoffs, default 1"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_ticket_clusters",
            "description": (
                "Clusteriza títulos de tickets por similitud semántica (embeddings "
                "+ HDBSCAN). Útil para aislar causas raíz repetidas (deuda "
                "operativa invisible) dentro de una categoría."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": VALID_CATEGORIES, "description": _CATEGORY_DESC},
                    "min_cluster_size": {"type": "integer", "description": "default 10"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticket_samples",
            "description": (
                "Tickets representativos de un cluster ya calculado por "
                "find_ticket_clusters (usa el MISMO category/min_cluster_size de "
                "esa llamada) — léelos para ponerle nombre/interpretación al cluster."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cluster_id": {"type": "integer"},
                    "n": {"type": "integer", "description": "default 5"},
                    "category": {"type": "string", "enum": VALID_CATEGORIES, "description": _CATEGORY_DESC},
                    "min_cluster_size": {"type": "integer"},
                },
                "required": ["cluster_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_business_alignment",
            "description": (
                "Métricas agregadas de alineación con el core de negocio: "
                "distribución de tipo de esfuerzo (valor_directo/deuda_operativa/"
                "deuda_tecnica/friccion_proceso), criticidad estratégica, matriz "
                "cruzada, y % de capacidad consumida fuera del core por equipo. "
                "Ya viene pre-calculado sobre TODO el dataset (cacheado por ticket, "
                "no se re-clasifica en esta llamada)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_change_severity",
            "description": (
                "Clasifica la severidad de un hallazgo YA confirmado con evidencia "
                "cuantitativa (nunca inventes estos números, sácalos de otras "
                "herramientas). Regla de negocio determinista de >=2 de 3 criterios."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "declared_teams_involved": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "equipos declarados distintos que el hallazgo involucra",
                    },
                    "is_interdepartmental_approval": {"type": "boolean"},
                    "months_present_last_6": {
                        "type": "integer",
                        "description": "en cuántos de los últimos 6 meses simulados aparece el patrón de forma estable (0-6)",
                    },
                    "pct_tickets_high_or_medium_strategic": {
                        "type": "number",
                        "description": "0.0-1.0, % de tickets del hallazgo con criticidad estratégica alto o medio",
                    },
                },
                "required": ["finding_id", "declared_teams_involved", "months_present_last_6", "pct_tickets_high_or_medium_strategic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_org_blocks",
            "description": (
                "SOLO invocar si ya hay hallazgos de severidad organizacional o "
                "estratégica. Propone bloques organizacionales por flujo de valor "
                "real (comunidades del grafo de handoffs) con evidencia y rol "
                "nuevo sugerido si aplica."
            ),
            "parameters": {
                "type": "object",
                "properties": {"min_weight": {"type": "integer", "description": "default 1"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_remove_bottleneck_state",
            "description": (
                "Simula ELIMINAR POR COMPLETO un estado del flujo (ej. quitar una "
                "aprobación) y recalcula lead time / WIP esperado (Ley de Little) / "
                "impacto económico anualizado (horas-en-cola x costo/hora, un proxy "
                "de costo de demora, no nómina literal). Para una reducción PARCIAL "
                "en vez de eliminar el estado, usa simulate_reduce_bottleneck_state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_state": {"type": "string", "enum": VALID_STATES, "description": _STATE_DESC + " El estado a eliminar."},
                    "category": {"type": "string", "enum": VALID_CATEGORIES, "description": _CATEGORY_DESC},
                    "team": {"type": "string", "enum": VALID_TEAMS, "description": _TEAM_DESC},
                    "cost_per_hour_usd": {"type": "number", "description": "default 45.0, declárese explícitamente en el informe"},
                },
                "required": ["target_state"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_reduce_bottleneck_state",
            "description": (
                "Simula REDUCIR (no eliminar) el tiempo de cola de un estado en un "
                "porcentaje dado, y recalcula lead time / WIP / impacto económico "
                "anualizado. Para eliminar el estado por completo usa "
                "simulate_remove_bottleneck_state en su lugar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_state": {"type": "string", "enum": VALID_STATES, "description": _STATE_DESC},
                    "reduction_pct": {"type": "number", "description": "0.0-1.0 (ej. 0.4 = reduce 40% del tiempo de cola actual). Obligatorio."},
                    "category": {"type": "string", "enum": VALID_CATEGORIES, "description": _CATEGORY_DESC},
                    "team": {"type": "string", "enum": VALID_TEAMS, "description": _TEAM_DESC},
                    "cost_per_hour_usd": {"type": "number", "description": "default 45.0, declárese explícitamente en el informe"},
                },
                "required": ["target_state", "reduction_pct"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_best_practices",
            "description": (
                "Busca 2-3 referencias EXTERNAS de la industria (Exa.ai, búsqueda web) "
                "que respalden una recomendación del informe (ej. 'cómo reducir la "
                "dependencia de un héroe/SPOF'). Opcional/aditivo: nunca uses esto para "
                "obtener cifras del diagnóstico — esas siempre vienen de las otras "
                "herramientas sobre el dataset real. Solo para enriquecer la narrativa "
                "citando fuentes externas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "n_results": {"type": "integer", "description": "default 3"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_horizon_cascade",
            "description": (
                "Encadena varios horizontes de cambio progresivos sobre EL MISMO "
                "estado — el resultado del horizonte N es el punto de partida del "
                "N+1. Úsalo para el plan de implementación progresiva de un "
                "hallazgo macro (ej. reducir 40%, luego 70% acumulado, luego "
                "eliminar del todo un cuello de botella)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sequence": {
                        "type": "array",
                        "description": (
                            "Un elemento por horizonte, en orden. Cada uno: "
                            '{"target_state": <estado>, "remove": true} para eliminarlo '
                            'del todo en ese horizonte, o '
                            '{"target_state": <estado>, "remove": false, "reduction_pct": 0.4} '
                            "para reducir un % de la cola restante."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "target_state": {"type": "string", "enum": VALID_STATES, "description": _STATE_DESC},
                                "remove": {"type": "boolean", "description": "true = eliminar el estado por completo en este horizonte; false = solo reducirlo"},
                                "reduction_pct": {"type": "number", "description": "0.0-1.0, solo se usa si remove=false"},
                            },
                            "required": ["target_state", "remove"],
                        },
                    },
                    "category": {"type": "string", "enum": VALID_CATEGORIES, "description": _CATEGORY_DESC},
                    "team": {"type": "string", "enum": VALID_TEAMS, "description": _TEAM_DESC},
                    "cost_per_hour_usd": {"type": "number"},
                },
                "required": ["sequence"],
            },
        },
    },
]


def _dispatch_classify_business_alignment(**kwargs) -> dict:
    result = business_alignment.classify_business_alignment(max_new_calls=0)
    result.pop("per_ticket", None)  # demasiado grande para el contexto del LLM; el informe lo usa directo en Python
    return result


def _dispatch_classify_change_severity(**kwargs) -> dict:
    return severity.classify_change_severity(kwargs)


_INTERNAL_ONLY_KEYS = {"resulting_tickets", "remaining_queue_hours"}  # para encadenar horizontes, no serializables/no relevantes para el LLM


def _dispatch_simulate_remove(**kwargs) -> dict:
    return {
        k: v
        for k, v in simulation.simulate_change(lever_type="remove_state", **kwargs).items()
        if k not in _INTERNAL_ONLY_KEYS
    }


def _dispatch_simulate_reduce(**kwargs) -> dict:
    return {
        k: v
        for k, v in simulation.simulate_change(lever_type="reduce_state_queue_time", **kwargs).items()
        if k not in _INTERNAL_ONLY_KEYS
    }


def _dispatch_simulate_horizon_cascade(sequence: list[dict], **kwargs) -> dict:
    # traduce {target_state, remove, reduction_pct} -> {lever_type, target_state, reduction_pct}
    # que es lo que espera simulation.simulate_horizon_cascade internamente.
    translated = []
    for step in sequence:
        if step.get("remove"):
            translated.append({"lever_type": "remove_state", "target_state": step["target_state"]})
        else:
            translated.append(
                {
                    "lever_type": "reduce_state_queue_time",
                    "target_state": step["target_state"],
                    "reduction_pct": step.get("reduction_pct", 0.5),
                }
            )
    return simulation.simulate_horizon_cascade(sequence=translated, **kwargs)


TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "get_flow_metrics": get_flow_metrics,
    "get_state_queue_times": get_state_queue_times,
    "get_monthly_trend": get_monthly_trend,
    "get_handoff_graph": handoff_graph.get_handoff_graph,
    "find_ticket_clusters": clustering.find_ticket_clusters,
    "get_ticket_samples": clustering.get_ticket_samples,
    "classify_business_alignment": _dispatch_classify_business_alignment,
    "classify_change_severity": _dispatch_classify_change_severity,
    "propose_org_blocks": org_blocks.propose_org_blocks,
    "search_best_practices": web_research.search_best_practices,
    "simulate_remove_bottleneck_state": _dispatch_simulate_remove,
    "simulate_reduce_bottleneck_state": _dispatch_simulate_reduce,
    "simulate_horizon_cascade": _dispatch_simulate_horizon_cascade,
}


def _normalize_arguments(arguments: dict) -> dict:
    """Los LLMs (visto empíricamente con gpt-oss:120b vía Ollama) a veces
    envían un parámetro opcional como string vacío "" en vez de omitirlo —
    con nuestras funciones eso filtraría a "categoría == ''" (0 resultados)
    en vez de "sin filtro". Se normaliza "" -> ausente antes de despachar,
    para todos los tools, en vez de parchear cada función una por una.
    """
    return {k: v for k, v in arguments.items() if v != ""}


def call_tool(name: str, arguments: dict) -> Any:
    if name not in TOOL_FUNCTIONS:
        return {"error": f"Herramienta desconocida: {name}. Herramientas válidas: {sorted(TOOL_FUNCTIONS)}"}
    arguments = _normalize_arguments(arguments)
    try:
        return TOOL_FUNCTIONS[name](**arguments)
    except Exception as exc:  # noqa: BLE001 — se le devuelve el error al LLM, no se oculta
        return {"error": f"{type(exc).__name__}: {exc}"}
