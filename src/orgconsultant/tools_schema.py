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
from .flow_metrics import get_flow_metrics, get_state_queue_times

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
                    "team": {"type": "string", "description": "team_alpha|team_beta|team_gamma|team_growth, opcional"},
                    "category": {"type": "string", "description": "categoría de negocio, opcional"},
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
                    "state": {"type": "string", "description": "estado específico, opcional"},
                    "category": {"type": "string"},
                    "declared_team": {"type": "string"},
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
                    "category": {"type": "string"},
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
                    "category": {"type": "string"},
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
            "name": "simulate_change",
            "description": (
                "Simula un cambio simple (Ley de Little) y recalcula lead time / "
                "WIP esperado / impacto económico anualizado (horas-en-cola x "
                "costo/hora, un proxy de costo de demora, no nómina literal)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lever_type": {"type": "string", "enum": ["remove_state", "reduce_state_queue_time"]},
                    "target_state": {"type": "string"},
                    "reduction_pct": {"type": "number", "description": "0.0-1.0, default 1.0"},
                    "category": {"type": "string"},
                    "team": {"type": "string"},
                    "cost_per_hour_usd": {"type": "number", "description": "default 45.0, declárese explícitamente en el informe"},
                },
                "required": ["lever_type", "target_state"],
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
                "Encadena varios simulate_change en horizontes progresivos — el "
                "resultado del horizonte N es el punto de partida del N+1. Úsalo "
                "para el plan de implementación progresiva de hallazgos macro."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sequence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "lever_type": {"type": "string", "enum": ["remove_state", "reduce_state_queue_time"]},
                                "target_state": {"type": "string"},
                                "reduction_pct": {"type": "number"},
                            },
                            "required": ["lever_type", "target_state"],
                        },
                    },
                    "category": {"type": "string"},
                    "team": {"type": "string"},
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


TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "get_flow_metrics": get_flow_metrics,
    "get_state_queue_times": get_state_queue_times,
    "get_handoff_graph": handoff_graph.get_handoff_graph,
    "find_ticket_clusters": clustering.find_ticket_clusters,
    "get_ticket_samples": clustering.get_ticket_samples,
    "classify_business_alignment": _dispatch_classify_business_alignment,
    "classify_change_severity": _dispatch_classify_change_severity,
    "propose_org_blocks": org_blocks.propose_org_blocks,
    "search_best_practices": web_research.search_best_practices,
    "simulate_change": lambda **kw: {
        k: v for k, v in simulation.simulate_change(**kw).items() if k != "resulting_tickets"
    },
    "simulate_horizon_cascade": simulation.simulate_horizon_cascade,
}


def call_tool(name: str, arguments: dict) -> Any:
    if name not in TOOL_FUNCTIONS:
        return {"error": f"Herramienta desconocida: {name}"}
    try:
        return TOOL_FUNCTIONS[name](**arguments)
    except Exception as exc:  # noqa: BLE001 — se le devuelve el error al LLM, no se oculta
        return {"error": f"{type(exc).__name__}: {exc}"}
