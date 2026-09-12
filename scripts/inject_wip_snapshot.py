"""
Inyección de snapshot de WIP realista sobre el dataset sintético.

Por qué existe este script
---------------------------
El generador original resuelve el 100% de los 6.000 tickets (todo ticket
tiene `resolved_at`). Eso es correcto para calibrar las 7 patologías sobre
un período histórico cerrado, pero significa que `wip_aging_hours` (Fase 1,
`get_flow_metrics`) siempre da `null` — no hay ningún ticket "actualmente
abierto" que mostrar en el informe. Para una demo que se presenta como
"agente sobre datos operacionales en vivo", eso es una laguna de
funcionalidad, no un hallazgo real.

Qué hace, exactamente
----------------------
Selecciona un pequeño subconjunto de tickets (target ~45 de 6000, ~0.75%,
calibrado con Ley de Little: WIP_estado ≈ tasa_llegada_estado × duración_media
del estado, usando los propios promedios ya medidos en el dataset) y trunca
su historial de eventos en el punto donde entraron a un estado objetivo,
descartando los eventos posteriores (incluida la eventual transición a
"Done"). Solo se trunca en estados que el ticket realmente visitó — no se
inventan transiciones que no ocurrieron, solo se "congela" el reloj antes de
que el ticket saliera de un estado real.

Esto es una intervención declarada y determinista (semilla fija), no un
intento de simular una patología adicional: es exclusivamente para poblar
la sección de WIP/aging del informe con datos consistentes con el resto del
dataset. El impacto sobre las métricas agregadas usadas para calibrar las 7
patologías es marginal (<1% de los tickets, todos re-etiquetados como
"aún no resueltos" en vez de eliminados).

Idempotencia: este script debe correrse UNA sola vez sobre los archivos
originales (100% resueltos). Si detecta que ya hay tickets sin resolver
(wip existente) aborta para no truncar dos veces.

Salida: sobrescribe data/synth/event_log.csv, event_log.jsonl, tickets.csv
y escribe data/synth/WIP_INJECTION_NOTES.md con el detalle de qué se tocó.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "synth"
SEED = 20260912

# Conteo objetivo de WIP por estado, calibrado con Ley de Little a partir de
# las medias observadas en get_state_queue_times() (ver PROGRESS.md fase 2):
#   WIP_estado ~= (n_intervalos_estado / dias_totales_dataset) * media_horas_estado / 24
# Redondeado a mano para dar una distribución legible en la demo, sesgada
# deliberadamente para que el cuello de botella de aprobación de seguridad
# sea visible también en el snapshot "en vivo", no solo en el histórico.
TARGET_WIP_BY_STATE = {
    "Pending Approval Security": 15,
    "In Progress": 14,
    "Backlog": 5,
    "Triage": 5,
    "In Review": 3,
    "Waiting Handoff": 2,
    "Reopened": 1,
}

# De los tickets elegidos por estado, cuántos se fuerzan a ser "neglect"
# antiguo (creados hace mucho y aún abiertos) en vez de recientes, para que
# el informe pueda citar 1-2 casos extremos de abandono real además del
# patrón agregado. Solo aplica a Pending Approval Security (es el estado
# donde el abandono prolongado es coherente con la patología ya plantada).
OLD_NEGLECT_COUNT = 2


def main() -> None:
    events = pd.read_csv(DATA_DIR / "event_log.csv", parse_dates=["ts"])
    tickets = pd.read_csv(DATA_DIR / "tickets.csv", parse_dates=["created_at", "resolved_at"])

    if tickets["resolved_at"].isna().any():
        raise SystemExit(
            "Ya existen tickets sin resolver en tickets.csv — parece que este "
            "script ya corrió antes. Abortando para no truncar dos veces."
        )

    rng = random.Random(SEED)
    events = events.sort_values(["ticket_id", "ts"]).reset_index(drop=True)

    # ticket_id -> lista de índices (en `events`) de sus eventos, en orden.
    ticket_event_idx: dict[str, list[int]] = events.groupby("ticket_id").indices  # type: ignore

    already_picked: set[str] = set()
    truncation_plan: dict[str, int] = {}  # ticket_id -> índice (en events) donde cortar (inclusive)
    injected_meta: list[dict] = []

    max_created = tickets["created_at"].max()

    for state, target_n in TARGET_WIP_BY_STATE.items():
        # candidatos: tickets que en algún momento entraron a `state` y que
        # aún no fueron elegidos para otro estado.
        mask = (events["to_state"] == state) & (~events["ticket_id"].isin(already_picked))
        candidates = events.loc[mask, ["ticket_id", "ts"]].merge(
            tickets[["ticket_id", "created_at"]], on="ticket_id"
        )
        if candidates.empty:
            continue

        n_old = OLD_NEGLECT_COUNT if state == "Pending Approval Security" else 0
        n_old = min(n_old, target_n, len(candidates))

        # "neglect" antiguo: el 10% más viejo por created_at de los candidatos
        # (casos deliberadamente extremos para evidencia narrativa).
        old_pool = candidates.sort_values("created_at").head(max(1, len(candidates) // 10))
        old_pick_ids = rng.sample(
            old_pool["ticket_id"].tolist(), k=min(n_old, len(old_pool))
        )

        remaining_pool = candidates[~candidates["ticket_id"].isin(old_pick_ids)]
        # sesgo a reciente: candidatos creados en los últimos N días antes del
        # último `created_at` del dataset, para que el "aging" de un snapshot
        # en vivo sea creíble (días, no meses). N crece si un estado es raro
        # y no hay suficientes candidatos en la ventana más corta.
        recent_pool = pd.DataFrame()
        for window_days in (14, 21, 30, 45, 60, 90):
            cutoff = max_created - pd.Timedelta(days=window_days)
            recent_pool = remaining_pool[remaining_pool["created_at"] >= cutoff]
            if len(recent_pool) >= (target_n - len(old_pick_ids)):
                break
        n_recent = min(target_n - len(old_pick_ids), len(recent_pool))
        recent_pick_ids = rng.sample(recent_pool["ticket_id"].tolist(), k=n_recent)

        picked_ids = old_pick_ids + recent_pick_ids
        already_picked.update(picked_ids)

        for tid in picked_ids:
            tid_events = events.iloc[ticket_event_idx[tid]]
            # última vez que el ticket entró a `state` (si hubo reopen loops,
            # congelamos en la visita más reciente, la más plausible como
            # "estado actual").
            cut_row = tid_events[tid_events["to_state"] == state].iloc[-1]
            cut_idx = cut_row.name  # índice original en `events`
            truncation_plan[tid] = cut_idx
            injected_meta.append(
                {
                    "ticket_id": tid,
                    "frozen_state": state,
                    "frozen_at": cut_row["ts"].isoformat(),
                    "created_at": tickets.loc[tickets["ticket_id"] == tid, "created_at"].iloc[0].isoformat(),
                    "neglect_case": tid in old_pick_ids,
                }
            )

    # --- aplicar truncamiento ---
    keep_mask = pd.Series(True, index=events.index)
    for tid, cut_idx in truncation_plan.items():
        idx_list = ticket_event_idx[tid]
        pos = list(idx_list).index(cut_idx)
        drop_idx = idx_list[pos + 1 :]  # todo lo posterior al corte, para ese ticket
        keep_mask.loc[drop_idx] = False

    truncated_events = events.loc[keep_mask].reset_index(drop=True)

    # --- recalcular tickets.csv para los tickets truncados ---
    tickets = tickets.set_index("ticket_id")
    for tid in truncation_plan:
        tid_events = truncated_events[truncated_events["ticket_id"] == tid]
        tickets.loc[tid, "resolved_at"] = pd.NaT
        tickets.loc[tid, "lead_time_hours"] = float("nan")
        tickets.loc[tid, "reassignments"] = int((tid_events["event_type"] == "reassignment").sum())
        tickets.loc[tid, "reopened"] = bool((tid_events["to_state"] == "Reopened").any())
    tickets = tickets.reset_index()

    # --- escribir CSV ---
    # IMPORTANTE: el `events` cargado arriba viene DIRECTO del CSV original
    # (pd.read_csv sin parsear payload_json), así que su columna
    # `payload_json` ya trae el contenido original intacto de CADA fila
    # (created/transition/reassignment). El truncamiento solo BORRA filas
    # completas (eventos posteriores al corte) — nunca modifica el
    # contenido de las filas que sí sobreviven, así que basta con
    # seleccionar las columnas originales tal cual. (Bug corregido: una
    # versión anterior de este script reconstruía payload_json desde
    # columnas aplanadas que no existían en este DataFrame crudo, lo que
    # vaciaba el payload de TODO el event log, no solo de los tickets
    # truncados. No repetir ese error.)
    out_csv = truncated_events[
        ["ticket_id", "ts", "event_type", "actor_hash", "from_state", "to_state", "payload_json"]
    ]
    out_csv.to_csv(DATA_DIR / "event_log.csv", index=False)

    with open(DATA_DIR / "event_log.jsonl", "w", encoding="utf-8") as f:
        for _, row in out_csv.iterrows():
            rec = {
                "ticket_id": row["ticket_id"],
                "ts": row["ts"].isoformat() if isinstance(row["ts"], pd.Timestamp) else row["ts"],
                "event_type": row["event_type"],
                "actor_hash": row["actor_hash"],
                "from_state": None if pd.isna(row["from_state"]) else row["from_state"],
                "to_state": row["to_state"],
                "payload": json.loads(row["payload_json"]),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    tickets.to_csv(DATA_DIR / "tickets.csv", index=False)

    # --- notas de auditoría ---
    notes = [
        "# Inyección de snapshot WIP — notas de auditoría",
        "",
        f"Script: `scripts/inject_wip_snapshot.py`, semilla determinista `{SEED}`.",
        "",
        "El dataset original resuelve el 100% de los 6.000 tickets (no hay WIP).",
        "Para demostrar la funcionalidad de aging de WIP en vivo, se congeló el",
        f"historial de **{len(truncation_plan)} tickets** ({100*len(truncation_plan)/6000:.2f}% del total)",
        "en un estado que realmente visitaron, descartando sus eventos posteriores",
        "(incluida la eventual resolución). No se inventaron transiciones nuevas:",
        "solo se recortó el historial real en un punto real.",
        "",
        "Conteo objetivo por estado (calibrado con Ley de Little sobre las medias",
        "de `get_state_queue_times()`):",
        "",
    ]
    for state, n in TARGET_WIP_BY_STATE.items():
        actual = sum(1 for m in injected_meta if m["frozen_state"] == state)
        notes.append(f"- {state}: objetivo {n}, aplicado {actual}")
    notes += [
        "",
        f"De estos, {sum(1 for m in injected_meta if m['neglect_case'])} son casos de",
        "abandono deliberadamente antiguo (creados hace mucho, aún abiertos) para dar",
        "evidencia narrativa de negligencia extrema, no solo el patrón agregado.",
        "",
        "Impacto sobre la calibración de las 7 patologías (`ground_truth.json`):",
        f"marginal — {len(truncation_plan)}/6000 tickets ({100*len(truncation_plan)/6000:.2f}%) pasaron",
        "de 'resuelto' a 'abierto', sin alterar categoría, equipo declarado, ni los",
        "flags precalculados de patología (is_hidden_operational_debt, hero_involved,",
        "hero_absence_hit, is_cross_team_flow) en tickets.csv.",
        "",
        "## Tickets afectados",
        "",
        "| ticket_id | estado congelado | congelado en | creado | caso de abandono |",
        "|---|---|---|---|---|",
    ]
    for m in sorted(injected_meta, key=lambda x: x["frozen_state"]):
        notes.append(
            f"| {m['ticket_id']} | {m['frozen_state']} | {m['frozen_at']} | "
            f"{m['created_at']} | {'sí' if m['neglect_case'] else 'no'} |"
        )

    with open(DATA_DIR / "WIP_INJECTION_NOTES.md", "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")

    print(f"Truncados {len(truncation_plan)} tickets. Detalle en data/synth/WIP_INJECTION_NOTES.md")
    print(f"Eventos: {len(events)} -> {len(truncated_events)}")


if __name__ == "__main__":
    main()
