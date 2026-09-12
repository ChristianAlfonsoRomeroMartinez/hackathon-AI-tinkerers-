# Dataset sintético — Consultor de Reestructuración Organizacional

Generado por simulación (máquina de estados + distribuciones estadísticas), **no por LLM por ticket**.
6.000 tickets, ~37.000 eventos, ~9 meses de histórico simulado.

## Qué darle al agente (input legítimo)

| Archivo | Contenido |
|---|---|
| `event_log.csv` / `event_log.jsonl` | Event log canónico: `(ticket_id, ts, event_type, actor_hash, from_state, to_state, payload)`. Es la fuente de verdad para todas las métricas. |
| `tickets.csv` | Vista resumida por ticket (útil para debug/joins rápidos, no reemplaza el event log). |
| `org_chart_declared.json` | Organigrama **oficial** — equipos y su membresía declarada. Deliberadamente NO incluye la capa técnica real: eso el agente debe inferirlo del grafo de handoffs. |
| `business_taxonomy.json` | Las 6 categorías estratégicas (ancla externa para la Capa 2.5 — clasificación de valor de negocio). |

## Qué NO darle al agente

`ground_truth.json` — la clave de validación. Contiene los parámetros exactos de las 7 patologías plantadas y las métricas realmente logradas en esta corrida (para que tú, no el agente, verifiques qué tan bien las encontró).

## Las 7 patologías plantadas y su valor logrado en esta corrida

| # | Patología | Objetivo | Logrado |
|---|---|---|---|
| 1 | Héroe/SPOF (`actor_07`) | ~40% de handoffs críticos | 38.8% |
| 2 | Aprobación de seguridad inútil | cola ~6 días, rechazo ~2% | 463 tickets pasaron por el estado |
| 3 | Silo mal cortado (organigrama vs. capa técnica real) | — | estructural, se valida con Louvain sobre el grafo de handoffs |
| 4 | Deuda operativa invisible (causa raíz repetida) | 35% de `mantenimiento_operativo` | 31.6% |
| 5 | Ping-pong de triage | ~30% de `soporte_reactivo` con ≥4 reasignaciones | 30.6% |
| 6 | Desalineación estratégica silenciosa | team_alpha 55% bajo valor / team_growth 75% alto valor | 57.3% / 75.6% |
| 7 | Fragmentación end-to-end (onboarding cruza 4 equipos) | lead time ~3x vs. flujo normal | 4.9x (19.4h → 94.8h mediana) |

## Regenerar / ajustar parámetros

Todo el ground truth vive en `generator_source/config.py` (diccionario `PATHOLOGY_PARAMS`).
Para regenerar con otra semilla o volumen:

```bash
cd generator_source
python3 main.py
```

Requiere `numpy` y `pandas` (`pip install numpy pandas --break-system-packages`).

## Siguiente paso sugerido

Construir las herramientas del agente (`get_flow_metrics`, `get_handoff_graph`,
`find_ticket_clusters`, `classify_business_alignment`, `classify_change_severity`)
que consumen `event_log.csv` + `org_chart_declared.json` + `business_taxonomy.json`,
y correr el agente para ver cuántas de las 7 patologías encuentra por sí solo.
