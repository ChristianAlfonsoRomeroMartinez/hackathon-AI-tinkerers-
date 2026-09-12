"""
Capa 1 — Métricas de flujo (determinista).

Todo cálculo aquí es pandas/DuckDB puro. Nada de esto invoca un LLM ni
"estima": son agregaciones directas sobre el event log.

Terminología:
- queue time: tiempo que un ticket pasa ESPERANDO en un estado antes de que
  alguien actúe sobre él (proxy: tiempo entre entrar a un estado y la
  siguiente transición que sale de él, sea cual sea el actor).
- touch time: no se puede medir directamente de este event log (no hay
  eventos de "empecé a trabajar" vs "dejé de trabajar" dentro de un estado);
  se documenta como limitación y se omite en vez de inventarlo.
- lead time: tiempo total created -> Done (ya viene precalculado en
  tickets.csv como lead_time_hours para tickets resueltos).
"""

from __future__ import annotations

import pandas as pd

from .data_loader import Dataset, load_dataset


def _state_intervals(events: pd.DataFrame) -> pd.DataFrame:
    """Reconstruye, por ticket, cada intervalo (estado, entrada, salida).

    Un ticket entra a `to_state` en el ts de una transición/creación, y sale
    de ese estado en el ts de la SIGUIENTE fila de ese mismo ticket (sea
    transition o reassignment). El último estado de un ticket (a menudo
    "Done", o el estado abierto si el ticket sigue sin resolver) no tiene
    salida observada y se descarta del cálculo de queue time (censura por
    la derecha) para no subestimar la cola con un tiempo de 0 o inflarla con
    "ahora".
    """
    ev = events.sort_values(["ticket_id", "ts"]).copy()
    ev["next_ts"] = ev.groupby("ticket_id")["ts"].shift(-1)
    ev["state"] = ev["to_state"]
    ev["queue_hours"] = (ev["next_ts"] - ev["ts"]).dt.total_seconds() / 3600.0

    intervals = ev.dropna(subset=["next_ts"]).copy()
    return intervals[
        ["ticket_id", "state", "ts", "next_ts", "queue_hours", "category", "declared_team"]
    ]


def get_state_queue_times(
    state: str | None = None,
    category: str | None = None,
    declared_team: str | None = None,
    dataset: Dataset | None = None,
) -> dict:
    """Tiempo mediano/p90 en cada estado del flujo (o en `state` si se filtra).

    Devuelve, por estado: n (número de intervalos observados), p50_hours,
    p90_hours, mean_hours. Ordenado descendente por p90_hours para que el
    outlier de cola salte a la vista primero.
    """
    dataset = dataset or load_dataset()
    intervals = _state_intervals(dataset.events)

    if category is not None:
        intervals = intervals[intervals["category"] == category]
    if declared_team is not None:
        intervals = intervals[intervals["declared_team"] == declared_team]
    if state is not None:
        intervals = intervals[intervals["state"] == state]

    if intervals.empty:
        return {"filters": {"state": state, "category": category, "declared_team": declared_team}, "states": []}

    grouped = intervals.groupby("state")["queue_hours"]
    summary = grouped.agg(
        n="count",
        mean_hours="mean",
        p50_hours=lambda s: s.quantile(0.5),
        p90_hours=lambda s: s.quantile(0.9),
        max_hours="max",
    ).reset_index()
    summary = summary.sort_values("p90_hours", ascending=False)

    return {
        "filters": {"state": state, "category": category, "declared_team": declared_team},
        "states": summary.round(2).to_dict(orient="records"),
    }


def get_flow_metrics(
    team: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    dataset: Dataset | None = None,
) -> dict:
    """Panorama de flujo agrupable por equipo o categoría.

    Incluye:
    - lead_time p50/p90 (solo tickets resueltos, i.e. resolved_at no nulo)
    - tasa de reapertura (reopened=True / total)
    - aging del WIP actual (tickets sin resolved_at): p50/p90 de horas
      transcurridas desde created_at hasta "ahora" = max ts observado en
      el dataset (no datetime.now(), para que el resultado sea reproducible
      sobre datos históricos fijos).
    - queue vs. "resto" por estado, delegando a get_state_queue_times.
    """
    dataset = dataset or load_dataset()
    tickets = dataset.tickets.copy()

    if team is not None:
        tickets = tickets[tickets["declared_team"] == team]
    if category is not None:
        tickets = tickets[tickets["category"] == category]
    if date_from is not None:
        tickets = tickets[tickets["created_at"] >= pd.Timestamp(date_from)]
    if date_to is not None:
        tickets = tickets[tickets["created_at"] <= pd.Timestamp(date_to)]

    if tickets.empty:
        return {"filters": {"team": team, "category": category}, "n_tickets": 0}

    resolved = tickets.dropna(subset=["resolved_at"])
    wip = tickets[tickets["resolved_at"].isna()]

    now = dataset.events["ts"].max()
    wip_aging_hours = (now - wip["created_at"]).dt.total_seconds() / 3600.0

    # estado actual de cada ticket WIP = to_state de su último evento conocido
    wip_by_state: list[dict] = []
    if not wip.empty:
        last_event = (
            dataset.events[dataset.events["ticket_id"].isin(wip["ticket_id"])]
            .sort_values("ts")
            .groupby("ticket_id")
            .last()[["to_state"]]
            .rename(columns={"to_state": "current_state"})
        )
        wip_current = wip.merge(last_event, left_on="ticket_id", right_index=True)
        wip_current["aging_hours"] = (now - wip_current["created_at"]).dt.total_seconds() / 3600.0
        for st, grp in wip_current.groupby("current_state"):
            wip_by_state.append(
                {
                    "state": st,
                    "n": int(len(grp)),
                    "aging_hours_p50": round(float(grp["aging_hours"].quantile(0.5)), 1),
                    "aging_hours_max": round(float(grp["aging_hours"].max()), 1),
                    "oldest_ticket_id": grp.loc[grp["aging_hours"].idxmax(), "ticket_id"],
                }
            )
        wip_by_state.sort(key=lambda d: d["aging_hours_max"], reverse=True)

    lead_time = resolved["lead_time_hours"]

    result = {
        "filters": {"team": team, "category": category, "date_from": date_from, "date_to": date_to},
        "n_tickets": int(len(tickets)),
        "n_resolved": int(len(resolved)),
        "n_wip": int(len(wip)),
        "lead_time_hours": {
            "p50": round(float(lead_time.quantile(0.5)), 2) if len(lead_time) else None,
            "p90": round(float(lead_time.quantile(0.9)), 2) if len(lead_time) else None,
            "mean": round(float(lead_time.mean()), 2) if len(lead_time) else None,
        },
        "reopen_rate": round(float(tickets["reopened"].mean()), 4),
        "mean_reassignments": round(float(tickets["reassignments"].mean()), 2),
        "wip_aging_hours": {
            "p50": round(float(wip_aging_hours.quantile(0.5)), 2) if len(wip_aging_hours) else None,
            "p90": round(float(wip_aging_hours.quantile(0.9)), 2) if len(wip_aging_hours) else None,
        },
        "wip_by_current_state": wip_by_state,
        "cross_team_flow_rate": round(float(tickets["is_cross_team_flow"].mean()), 4)
        if "is_cross_team_flow" in tickets.columns
        else None,
    }

    queue = get_state_queue_times(category=category, declared_team=team, dataset=dataset)
    result["state_queue_times"] = queue["states"]

    return result


if __name__ == "__main__":
    import json

    print("=== get_flow_metrics() sin filtros ===")
    print(json.dumps(get_flow_metrics(), indent=2, default=str))

    print("\n=== get_state_queue_times() sin filtros, ordenado por p90 ===")
    print(json.dumps(get_state_queue_times(), indent=2, default=str))
