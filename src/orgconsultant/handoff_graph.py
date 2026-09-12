"""
Capa 1/2 — Grafo de handoffs (determinista, NetworkX).

Construye el grafo dirigido y pesado de colaboración real: un nodo por
actor_hash, una arista dirigida actor_A -> actor_B con peso = número de
veces que un ticket pasó de A a B en eventos consecutivos.

Esta herramienta SOLO devuelve datos crudos (centralidad, comunidades,
metadata declarada por actor). El contraste "¿la comunidad detectada
coincide con el equipo declarado?" es interpretación y le corresponde al
LLM orquestador, no a esta función — a propósito no se calcula aquí ningún
"score de desalineación" ni se decide si hay un silo mal cortado.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd

try:
    import community as community_louvain  # python-louvain
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Falta python-louvain. Instala con: pip install python-louvain"
    ) from exc

from .data_loader import Dataset, actor_to_declared_team_map, load_dataset


def _build_handoff_edges(events: pd.DataFrame, min_weight: int) -> pd.DataFrame:
    """Una fila por handoff (A->B) con su peso, agregando TODOS los eventos
    del event log (created + transition + reassignment) en orden temporal
    por ticket — un handoff es cualquier cambio de actor entre dos eventos
    consecutivos del mismo ticket, sin importar el tipo de evento.
    """
    ev = events.sort_values(["ticket_id", "ts"]).copy()
    ev["prev_actor"] = ev.groupby("ticket_id")["actor_hash"].shift(1)
    handoffs = ev.dropna(subset=["prev_actor"])
    handoffs = handoffs[handoffs["prev_actor"] != handoffs["actor_hash"]]

    edges = (
        handoffs.groupby(["prev_actor", "actor_hash"])
        .size()
        .reset_index(name="weight")
        .rename(columns={"prev_actor": "source", "actor_hash": "target"})
    )
    return edges[edges["weight"] >= min_weight].reset_index(drop=True)


def get_handoff_graph(min_weight: int = 1, dataset: Dataset | None = None) -> dict:
    """Grafo de handoffs actor-a-actor + centralidad + comunidades Louvain.

    Args:
        min_weight: descarta aristas con menos de este número de handoffs
            observados (reduce ruido de traspasos únicos/accidentales antes
            de calcular centralidad y comunidades).

    Devuelve:
        nodes: por actor_hash — declared_team y role (de org_chart_declared.json),
            grado ponderado de entrada/salida, betweenness centrality
            (versión no ponderada y versión ponderada por distancia = 1/peso,
            de forma que pares que colaboran MUCHO quedan "más cerca"),
            y el id de comunidad Louvain al que quedó asignado.
        edges: lista de aristas fuente/destino/peso que sobrevivieron el filtro.
        communities: comunidad_id -> lista de actor_hash.
        modularity: modularidad de la partición Louvain encontrada (0-1 aprox,
            más alto = comunidades más "limpias" estructuralmente).
    """
    dataset = dataset or load_dataset()
    edges_df = _build_handoff_edges(dataset.events, min_weight)
    actor_team = actor_to_declared_team_map(dataset)
    actor_role = {m["actor_id_hash"]: m["role"] for m in dataset.org_chart["members"]}

    G = nx.DiGraph()
    for _, row in edges_df.iterrows():
        G.add_edge(row["source"], row["target"], weight=int(row["weight"]))

    if G.number_of_nodes() == 0:
        return {
            "min_weight": min_weight,
            "n_nodes": 0,
            "n_edges": 0,
            "nodes": [],
            "edges": [],
            "communities": {},
            "modularity": None,
        }

    for _, _, d in G.edges(data=True):
        d["distance"] = 1.0 / d["weight"]

    betw_unweighted = nx.betweenness_centrality(G, weight=None, normalized=True)
    betw_weighted = nx.betweenness_centrality(G, weight="distance", normalized=True)

    # Louvain requiere grafo no dirigido; se suman los pesos de ambas direcciones
    # de cada par (A->B y B->A se tratan como una sola relación de colaboración).
    UG = nx.Graph()
    for u, v, d in G.edges(data=True):
        w = d["weight"]
        if UG.has_edge(u, v):
            UG[u][v]["weight"] += w
        else:
            UG.add_edge(u, v, weight=w)

    partition = community_louvain.best_partition(UG, weight="weight", random_state=42)
    modularity = community_louvain.modularity(partition, UG, weight="weight")

    communities: dict[int, list[str]] = {}
    for actor, comm_id in partition.items():
        communities.setdefault(comm_id, []).append(actor)

    nodes = []
    for actor in G.nodes():
        in_w = sum(d["weight"] for _, _, d in G.in_edges(actor, data=True))
        out_w = sum(d["weight"] for _, _, d in G.out_edges(actor, data=True))
        nodes.append(
            {
                "actor_hash": actor,
                "declared_team": actor_team.get(actor),
                "role": actor_role.get(actor),
                "weighted_in_degree": int(in_w),
                "weighted_out_degree": int(out_w),
                "betweenness_unweighted": round(betw_unweighted.get(actor, 0.0), 4),
                "betweenness_weighted": round(betw_weighted.get(actor, 0.0), 4),
                "louvain_community": partition.get(actor),
            }
        )
    nodes.sort(key=lambda n: n["betweenness_weighted"], reverse=True)

    edges = edges_df.sort_values("weight", ascending=False).to_dict(orient="records")

    return {
        "min_weight": min_weight,
        "n_nodes": G.number_of_nodes(),
        "n_edges": G.number_of_edges(),
        "nodes": nodes,
        "edges": edges,
        "communities": {str(k): v for k, v in communities.items()},
        "modularity": round(modularity, 4),
    }


if __name__ == "__main__":
    import json

    result = get_handoff_graph()
    print(f"n_nodes={result['n_nodes']} n_edges={result['n_edges']} modularity={result['modularity']}")
    print("\n=== Top 5 por betweenness_weighted (candidatos a SPOF) ===")
    for n in result["nodes"][:5]:
        print(n)

    print("\n=== Comunidades Louvain vs declared_team ===")
    actor_team = {n["actor_hash"]: n["declared_team"] for n in result["nodes"]}
    for comm_id, members in sorted(result["communities"].items(), key=lambda kv: int(kv[0])):
        teams = [actor_team.get(m) for m in members]
        print(f"community {comm_id} ({len(members)} actores): equipos declarados = {teams}")
