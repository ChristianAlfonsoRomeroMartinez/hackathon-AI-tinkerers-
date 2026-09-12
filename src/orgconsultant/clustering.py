"""
Capa 2 — Clustering semántico sobre títulos de tickets (determinista).

Decisión de implementación (documentada porque se desvía del plan original
de usar sentence-transformers): en este entorno, instalar
sentence-transformers arrastra `torch` y la descarga se estancó por más de
una hora sin completar (conexión lenta/inestable) — se abortó y se optó por
TF-IDF + reducción de dimensionalidad (TruncatedSVD) + HDBSCAN, todo con
scikit-learn (ya instalado, sin dependencias pesadas).

Esto es además un mejor ajuste para ESTE dataset específicamente: los
títulos son generados por plantillas con huecos rellenados (nombres de
servicio, IDs de cliente) — ver `root_cause_template_id` en el payload —
así que la similitud léxica de n-gramas (lo que TF-IDF captura) agrupa las
variantes de una misma plantilla tan bien o mejor que un embedding
semántico denso, sin la latencia/dependencia de un modelo neuronal.

El LLM NO participa en este cálculo — solo se le muestran después los
`get_ticket_samples()` de un cluster para que le ponga nombre/interpretación,
ya con el agrupamiento ya hecho por código.

Determinismo: TfidfVectorizer + TruncatedSVD(random_state fijo) + HDBSCAN
son deterministas dado el mismo texto de entrada y los mismos parámetros.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from .data_loader import Dataset, load_dataset

_SVD_RANDOM_STATE = 42
_SVD_COMPONENTS = 50


def _embed_titles(titles: list[str]) -> np.ndarray:
    """TF-IDF (word 1-2grams) -> TruncatedSVD -> vectores normalizados.
    Reemplaza a un embedding neuronal (ver docstring del módulo)."""
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
        sublinear_tf=True,
    )
    tfidf = vectorizer.fit_transform(titles)

    n_components = min(_SVD_COMPONENTS, tfidf.shape[0] - 1, tfidf.shape[1] - 1)
    if n_components < 2:
        # muy pocos documentos para SVD útil — usar TF-IDF denso directo
        return normalize(tfidf.toarray())

    svd = TruncatedSVD(n_components=n_components, random_state=_SVD_RANDOM_STATE)
    reduced = svd.fit_transform(tfidf)
    return normalize(reduced)


def _tickets_with_title(dataset: Dataset) -> pd.DataFrame:
    """tickets.csv no trae `title` — solo vive en el payload del evento
    `created`. Se reconstruye aquí en vez de duplicarlo en data_loader
    porque solo esta capa lo necesita.
    """
    created = dataset.events[dataset.events["event_type"] == "created"][
        ["ticket_id", "title", "category", "declared_team"]
    ].drop_duplicates(subset="ticket_id")
    return created


@lru_cache(maxsize=32)
def _cluster_cache_key(category: str | None, min_cluster_size: int) -> tuple:
    """Solo para forzar que el resultado de _run_clustering sea cacheado
    por combinación de parámetros (lru_cache no puede cachear DataFrames
    directamente de forma legible, así que el cache real vive en
    _run_clustering; esta función existe únicamente como llave estable).
    """
    return (category, min_cluster_size)


@lru_cache(maxsize=32)
def _run_clustering(category: str | None, min_cluster_size: int) -> pd.DataFrame:
    import hdbscan

    dataset = load_dataset()
    titles_df = _tickets_with_title(dataset)
    if category is not None:
        titles_df = titles_df[titles_df["category"] == category]
    titles_df = titles_df.reset_index(drop=True)

    if len(titles_df) < min_cluster_size:
        titles_df["cluster_id"] = -1
        return titles_df

    embeddings = _embed_titles(titles_df["title"].tolist())

    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean")
    labels = clusterer.fit_predict(embeddings)
    titles_df["cluster_id"] = labels
    return titles_df


def find_ticket_clusters(
    category: str | None = None, min_cluster_size: int = 10
) -> dict:
    """Clusteriza títulos de tickets por similitud semántica (HDBSCAN sobre
    embeddings de sentence-transformers). `-1` es ruido (no asignado a
    ningún cluster, comportamiento estándar de HDBSCAN, no un error).

    Devuelve, por cluster: tamaño, distribución de categoría/equipo
    declarado dentro del cluster, y 3 títulos de muestra directamente (para
    que el LLM pueda decidir si vale la pena pedir más con
    get_ticket_samples antes de nombrar el cluster).
    """
    df = _run_clustering(category, min_cluster_size)

    clusters = []
    for cid, grp in df.groupby("cluster_id"):
        clusters.append(
            {
                "cluster_id": int(cid),
                "is_noise": bool(cid == -1),
                "size": int(len(grp)),
                "category_distribution": grp["category"].value_counts().to_dict(),
                "declared_team_distribution": grp["declared_team"].value_counts().to_dict(),
                "sample_titles": grp["title"].head(3).tolist(),
            }
        )
    clusters.sort(key=lambda c: (c["is_noise"], -c["size"]))

    return {
        "filters": {"category": category, "min_cluster_size": min_cluster_size},
        "n_tickets_considered": int(len(df)),
        "n_clusters": len([c for c in clusters if not c["is_noise"]]),
        "clusters": clusters,
    }


def get_ticket_samples(
    cluster_id: int,
    n: int = 5,
    category: str | None = None,
    min_cluster_size: int = 10,
) -> dict:
    """Tickets representativos de un cluster ya calculado por
    find_ticket_clusters (mismos filtros `category`/`min_cluster_size` —
    deben coincidir con la llamada que produjo ese cluster_id, porque el
    clustering se recachea por esa combinación de parámetros).
    """
    df = _run_clustering(category, min_cluster_size)
    grp = df[df["cluster_id"] == cluster_id]
    sample = grp.head(n)
    return {
        "cluster_id": cluster_id,
        "cluster_size": int(len(grp)),
        "samples": sample[["ticket_id", "title", "category", "declared_team"]].to_dict(
            orient="records"
        ),
    }


if __name__ == "__main__":
    import json

    print("=== find_ticket_clusters(category='mantenimiento_operativo') ===")
    result = find_ticket_clusters(category="mantenimiento_operativo", min_cluster_size=10)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if result["clusters"]:
        biggest = max(
            (c for c in result["clusters"] if not c["is_noise"]),
            key=lambda c: c["size"],
            default=None,
        )
        if biggest:
            print(f"\n=== get_ticket_samples(cluster_id={biggest['cluster_id']}) ===")
            samples = get_ticket_samples(
                biggest["cluster_id"], n=8, category="mantenimiento_operativo", min_cluster_size=10
            )
            print(json.dumps(samples, indent=2, ensure_ascii=False, default=str))
