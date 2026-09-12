"""
Herramienta opcional de investigación externa — Exa.ai (búsqueda neuronal).

Uso legítimo de Exa: es un motor de búsqueda/retrieval web, NO un proveedor
de embeddings ni de LLM (ver PROGRESS.md — se probó y descartó para esos
dos usos). Aquí se usa para lo que sí sirve: traer 2-3 referencias externas
de buenas prácticas de la industria que respalden una recomendación del
informe (ej. "cómo reducir la dependencia de un héroe/SPOF"), citando la
fuente — nunca para calcular ninguna métrica interna del dataset.

Esta herramienta es aditiva/opcional para el agente: enriquece la narrativa
del informe con benchmarks externos, pero ninguna cifra del diagnóstico
(lead time, costo, severidad, etc.) depende de ella — esas siempre vienen
de las capas deterministas sobre el dataset real.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

EXA_SEARCH_URL = "https://api.exa.ai/search"


class WebResearchError(RuntimeError):
    pass


def search_best_practices(query: str, n_results: int = 3) -> dict:
    """Busca referencias externas (artículos/guías de industria) relevantes
    a un hallazgo del diagnóstico. Devuelve título+URL+snippet — el LLM cita
    la fuente en el informe, no se le pide a Exa ningún número.
    """
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise WebResearchError("EXA_API_KEY no configurada en .env")

    resp = requests.post(
        EXA_SEARCH_URL,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json={"query": query, "numResults": n_results, "type": "auto", "contents": {"summary": True}},
        timeout=30,
    )
    if resp.status_code != 200:
        raise WebResearchError(f"Exa devolvió {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    results = []
    for r in data.get("results", []):
        results.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "summary": r.get("summary") or r.get("text", "")[:400],
            }
        )
    return {"query": query, "results": results}


if __name__ == "__main__":
    import json

    print(json.dumps(search_best_practices("reducing single point of failure hero engineer"), indent=2, ensure_ascii=False))
