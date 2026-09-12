"""
Capa 0 — Carga de datos.

Punto único de acceso a los datos crudos del dataset sintético. Todo lo demás
(flow_metrics, handoff_graph, clustering, etc.) debe construirse sobre las
funciones de este módulo, nunca releer los CSV/JSON por su cuenta.

Nota deliberada: este módulo NUNCA toca `ground_truth.json`. Ese archivo es
solo para la verificación manual del humano fuera del sistema del agente.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

# Raíz del proyecto = dos niveles arriba de este archivo (src/orgconsultant/..)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "synth"

EVENT_LOG_CSV = DATA_DIR / "event_log.csv"
TICKETS_CSV = DATA_DIR / "tickets.csv"
ORG_CHART_JSON = DATA_DIR / "org_chart_declared.json"
BUSINESS_TAXONOMY_JSON = DATA_DIR / "business_taxonomy.json"
# Deliberadamente NO se define una constante para ground_truth.json aquí.

# Estados válidos del flujo, en orden canónico (no todos los tickets pasan
# por todos; Pending Approval Security y Reopened son condicionales).
CANONICAL_STATES = [
    "Backlog",
    "Triage",
    "In Progress",
    "Pending Approval Security",
    "In Review",
    "Reopened",
    "Waiting Handoff",
    "Done",
]


@dataclass(frozen=True)
class Dataset:
    """Contenedor inmutable de los datos crudos ya cargados y tipados."""

    events: pd.DataFrame  # event log, una fila por evento
    tickets: pd.DataFrame  # vista resumida por ticket
    org_chart: dict
    taxonomy: dict

    con: duckdb.DuckDBPyConnection  # conexión DuckDB con vistas registradas


def _load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENT_LOG_CSV, parse_dates=["ts"])
    # payload viene serializado como JSON string en la columna payload_json
    df["payload"] = df["payload_json"].apply(json.loads)
    df = df.drop(columns=["payload_json"])
    # columnas de payload usadas frecuentemente, aplanadas para conveniencia
    # (no todos los eventos las tienen; NaN donde no aplica)
    df["category"] = df["payload"].apply(lambda p: p.get("category"))
    df["declared_team"] = df["payload"].apply(lambda p: p.get("declared_team"))
    df["title"] = df["payload"].apply(lambda p: p.get("title"))
    df["leg_team"] = df["payload"].apply(lambda p: p.get("leg_team"))
    df["leg_index"] = df["payload"].apply(lambda p: p.get("leg_index"))
    df["root_cause_template_id"] = df["payload"].apply(
        lambda p: p.get("root_cause_template_id")
    )
    # category/declared_team solo vienen en el evento `created`; propagarlos
    # a todos los eventos del mismo ticket para que se puedan filtrar métricas
    # de flujo por categoría/equipo sin tener que hacer join manual cada vez.
    df = df.sort_values(["ticket_id", "ts"]).reset_index(drop=True)
    df["category"] = df.groupby("ticket_id")["category"].transform(
        lambda s: s.ffill().bfill()
    )
    df["declared_team"] = df.groupby("ticket_id")["declared_team"].transform(
        lambda s: s.ffill().bfill()
    )
    return df


def _load_tickets() -> pd.DataFrame:
    df = pd.read_csv(
        TICKETS_CSV, parse_dates=["created_at", "resolved_at"]
    )
    return df


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_dataset() -> Dataset:
    """Carga event log + tickets + organigrama + taxonomía, y registra
    vistas DuckDB sobre los DataFrames para que las capas de métricas
    puedan usar SQL cuando sea más claro que pandas puro.

    Cacheado en proceso (lru_cache) porque el event log completo se lee
    muchas veces durante una sesión del agente (una por herramienta
    invocada) y no cambia durante la ejecución.
    """
    events = _load_events()
    tickets = _load_tickets()
    org_chart = _load_json(ORG_CHART_JSON)
    taxonomy = _load_json(BUSINESS_TAXONOMY_JSON)

    con = duckdb.connect(database=":memory:")
    con.register("events", events)
    con.register("tickets", tickets)

    return Dataset(events=events, tickets=tickets, org_chart=org_chart, taxonomy=taxonomy, con=con)


def actor_to_declared_team_map(dataset: Dataset | None = None) -> dict[str, str]:
    """actor_hash -> declared_team, según org_chart_declared.json (membresía oficial)."""
    dataset = dataset or load_dataset()
    return {
        member["actor_id_hash"]: member["declared_team"]
        for member in dataset.org_chart["members"]
    }


def validate_dataset(dataset: Dataset | None = None) -> dict:
    """Chequeos de sanidad básicos: conteos esperados, estados válidos,
    columnas requeridas presentes. Lanza AssertionError si algo no cuadra.
    Devuelve un dict de resumen para loguear/mostrar.
    """
    dataset = dataset or load_dataset()
    events, tickets = dataset.events, dataset.tickets

    n_tickets_events = events["ticket_id"].nunique()
    n_tickets_summary = len(tickets)
    n_events = len(events)

    unknown_to_states = set(events["to_state"].dropna().unique()) - set(CANONICAL_STATES)
    unknown_from_states = set(events["from_state"].dropna().unique()) - set(CANONICAL_STATES)

    assert n_tickets_summary == 6000, f"esperaba 6000 tickets, encontré {n_tickets_summary}"
    assert 30000 <= n_events <= 45000, f"esperaba ~37000 eventos, encontré {n_events}"
    assert n_tickets_events == n_tickets_summary, (
        f"ticket_ids en event log ({n_tickets_events}) no cuadra con tickets.csv "
        f"({n_tickets_summary})"
    )
    assert not unknown_to_states, f"estados to_state desconocidos: {unknown_to_states}"
    assert not unknown_from_states, f"estados from_state desconocidos: {unknown_from_states}"

    return {
        "n_events": n_events,
        "n_tickets": n_tickets_summary,
        "event_types": events["event_type"].value_counts().to_dict(),
        "categories": sorted(tickets["category"].unique().tolist()),
        "declared_teams": sorted(tickets["declared_team"].unique().tolist()),
        "date_range": (events["ts"].min().isoformat(), events["ts"].max().isoformat()),
    }


if __name__ == "__main__":
    summary = validate_dataset()
    import pprint

    pprint.pprint(summary)
