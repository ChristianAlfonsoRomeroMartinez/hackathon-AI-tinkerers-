"""
Capa 2.5 — Alineación con el core de negocio.

Clasificación de doble eje por ticket:
  (a) tipo de esfuerzo [valor_directo | deuda_operativa | deuda_tecnica |
      friccion_proceso] — ÚNICO campo que requiere juicio semántico sobre
      la intención del ticket (su título). Es la única parte de todo el
      proyecto que usa el LLM para "decidir" algo — y lo hace en batch, con
      salida JSON forzada (ver llm_client.chat_structured), nunca como
      texto libre, y el resultado se cachea en disco por ticket para no
      re-clasificar en cada turno del agente.
  (b) criticidad estratégica — NO requiere LLM: es un lookup determinista
      directo de business_taxonomy.json por categoría (la propia
      especificación dice "según la taxonomía", y la taxonomía ya trae
      `strategic_value` por categoría). Clasificarlo con LLM sería
      reinventar con una llamada cara algo que ya está dado como dato.

Métrica derivada: % de capacidad (tickets) consumida FUERA del core
(cualquier effort_type != valor_directo), por equipo declarado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .data_loader import Dataset, load_dataset
from .llm_client import LLMError, chat_structured

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "derived" / "business_alignment_cache.json"

EFFORT_TYPES = ["valor_directo", "deuda_operativa", "deuda_tecnica", "friccion_proceso"]
BATCH_SIZE = 40  # tickets por llamada al LLM — balance entre latencia y tamaño de contexto

_SYSTEM_PROMPT = """Eres un analista de operaciones clasificando tickets de soporte/desarrollo \
por TIPO DE ESFUERZO, según la intención real detrás del título (no la categoría, que no ves aquí).

Las 4 opciones posibles:
- valor_directo: trabajo que entrega valor de negocio nuevo o solicitado por el cliente \
(features, solicitudes de cliente, cambios de negocio).
- deuda_operativa: incidentes operativos recurrentes (reinicios, alertas, caídas, lentitud) \
que son síntoma de un problema no resuelto de raíz, no trabajo de valor nuevo.
- deuda_tecnica: refactors, eliminar hardcode, vulnerabilidades, mejoras de arquitectura — \
trabajo técnico que no es visible para el negocio pero reduce riesgo/deuda futura.
- friccion_proceso: reasignaciones, aprobaciones duplicadas o burocráticas, retrabajo por \
proceso mal diseñado — el ticket en sí no es el problema, el proceso alrededor sí.

Clasifica cada ticket de la lista, EN EL MISMO ORDEN, con su id."""


def _load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _classify_batch_via_llm(batch: list[dict]) -> dict[str, str]:
    """batch: [{ticket_id, title}, ...]. Devuelve {ticket_id: effort_type}."""
    numbered = "\n".join(f'{i+1}. [id={t["ticket_id"]}] "{t["title"]}"' for i, t in enumerate(batch))
    user_prompt = f"Clasifica el effort_type de cada ticket:\n{numbered}"
    schema = {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "effort_type": {"type": "string", "enum": EFFORT_TYPES},
                    },
                    "required": ["id", "effort_type"],
                },
            }
        },
        "required": ["classifications"],
    }
    result = chat_structured(_SYSTEM_PROMPT, user_prompt, schema)
    return _extract_classifications(result)


def _extract_classifications(result: object) -> dict[str, str]:
    """gpt-oss:120b vía Ollama Cloud respeta el CONTENIDO pedido (id +
    effort_type por ticket) pero NO es consistente con la forma exacta del
    envoltorio pese al JSON Schema forzado. Formas observadas empíricamente
    para el mismo prompt/schema en llamadas distintas:
      1. {"classifications": [{"id": "TCK-1", "effort_type": "..."}, ...]}
      2. {"tickets": [{"id": "TCK-1", "effort_type": "..."}, ...]}
      3. [{"id": "TCK-1", "effort_type": "..."}, ...]           (lista suelta)
      4. {"TCK-1": "deuda_operativa", "TCK-2": "valor_directo", ...} (mapa plano)

    Se normalizan las 4 formas en vez de fallar por un detalle cosmético de
    empaquetado — el contenido semántico (qué ticket, qué label) es lo que
    importa y sí se valida estrictamente contra EFFORT_TYPES.
    """
    out: dict[str, str] = {}

    def _from_item(item: dict) -> None:
        if item.get("effort_type") in EFFORT_TYPES and item.get("id"):
            out[str(item["id"])] = item["effort_type"]

    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                _from_item(item)
        return out

    if isinstance(result, dict):
        # forma 4: mapa plano ticket_id -> effort_type (todos los valores son
        # labels válidos, no dicts/listas anidadas)
        if result and all(v in EFFORT_TYPES for v in result.values()):
            return {str(k): v for k, v in result.items()}
        # formas 1/2: buscar la primera lista de dicts en cualquier llave
        for value in result.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _from_item(item)
                if out:
                    return out
    return out


def _tickets_with_title(dataset: Dataset) -> pd.DataFrame:
    created = dataset.events[dataset.events["event_type"] == "created"][
        ["ticket_id", "title", "category", "declared_team"]
    ].drop_duplicates(subset="ticket_id")
    return created


def classify_business_alignment(
    dataset: Dataset | None = None,
    max_new_calls: int | None = None,
    force_refresh: bool = False,
) -> dict:
    """Clasifica todos los tickets (o usa caché) en los dos ejes, y devuelve
    la métrica derivada de % capacidad fuera del core por equipo.

    Args:
        max_new_calls: límite de llamadas NUEVAS al LLM en esta invocación
            (protección de costo/latencia en demos — si el caché ya cubre
            todo, no importa). None = sin límite.
        force_refresh: ignora el caché existente y reclasifica todo.
    """
    dataset = dataset or load_dataset()
    titles_df = _tickets_with_title(dataset)
    taxonomy = dataset.taxonomy

    cache = {} if force_refresh else _load_cache()
    pending = titles_df[~titles_df["ticket_id"].isin(cache.keys())] if not force_refresh else titles_df

    n_calls = 0
    failed_batches: list[str] = []
    pending_records = pending[["ticket_id", "title"]].to_dict(orient="records")
    for i in range(0, len(pending_records), BATCH_SIZE):
        if max_new_calls is not None and n_calls >= max_new_calls:
            break
        batch = pending_records[i : i + BATCH_SIZE]
        try:
            result = _classify_batch_via_llm(batch)
        except LLMError as exc:
            # un batch que agotó reintentos no debe tirar todo el progreso ya
            # cacheado de los batches anteriores — se registra como pendiente
            # y se sigue con el resto (se puede reintentar en una corrida
            # posterior, el caché ya tiene lo demás guardado).
            failed_batches.append(f"{i}-{i+len(batch)}: {exc}")
            n_calls += 1
            continue
        cache.update(result)
        n_calls += 1
        _save_cache(cache)  # guardar incrementalmente, no perder progreso si algo falla a mitad

    titles_df = titles_df.copy()
    titles_df["effort_type"] = titles_df["ticket_id"].map(cache)
    titles_df["strategic_value"] = titles_df["category"].map(
        lambda c: taxonomy.get(c, {}).get("strategic_value")
    )

    classified = titles_df.dropna(subset=["effort_type"])
    n_total = len(titles_df)
    n_classified = len(classified)

    # % capacidad fuera del core, por equipo declarado (solo sobre tickets
    # efectivamente clasificados — si hay pendientes por límite de llamadas,
    # se declara explícitamente cuántos, no se extrapola).
    classified = classified.copy()
    classified["is_core_value"] = classified["effort_type"] == "valor_directo"
    by_team = (
        classified.groupby("declared_team")["is_core_value"]
        .agg(n_tickets="count", pct_core_value="mean")
        .reset_index()
    )
    by_team["pct_outside_core"] = 1 - by_team["pct_core_value"]

    effort_distribution = classified["effort_type"].value_counts().to_dict()
    strategic_distribution = classified["strategic_value"].value_counts().to_dict()

    # matriz esfuerzo x criticidad estratégica (para la Sección 2 del informe)
    matrix = (
        classified.groupby(["effort_type", "strategic_value"])
        .size()
        .reset_index(name="n_tickets")
        .to_dict(orient="records")
    )

    return {
        "n_tickets_total": n_total,
        "n_tickets_classified": n_classified,
        "n_tickets_pending": n_total - n_classified,
        "llm_calls_made_this_run": n_calls,
        "failed_batches": failed_batches,
        "effort_type_distribution": effort_distribution,
        "strategic_value_distribution": strategic_distribution,
        "effort_x_strategic_matrix": matrix,
        "pct_outside_core_by_team": by_team.round(4).to_dict(orient="records"),
        "per_ticket": classified[
            ["ticket_id", "category", "declared_team", "effort_type", "strategic_value"]
        ].to_dict(orient="records"),
    }


if __name__ == "__main__":
    import sys

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 3  # default: prueba chica (validación manual)
    result = classify_business_alignment(max_new_calls=limit)
    per_ticket = result.pop("per_ticket")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n=== muestra de {min(15, len(per_ticket))} tickets clasificados (para validación manual) ===")
    for row in per_ticket[:15]:
        print(row)
