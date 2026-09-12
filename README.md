# Consultor Organizacional Autónomo

Agente de IA que convierte datos operacionales pasivos (tickets tipo
Jira/Zendesk/ServiceNow) en diagnóstico estructural y propuestas de cambio
organizacional, con plan progresivo de implementación. Construido para un
hackathon de agentes.

Ver `PROGRESS.md` para el estado detallado de construcción (fase por fase,
decisiones tomadas, bugs encontrados/corregidos) — este README es solo la
vista de "cómo correrlo".

## Principio arquitectónico: compute-first, LLM-last

El LLM nunca calcula métricas. Todo número (tiempos de cola, lead time,
centralidad de grafo, clusters, Ley de Little) lo calcula código
determinista (pandas/DuckDB/NetworkX/HDBSCAN). El LLM solo:
1. decide qué herramienta invocar y con qué filtros (orquestación por hipótesis),
2. clasifica semánticamente el tipo de esfuerzo de cada ticket (única parte
   que requiere juicio de lenguaje real, en batch con salida JSON forzada),
3. interpreta los números ya calculados y redacta el informe final citando
   evidencia concreta (ticket_ids, cifras exactas).

## Estructura

```
data/synth/       dataset sintético (event log, tickets, organigrama, taxonomía)
data/derived/     cachés generados por el pipeline (clasificación LLM, traza del agente)
src/orgconsultant/
  data_loader.py        Capa 0 — carga event log + tickets + organigrama + taxonomía
  flow_metrics.py        Capa 1 — lead time, tasas, tiempos de cola por estado
  handoff_graph.py        Capa 1/2 — grafo de handoffs, betweenness, comunidades Louvain
  clustering.py             Capa 2 — clustering semántico de títulos (embeddings + HDBSCAN)
  business_alignment.py     Capa 2.5 — tipo de esfuerzo (LLM) + criticidad estratégica (taxonomía)
  severity.py                Capa 3 — clasificación determinista de severidad de hallazgos
  org_blocks.py                Capa 3 — bloques organizacionales propuestos
  simulation.py                  Capa 4 — simulación what-if (Ley de Little)
  llm_client.py                   cliente Ollama Cloud (único punto de acceso al LLM)
  web_research.py                  búsqueda externa opcional (Exa.ai) para citar referencias
  tools_schema.py                   registro de herramientas del agente (JSON schema + dispatch)
  agent.py                           orquestación: loop de tool-use real, protocolo por hipótesis
  report.py                           ensamblado del informe final (HTML)
tests/test_severity.py   tests unitarios de la regla de severidad (17 casos)
scripts/inject_wip_snapshot.py   inyección de snapshot de WIP realista (ya corrido)
```

## Cómo correr

Requiere las keys en `.env` (gitignored): `OLLAMA_API_KEY` (LLM real, vía
Ollama Cloud) y opcionalmente `EXA_API_KEY` (búsqueda web para citar
referencias externas — aditivo, el diagnóstico funciona sin ella).

```bash
# validar el dataset
PYTHONPATH=src python3 -m orgconsultant.data_loader

# correr cualquier capa de forma aislada (todas tienen un __main__ de auto-chequeo)
PYTHONPATH=src python3 -m orgconsultant.flow_metrics
PYTHONPATH=src python3 -m orgconsultant.handoff_graph
PYTHONPATH=src python3 -m orgconsultant.clustering
PYTHONPATH=src python3 -m orgconsultant.simulation

# clasificación de negocio (cachea incrementalmente — seguro de re-correr)
PYTHONPATH=src python3 -m orgconsultant.business_alignment

# tests de la regla de severidad
python3 -m pytest tests/test_severity.py -v

# correr el agente completo (requiere OLLAMA_API_KEY)
PYTHONPATH=src python3 -m orgconsultant.agent
```

## Estado actual

Ver `PROGRESS.md` — al momento de este commit, capas 1-7 construidas y
verificadas, Fase 5 (clasificación de negocio) corriendo sobre el dataset
completo, Fase 8 (agente) construida y pendiente de una corrida end-to-end
completa, Fase 9 (informe final) con el anexo metodológico listo.
