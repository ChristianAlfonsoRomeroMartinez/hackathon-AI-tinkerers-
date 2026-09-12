"""
Capa 3 — Bloques organizacionales propuestos (determinista).

Solo tiene sentido invocarlo cuando ya hay hallazgos de severidad
"organizacional" o "estratégico" (eso lo decide el LLM orquestador vía
classify_change_severity, no esta función). A partir de las comunidades de
Louvain de get_handoff_graph (la topología real de colaboración) y de qué
categorías de negocio toca cada comunidad, propone unidades por flujo de
valor — con evidencia cuantitativa citable, no una recomendación genérica.
"""

from __future__ import annotations

import pandas as pd

from .data_loader import Dataset, actor_to_declared_team_map, load_dataset
from .handoff_graph import get_handoff_graph

# Umbral por encima del cual se sugiere un rol dedicado de automatización,
# ver evidencia en el propio output (pct_operational_debt + volumen).
AUTOMATION_ROLE_THRESHOLD = 0.25


def _ticket_actors_map(dataset: Dataset) -> pd.Series:
    """ticket_id -> set(actor_hash) que tocaron ese ticket en algún evento."""
    return dataset.events.groupby("ticket_id")["actor_hash"].apply(set)


def propose_org_blocks(min_weight: int = 1, dataset: Dataset | None = None) -> dict:
    """Propone bloques organizacionales por flujo de valor real.

    Cada bloque (una comunidad Louvain del grafo de handoffs) viene con:
    - members: actor_hash + de qué equipo(s) declarado(s) vienen realmente
    - evidence: volumen y categorías de negocio que ese bloque realmente
      atiende, % de deuda operativa, % de flujo cross-team
    - role_suggestion: rol nuevo sugerido SOLO si la evidencia lo justifica
      (regla explícita y documentada, no "sugerencia libre" del LLM)
    """
    dataset = dataset or load_dataset()
    graph = get_handoff_graph(min_weight=min_weight, dataset=dataset)
    actor_team = actor_to_declared_team_map(dataset)
    actor_role = {m["actor_id_hash"]: m["role"] for m in dataset.org_chart["members"]}

    ticket_actors = _ticket_actors_map(dataset)
    tickets = dataset.tickets.copy()
    tickets["actors"] = tickets["ticket_id"].map(ticket_actors)

    blocks = []
    for comm_id, members in graph["communities"].items():
        member_set = set(members)
        touched_mask = tickets["actors"].apply(
            lambda actors: bool(actors & member_set) if isinstance(actors, set) else False
        )
        touched = tickets[touched_mask]

        declared_origin = pd.Series([actor_team.get(m) for m in members]).value_counts().to_dict()
        category_dist = touched["category"].value_counts().to_dict()
        pct_operational_debt = float(touched["is_hidden_operational_debt"].mean()) if len(touched) else 0.0
        pct_cross_team = float(touched["is_cross_team_flow"].mean()) if len(touched) else 0.0
        n_operational_debt = int(touched["is_hidden_operational_debt"].sum()) if len(touched) else 0

        role_suggestion = None
        if pct_operational_debt >= AUTOMATION_ROLE_THRESHOLD and n_operational_debt > 0:
            role_suggestion = {
                "suggested_role": "Automation/Platform Engineer dedicado",
                "justification": (
                    f"{pct_operational_debt:.1%} de los {len(touched)} tickets que atiende este "
                    f"bloque son deuda operativa repetida (is_hidden_operational_debt), "
                    f"{n_operational_debt} tickets en volumen — suficiente carga recurrente "
                    f"para justificar un rol dedicado a automatizar esa causa raíz en vez de "
                    f"seguir resolviéndola manualmente ticket por ticket."
                ),
            }

        blocks.append(
            {
                "community_id": comm_id,
                "members": [
                    {
                        "actor_hash": m,
                        "declared_team_origin": actor_team.get(m),
                        "role": actor_role.get(m),
                    }
                    for m in members
                ],
                "declared_team_origin_distribution": declared_origin,
                "evidence": {
                    "n_tickets_touched": int(len(touched)),
                    "category_distribution": category_dist,
                    "pct_operational_debt": round(pct_operational_debt, 4),
                    "pct_cross_team_flow": round(pct_cross_team, 4),
                },
                "role_suggestion": role_suggestion,
            }
        )

    return {
        "min_weight": min_weight,
        "modularity": graph["modularity"],
        "n_blocks": len(blocks),
        "blocks": blocks,
    }


if __name__ == "__main__":
    import json

    result = propose_org_blocks()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
