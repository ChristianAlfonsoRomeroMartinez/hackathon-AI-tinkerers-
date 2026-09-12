# Consultor Organizacional Autónomo

Agente de IA que convierte datos operacionales pasivos (tickets tipo
Jira/Zendesk/ServiceNow) en diagnóstico estructural y propuestas de cambio
organizacional, con plan progresivo de implementación. Construido para un
hackathon de agentes.

**🔦 Demo en vivo (dashboard "Punto Ciego"):**
https://claude.ai/code/artifact/0dbec2b0-838b-4b11-a9a9-8faadf06c794

Dashboard con los hallazgos reales, la traza real del agente (reproducible
paso a paso) y las simulaciones económicas — todo generado por el pipeline
de este repo, no maquetado a mano. Código fuente del frontend en
`web/dashboard.html`.

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
  clustering.py             Capa 2 — clustering semántico de títulos (TF-IDF + SVD + HDBSCAN)
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
web/dashboard.html   frontend "Punto Ciego" — dashboard con hallazgos, traza del agente y simulaciones
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

Ver `PROGRESS.md` para el detalle fase por fase. Resumen: las 10 capas
(carga, flujo, grafo de handoffs, clustering, alineación de negocio,
severidad, bloques organizacionales, simulación, orquestación del agente,
frontend) están construidas, corridas de punta a punta contra el dataset
completo (6.000 tickets, 6.000/6.000 clasificados) y verificadas. El agente
corrió en vivo (`data/derived/agent_trace.jsonl`) y encontró, sin leer
`ground_truth.json`, evidencia cuantitativa para el héroe/SPOF, el cuello
de botella de aprobación y la desalineación estratégica — clasificados
todos como "estratégico" por la regla determinista de severidad, con
$5.64M/año de ahorro potencial simulado. El resto de las 7 patologías
plantadas (silo mal cortado, deuda operativa repetida, ping-pong de
triage, fragmentación end-to-end) están confirmadas con evidencia real
calculada directamente sobre las herramientas y presentadas en el
dashboard — ver `PROGRESS.md` para el detalle de qué se verificó cómo.
