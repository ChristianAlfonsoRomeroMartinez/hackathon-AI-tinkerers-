"""
Capa 4 — Simulación what-if (determinista: Ley de Little + recorte directo
de intervalos observados; sin SimPy por ahora — no hace falta modelar colas
con recursos limitados para los cambios que pide este dataset, un cálculo
analítico alcanza y es más auditable/explicable en el informe).

Ley de Little: WIP = throughput (tickets/día) × lead_time (días).

Enfoque: en vez de mover el promedio "a mano", se recalcula el lead time
TICKET POR TICKET restando el tiempo de cola que ese ticket específico pasó
en el estado afectado (si nunca pasó por ahí, no cambia). Esto es más
preciso que escalar el promedio global y permite recalcular p50/p90 reales
del escenario simulado, no solo la media.
"""

from __future__ import annotations

import pandas as pd

from .data_loader import Dataset, load_dataset
from .flow_metrics import _state_intervals

DEFAULT_COST_PER_HOUR_USD = 45.0  # declarado explícitamente; ajustable por el usuario del informe

# Nota metodológica importante para el informe: "impacto económico" aquí es
# horas-en-cola × costo/hora, tal como pide la especificación del proyecto
# (Fase de orquestación, paso 5). Es un proxy de "costo de demora" (cost of
# delay / capital inmovilizado en trabajo sin terminar), NO nómina literal
# de las personas involucradas — nadie está "trabajando" mientras un ticket
# espera en cola. Debe declararse así explícitamente en el Anexo
# Metodológico del informe final para no sobre-interpretar la cifra como
# ahorro directo en planilla.
DAYS_PER_YEAR = 365
HOURS_PER_DAY = 24


def _baseline_tickets(dataset: Dataset, category: str | None, team: str | None) -> pd.DataFrame:
    tickets = dataset.tickets.dropna(subset=["resolved_at"]).copy()
    if category is not None:
        tickets = tickets[tickets["category"] == category]
    if team is not None:
        tickets = tickets[tickets["declared_team"] == team]
    return tickets


def _dataset_span_days(dataset: Dataset) -> float:
    span = dataset.events["ts"].max() - dataset.events["ts"].min()
    return max(span.total_seconds() / 86400.0, 1.0)


def simulate_change(
    lever_type: str,
    target_state: str | None = None,
    reduction_pct: float = 1.0,
    category: str | None = None,
    team: str | None = None,
    cost_per_hour_usd: float = DEFAULT_COST_PER_HOUR_USD,
    dataset: Dataset | None = None,
    baseline_tickets: pd.DataFrame | None = None,
    remaining_queue_hours: pd.Series | None = None,
) -> dict:
    """Simula un cambio simple y recalcula lead time / WIP esperado (Ley de
    Little) y el ahorro económico anualizado.

    lever_type:
        "remove_state" — elimina por completo el tiempo de cola RESTANTE de
            `target_state` para los tickets que pasaron por ahí
            (reduction_pct se ignora, equivale a 1.0).
        "reduce_state_queue_time" — recorta el tiempo de cola RESTANTE de
            `target_state` en `reduction_pct` (0.0-1.0).

    baseline_tickets / remaining_queue_hours: si se pasan (típicamente el
        resultado de un horizonte anterior en simulate_horizon_cascade), se
        usan como punto de partida en vez de recalcular desde el dataset
        original — así los horizontes encadenan de verdad: `reduction_pct`
        en el horizonte N se aplica sobre lo que QUEDABA tras el horizonte
        N-1, no sobre la cola original completa otra vez (ese fue un bug
        real detectado corriendo el agente: sin esto, sumar el "ahorro" de
        varios horizontes sobrestima el total porque cada uno se calculaba
        contra la cola original de cero).
    """
    dataset = dataset or load_dataset()
    if lever_type not in {"remove_state", "reduce_state_queue_time"}:
        raise ValueError(f"lever_type desconocido: {lever_type}")
    if target_state is None:
        raise ValueError("target_state es obligatorio para este lever_type")

    effective_reduction = 1.0 if lever_type == "remove_state" else reduction_pct

    tickets = (
        baseline_tickets.copy()
        if baseline_tickets is not None
        else _baseline_tickets(dataset, category, team)
    )
    baseline_lead_time = tickets["lead_time_hours"].copy()

    if remaining_queue_hours is None:
        # primer horizonte: derivar la cola real restante desde el event log
        intervals = _state_intervals(dataset.events)
        intervals = intervals[intervals["state"] == target_state]
        intervals = intervals[intervals["ticket_id"].isin(tickets["ticket_id"])]
        # un ticket puede visitar el mismo estado más de una vez (reopen loops);
        # sumamos toda su cola en ese estado antes de recortar.
        remaining_queue_hours = intervals.groupby("ticket_id")["queue_hours"].sum()

    delta_by_ticket = remaining_queue_hours * effective_reduction
    new_remaining_queue_hours = remaining_queue_hours - delta_by_ticket

    tickets = tickets.set_index("ticket_id")
    tickets["delta_hours"] = 0.0
    tickets.loc[delta_by_ticket.index, "delta_hours"] = delta_by_ticket.values
    tickets["lead_time_hours"] = (tickets["lead_time_hours"] - tickets["delta_hours"]).clip(lower=0.1)
    tickets = tickets.reset_index()

    span_days = _dataset_span_days(dataset)
    n_tickets = len(tickets)
    throughput_per_day = n_tickets / span_days

    baseline_mean_h = float(baseline_lead_time.mean())
    new_mean_h = float(tickets["lead_time_hours"].mean())

    baseline_wip = throughput_per_day * (baseline_mean_h / HOURS_PER_DAY)
    new_wip = throughput_per_day * (new_mean_h / HOURS_PER_DAY)

    n_affected = int((tickets["delta_hours"] > 0).sum())
    total_hours_saved_in_window = float(tickets["delta_hours"].sum())
    # anualiza extrapolando el ahorro observado en la ventana del dataset a un año
    annualized_hours_saved = total_hours_saved_in_window * (DAYS_PER_YEAR / span_days)
    annualized_cost_saved_usd = annualized_hours_saved * cost_per_hour_usd

    return {
        "lever": {
            "lever_type": lever_type,
            "target_state": target_state,
            "reduction_pct": effective_reduction,
            "filters": {"category": category, "team": team},
        },
        "n_tickets": n_tickets,
        "n_tickets_affected": n_affected,
        "lead_time_hours": {
            "baseline_mean": round(baseline_mean_h, 2),
            "baseline_p50": round(float(baseline_lead_time.quantile(0.5)), 2),
            "baseline_p90": round(float(baseline_lead_time.quantile(0.9)), 2),
            "new_mean": round(new_mean_h, 2),
            "new_p50": round(float(tickets["lead_time_hours"].quantile(0.5)), 2),
            "new_p90": round(float(tickets["lead_time_hours"].quantile(0.9)), 2),
        },
        "wip_little_law": {
            "throughput_per_day": round(throughput_per_day, 3),
            "baseline_wip": round(baseline_wip, 1),
            "new_wip": round(new_wip, 1),
        },
        "economic_impact": {
            "cost_per_hour_usd": cost_per_hour_usd,
            "hours_saved_in_dataset_window": round(total_hours_saved_in_window, 1),
            "dataset_window_days": round(span_days, 1),
            "annualized_hours_saved": round(annualized_hours_saved, 1),
            "annualized_cost_saved_usd": round(annualized_cost_saved_usd, 2),
        },
        "resulting_tickets": tickets,  # para encadenar en simulate_horizon_cascade; no serializar tal cual en el informe
        "remaining_queue_hours": new_remaining_queue_hours,  # ídem — cola restante para el siguiente horizonte
    }


def simulate_horizon_cascade(
    sequence: list[dict],
    category: str | None = None,
    team: str | None = None,
    cost_per_hour_usd: float = DEFAULT_COST_PER_HOUR_USD,
    dataset: Dataset | None = None,
) -> dict:
    """Corre una secuencia de simulate_change en cadena: el resultado
    (tickets ajustados) del horizonte N es el punto de partida del N+1.

    sequence: lista de dicts, cada uno con las llaves de simulate_change
        (lever_type, target_state, reduction_pct) — category/team/dataset/
        cost_per_hour_usd se heredan del nivel de la cascada, no hace falta
        repetirlos por horizonte.

    Gobernanza (declarada, no impuesta por código): cada horizonte solo
    debería avanzar en la implementación real si el horizonte anterior
    sostiene sus métricas — eso lo evalúa el informe/humano con datos reales
    de producción, no esta simulación (que es un techo teórico optimista,
    asumiendo que cada palanca se ejecuta con éxito total).
    """
    dataset = dataset or load_dataset()
    baseline_tickets = None
    remaining_queue_hours = None
    prev_target_state = None
    horizons = []
    cumulative_annualized_savings = 0.0

    for i, step in enumerate(sequence, start=1):
        target_state = step.get("target_state")
        # el remanente de cola solo es válido para encadenar horizontes que
        # apuntan al MISMO estado — si el horizonte N+1 apunta a otro estado,
        # se recalcula desde cero (es un lever distinto, no una continuación).
        if target_state != prev_target_state:
            remaining_queue_hours = None
        result = simulate_change(
            lever_type=step["lever_type"],
            target_state=target_state,
            reduction_pct=step.get("reduction_pct", 1.0),
            category=category,
            team=team,
            cost_per_hour_usd=cost_per_hour_usd,
            dataset=dataset,
            baseline_tickets=baseline_tickets,
            remaining_queue_hours=remaining_queue_hours,
        )
        baseline_tickets = result.pop("resulting_tickets")
        remaining_queue_hours = result.pop("remaining_queue_hours")
        prev_target_state = target_state
        cumulative_annualized_savings += result["economic_impact"]["annualized_cost_saved_usd"]
        horizons.append({"horizon": i, **result})

    return {
        "n_horizons": len(horizons),
        "horizons": horizons,
        "cumulative_annualized_cost_saved_usd": round(cumulative_annualized_savings, 2),
    }


if __name__ == "__main__":
    import json

    print("=== simulate_change: eliminar Pending Approval Security ===")
    r = simulate_change("remove_state", target_state="Pending Approval Security")
    r.pop("resulting_tickets")
    print(json.dumps(r, indent=2, ensure_ascii=False))

    print("\n=== simulate_horizon_cascade: 3 horizontes progresivos ===")
    cascade = simulate_horizon_cascade(
        [
            {"lever_type": "reduce_state_queue_time", "target_state": "Pending Approval Security", "reduction_pct": 0.3},
            {"lever_type": "reduce_state_queue_time", "target_state": "Pending Approval Security", "reduction_pct": 0.5},
            {"lever_type": "remove_state", "target_state": "Pending Approval Security"},
        ]
    )
    for h in cascade["horizons"]:
        print(f"Horizonte {h['horizon']}: new_p50={h['lead_time_hours']['new_p50']}h, "
              f"ahorro anualizado=${h['economic_impact']['annualized_cost_saved_usd']:,}")
    print("Ahorro anualizado acumulado: $", cascade["cumulative_annualized_cost_saved_usd"])
