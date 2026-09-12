# Progreso — Agente Consultor de Reestructuración Organizacional

> Este archivo existe para poder retomar el proyecto sin releer toda la
> conversación. Actualízalo al cerrar cada fase (o cuando el contexto/tokens
> se estén por agotar). La especificación completa original del usuario está
> en el primer mensaje de la conversación (prompt largo en español); no se
> duplica aquí, solo se resume lo operativo.

## Principio no negociable (no lo rompas al seguir)
Compute-first, LLM-last: el LLM nunca calcula métricas. Solo decide qué tool
invocar, interpreta números ya calculados por código determinista, y redacta.
La única excepción explícita es `classify_business_alignment` (Capa 2.5),
que SÍ usa LLM pero con structured output forzado (JSON schema) y cacheado
por ticket — nunca texto libre, nunca sin invocar la herramienta.

## Estado del entorno
- Repo git inicializado en `/home/christian/university/hackathon` (sin commits aún).
- Sin venv (no había `python3-venv` instalado y no se tiene sudo aquí).
  Dependencias instaladas **system-wide** con `pip3 install --break-system-packages`.
- Instalado hasta ahora: `duckdb`, `pandas` (3.0.5 — ojo, es pandas 3.x, no 2.x),
  `networkx`, `anthropic`, `python-louvain` (import como `community`).
- Pendiente instalar cuando se llegue a esas fases: `sentence-transformers`
  o similar + `hdbscan`/`scikit-learn` (Capa 2, clustering semántico).
- Python 3.13.5, `/usr/bin/python3`.

## Estructura del proyecto
```
hackathon/
  data/synth/                    # dataset sintético (ver su propio README.md)
    event_log.csv / .jsonl       # fuente de verdad, MUTADO (ver abajo)
    tickets.csv                  # vista resumida, MUTADO (ver abajo)
    org_chart_declared.json      # organigrama oficial (sin tocar)
    business_taxonomy.json       # 6 categorías de negocio (sin tocar)
    ground_truth.json            # NUNCA leído por código del agente ni por mí
    README.md                    # readme original del generador del dataset
    WIP_INJECTION_NOTES.md       # auditoría de la mutación de snapshot WIP (ver abajo)
  scripts/
    inject_wip_snapshot.py       # script de mutación del dataset (ya corrido, ver abajo)
  src/orgconsultant/
    __init__.py
    data_loader.py                # Capa 0 — carga event_log/tickets/org_chart/taxonomy
    flow_metrics.py                # Capa 1 — get_flow_metrics, get_state_queue_times
    (pendientes: handoff_graph.py, clustering.py, business_alignment.py,
     severity.py, org_blocks.py, simulation.py, agent.py, tools_schema.py, report.py)
  tests/                           # vacío todavía (pendiente Fase 6: tests de severidad)
  PROGRESS.md                      # este archivo
```

Todo el código se corre con `PYTHONPATH=src python3 -m orgconsultant.<modulo>`
desde la raíz del proyecto (cada módulo tiene un `if __name__ == "__main__"`
de auto-chequeo).

## ⚠️ Bug encontrado y corregido: corrupción de `payload_json` en la inyección WIP
Mientras se preparaba la Fase 4 (clustering, necesita `title` de los
tickets), se detectó que `find_ticket_clusters` no encontraba NINGÚN título
(`title` era `None` para los 6.000 tickets). Causa raíz: la primera versión
de `scripts/inject_wip_snapshot.py` reconstruía `payload_json` con una
función `row_to_payload` que leía columnas aplanadas (`category`,
`declared_team`, `title`, etc.) que **no existen** en el DataFrame crudo
cargado directamente del CSV (`pd.read_csv` sin parsear payload) — por lo
tanto esa función devolvía `{}` para cada fila, y al reescribir
`event_log.csv` completo, **vació el payload de las 36.800 filas**, no solo
de los tickets truncados.

**Ya corregido**: se restauró el backup pristino (scratchpad de esta
sesión) y se reescribió esa sección del script para reusar directamente la
columna `payload_json` original de `events` (que sí venía intacta desde el
CSV, el bug estaba solo en cómo se RE-escribía, no en cómo se leía) — el
truncamiento ahora solo borra filas completas, nunca reconstruye contenido.
Se re-corrió el script y se verificó:
- 6.000/6.000 eventos `created` con `title` no vacío, 0 payloads vacíos.
- `validate_dataset()`, `get_flow_metrics()` y `get_handoff_graph()` dan
  EXACTAMENTE los mismos números que antes del fix (esas funciones nunca
  leen `title`/payload, así que el bug nunca las afectó — coincide con que
  ya se habían confirmado con el usuario antes de encontrar el bug, y las
  cifras confirmadas siguen siendo válidas, no hace falta re-confirmarlas).
- `clustering.py` NO se había ejecutado todavía cuando se encontró el bug
  (se descubrió precisamente al chequear cardinalidad de títulos antes de
  correrlo) — por eso no hizo falta invalidar ningún resultado ya mostrado
  al usuario.

Lección para el futuro de este proyecto: si se vuelve a tocar
`inject_wip_snapshot.py`, JAMÁS reconstruir `payload_json` desde columnas
aplanadas de un DataFrame que no las tiene — reusar la columna cruda
original y solo tocar (borrar filas de) lo estrictamente necesario.

## Decisión importante tomada en esta sesión: mutación del dataset (WIP snapshot)
El dataset original generado resuelve el 100% de los 6.000 tickets (no hay
WIP real). El usuario pidió explícitamente dejarlo "en el estado más real
posible" e "inventar datos" para demostrar funcionalidad (que `wip_aging_hours`
no sea `null`).

Se ejecutó `scripts/inject_wip_snapshot.py` (semilla determinista `20260912`,
**ya corrido una vez, es idempotente-guardado**: si se vuelve a correr sobre
un dataset que ya tiene WIP, aborta con error a propósito). Qué hizo:
- Truncó el historial real (no inventó transiciones) de **45 de 6.000 tickets
  (0.75%)** en un estado que realmente visitaron, descartando sus eventos
  posteriores (incluida la resolución eventual).
- Distribución objetivo calibrada con Ley de Little sobre las medias de
  `get_state_queue_times()`: 15 en Pending Approval Security, 14 en In
  Progress, 5 Backlog, 5 Triage, 3 In Review, 2 Waiting Handoff, 1 Reopened.
- 2 casos de "abandono" deliberadamente antiguos en Pending Approval Security
  (creados hace meses, congelados igual) para evidencia narrativa fuerte —
  ej. `TCK-02869`, ~272 días de antigüedad, sigue "abierto" ahí mismo.
- Detalle completo, ticket por ticket, en `data/synth/WIP_INJECTION_NOTES.md`.
- **Archivos sobrescritos in-place**: `data/synth/event_log.csv`, `.jsonl`,
  `tickets.csv`. Hay backup de los originales (100% resueltos, pre-mutación)
  en el scratchpad de esta sesión — **no persistente entre sesiones**, así
  que si hace falta revertir y esta sesión ya no está, hay que volver a pedir
  el dataset original o regenerar con `generator_source/` (si existe — no
  se encontró en este checkout; solo estaban los 5 archivos + jsonl + README).
- Impacto verificado como marginal sobre los históricos: Pending Approval
  Security sigue siendo el outlier clarísimo (n=447 vs 463 original, p50/p90
  casi idénticos). Esto SÍ debe declararse en el Anexo Metodológico del
  informe final (Fase 9): "N tickets fueron congelados sintéticamente para
  poblar un snapshot de WIP en vivo; ver WIP_INJECTION_NOTES.md".

## Fases completadas (con checkpoint del usuario)

### Fase 1 — Carga de datos ✅ confirmada
`src/orgconsultant/data_loader.py`. `validate_dataset()` comprueba:
6.000 tickets, ~37K eventos (36.800 tras la mutación WIP), ticket_ids
event log == tickets.csv, estados válidos. Corre con
`PYTHONPATH=src python3 -m orgconsultant.data_loader`.

Nota de schema real (difiere levemente de la especificación del prompt):
la columna del CSV es `payload_json` (string JSON), no `payload` (dict) —
`data_loader.py` la parsea y expone como `payload` (dict) + columnas
aplanadas `category`/`declared_team`/`title`/`leg_team`/`leg_index`/
`root_cause_template_id` propagadas (ffill/bfill) a todos los eventos del
mismo ticket (el evento `created` es el único que trae `category`/
`declared_team`/`title` en el payload original).

### Fase 2 — Métricas de flujo ✅ confirmada
`src/orgconsultant/flow_metrics.py`: `get_flow_metrics()`,
`get_state_queue_times()`. Confirmado sin ground_truth: **Pending Approval
Security es outlier clarísimo** — p50 180h (~7.5 días), p90 345h (~14.4
días), **13x** el siguiente estado más lento (In Progress, p90 26h). 447
tickets pasaron por ahí. Coincide con la patología 2 del dataset (aprobación
inútil).

También implementado (post-mutación WIP): `wip_by_current_state` en
`get_flow_metrics()` — desglose de los 45 WIP por estado actual, con aging
p50/max y el ticket más viejo de cada uno. 15 de los 45 WIP están AHORA
MISMO en Pending Approval Security — refuerza la narrativa del cuello de
botella con evidencia "en vivo", no solo histórica.

Limitación documentada en el docstring del módulo: no se puede medir
"touch time" real (no hay eventos de inicio/fin de trabajo dentro de un
estado), solo queue time (tiempo total en el estado). Está declarado así,
no se inventó touch time.

## Credenciales de API (estado actual)
- **OpenAI**: key guardada en `.env` (`OPENAI_API_KEY`, gitignored) pero
  **sin créditos** (`insufficient_quota`/`credit_balance_exhausted` al
  probarla) — NO USAR para embeddings hasta que el usuario cargue saldo.
- **Exa.ai**: key que dio el usuario, mala elección para esto — Exa es un
  motor de búsqueda/retrieval web (search/contents/find-similar/answer),
  **no tiene endpoint de embeddings genérico** para texto arbitrario.
  Confirmado vía docs oficiales. No usar para clustering.
- **Decisión tomada**: usar `sentence-transformers` LOCAL
  (`all-MiniLM-L6-v2`), gratis, offline, sin depender de ninguna key.
  Instalación de `sentence-transformers` (arrastra `torch`, pesado, tardó
  varios minutos) — revisar si ya terminó con
  `python3 -c "import sentence_transformers"` antes de correr
  `orgconsultant.clustering`.
- **Anthropic**: NO hay `ANTHROPIC_API_KEY` en el entorno ni credenciales
  locales encontradas. Hará falta pedírsela al usuario antes de la Fase 5
  (`classify_business_alignment`, única parte con LLM real) y la Fase 8
  (orquestación del agente vía tool use). Cuando la pida, mismo tratamiento
  que las otras keys: guardar en `.env` (gitignored), nunca imprimirla,
  nunca commitearla.

## Fase 3 — Grafo de handoffs ✅ confirmada
`src/orgconsultant/handoff_graph.py`: `get_handoff_graph(min_weight=1)`.
Grafo dirigido pesado actor_hash->actor_hash desde TODOS los eventos
(created+transition+reassignment) ordenados por ts dentro de cada ticket;
un handoff = cambio de actor entre dos eventos consecutivos del mismo
ticket. Solo devuelve datos crudos (nodes con betweenness/comunidad, edges,
communities, modularity) — el contraste comunidad-vs-declared_team lo hace
el LLM orquestador, no la herramienta (a propósito).

Confirmado sin ground_truth:
- **SPOF**: `ad55053f31d6` (rol declarado `senior_engineer_bottleneck`,
  team_alpha) betweenness ponderada 0.457, 3.2x el siguiente actor
  (`189d4e84a2cc`, security_approver, team_alpha, 0.141). Nota técnica
  importante: la betweenness NO ponderada da 0 para TODOS los nodos porque
  el grafo es casi completo (462/462 aristas posibles con 22 actores) — hay
  que usar la versión ponderada por distancia=1/peso, ya implementada y
  documentada en el docstring del módulo.
- **Silo mal cortado**: 4 equipos declarados colapsan en solo 2 comunidades
  Louvain reales, cortando transversalmente los equipos oficiales (equipo
  alpha se reparte entre ambas comunidades). Modularidad muy baja (0.079,
  robusta a filtrar con min_weight 1/3/5) — la red de colaboración real casi
  no tiene fronteras naturales, el organigrama declarado no refleja cómo se
  trabaja de verdad.

22 actores en total, los 22 están en `org_chart_declared.json` (sin actores
"fantasma" fuera del organigrama oficial).

## Fase 6 — `classify_change_severity` ✅ construida y testeada (adelantada)
`src/orgconsultant/severity.py` + `tests/test_severity.py` (17/17 tests
pasan, correr con `python3 -m pytest tests/test_severity.py -v`). Implementa
la regla de >=2 de 3 criterios (alcance estructural / persistencia /
impacto en core) tal cual la especificación, con una heurística de
desempate DOCUMENTADA en el docstring del módulo para el caso de exactamente
2/3 criterios cumplidos (qué par de criterios da qué severidad — ver ahí el
razonamiento completo, no repetido aquí). Acepta dict o dataclass `Finding`.
Se adelantó esta fase mientras se esperaba la instalación de
sentence-transformers en background, porque es lógica pura sin
dependencias externas.

## Fase 7 (parcial) — `simulate_change` / `simulate_horizon_cascade` ✅ + `propose_org_blocks` ✅
`src/orgconsultant/simulation.py`: Ley de Little analítica, sin SimPy (no
hizo falta modelar colas con recursos limitados para los cambios que pide
este dataset). Recalcula lead time TICKET POR TICKET restando la cola real
que cada ticket específico pasó en el estado afectado (no escala el
promedio a mano) — permite recomputar p50/p90 reales del escenario, no solo
la media. Ya probado: eliminar "Pending Approval Security" completo baja el
lead time p50 de 21.4h a 19.8h y p90 de 102.8h a 75.7h, con
~$5.64M/año de "costo de demora" ahorrado (447 tickets afectados, ~210h
promedio cada uno, costo/hora default $45 USD — CONFIGURABLE, declarado
explícitamente). `simulate_horizon_cascade` encadena horizontes reduciendo
progresivamente el mismo estado (30%->50% de lo restante->100%), cada
horizonte parte de los tickets ya ajustados del anterior.

**Nota metodológica importante ya documentada en el código**: el "impacto
económico" es horas-en-cola × costo/hora (proxy de "costo de demora"/cost of
delay), NO nómina literal — nadie trabaja mientras un ticket espera en cola.
Debe aclararse así en el Anexo Metodológico del informe final (Fase 9) para
no sobre-interpretar la cifra.

`src/orgconsultant/org_blocks.py`: `propose_org_blocks(min_weight=1)` sobre
las 2 comunidades Louvain ya detectadas. Con este dataset, el
`role_suggestion` (ej. "Automation Engineer") da `null` en ambos bloques
actuales — la razón queda documentada: el grafo de handoffs es casi
completo/denso, así que las comunidades Louvain son demasiado anchas (10-12
actores tocando casi todas las categorías) y diluyen la concentración de
`is_hidden_operational_debt` por debajo del umbral (25%). La señal fina de
la patología 4 (deuda operativa repetida en mantenimiento_operativo) va a
salir de `find_ticket_clusters` (Fase 4, pendiente), no de esta función — el
LLM orquestador deberá CRUZAR el cluster dominante de Fase 4 con quién lo
atiende para argumentar el rol dedicado, no esperar que `propose_org_blocks`
lo resuelva solo. Dejar esto claro en el system prompt del agente si hace
falta (Fase 8).

## Credenciales de API — ACTUALIZACIÓN: ya hay LLM real funcionando
El usuario consiguió una **API key de Ollama Cloud** (`OLLAMA_API_KEY` en
`.env`, gitignored) que SÍ funciona como LLM real con tool-use y salida
estructurada — probado con curl antes de construir nada encima. Modelo:
`gpt-oss:120b`. Esto reemplaza el plan original de usar Anthropic/OpenAI
para las Fases 5 y 8 — no hace falta seguir pidiendo esas keys.

También hay una **API key de Exa.ai** (`EXA_API_KEY` en `.env`) — Exa NO
sirve como LLM ni como proveedor de embeddings (confirmado, ver más abajo),
pero SÍ sirve para lo que realmente es: búsqueda web. Se usa como
herramienta OPCIONAL/aditiva (`search_best_practices` en
`web_research.py`) para citar 2-3 referencias externas de industria que
respalden una recomendación puntual del informe — nunca para calcular
ninguna cifra del diagnóstico.

**Nota de nombre del agente** (pedido explícito del usuario): el agente se
llama **"Consultor Organizacional Autónomo"** (`AGENT_NAME` en `agent.py`),
ya reflejado en el system prompt. Usar ese nombre también en el informe
final (Fase 9) y en cualquier material de cara al usuario.

## Fase 5 — `classify_business_alignment` ✅ construida, clasificación completa EN CURSO
`src/orgconsultant/llm_client.py`: cliente compartido para Ollama Cloud
(`https://ollama.com/api/chat`), con reintentos+backoff exponencial (Ollama
Cloud tier gratuito corta la conexión ocasionalmente bajo carga sostenida —
visto en producción). Usado en EXACTAMENTE 2 lugares: business_alignment.py
y agent.py — ningún otro módulo debe importarlo.

`src/orgconsultant/business_alignment.py`: doble eje por ticket —
(a) `effort_type` [valor_directo/deuda_operativa/deuda_tecnica/
friccion_proceso] SÍ requiere LLM (única parte semántica real del
proyecto), en batch de 40 tickets por llamada, salida JSON forzada.
(b) `strategic_value` es un lookup DETERMINISTA directo de
`business_taxonomy.json` por categoría — la propia especificación dice
"según la taxonomía", no hace falta LLM para esto (ahorra ~6000 llamadas).
Cachea en `data/derived/business_alignment_cache.json` (gitignored-worthy
pero no lo agregué a .gitignore todavía — es reproducible, no secreto,
revisar si conviene versionarlo o no antes de un commit).

**Bug importante encontrado y corregido en `_extract_classifications`**:
gpt-oss:120b vía Ollama Cloud respeta el CONTENIDO del schema (id +
effort_type) pero NO consistentemente la forma del envoltorio — se
observaron 4 formas distintas para el mismo prompt/schema en llamadas
distintas: `{"classifications":[...]}`, `{"tickets":[...]}`, lista suelta
`[...]`, y mapa plano `{ticket_id: effort_type, ...}`. La función normaliza
las 4 formas. Si se cambia el prompt/schema y vuelve a fallar con
`n_tickets_classified=0` sin excepción, empezar a debuggear por aquí.

**Validación manual (paso 5 del plan)**: hecha sobre 40 tickets, ejemplos
razonables — "Refactor urgente kyc-gateway" (deuda_tecnica_critica) ->
`deuda_tecnica` ✓, "Actualizar política SARLAFT" (cumplimiento_regulatorio)
-> `valor_directo` ✓, "Servicio caído — reinicio manual" (mantenimiento_
operativo) -> `deuda_operativa` ✓. Aprobada, se procedió a correr sobre
todo el dataset.

**Clasificación completa (6000 tickets, 150 batches) — EN CURSO EN
BACKGROUND al cortarse el contexto.** Historial de intentos (para no
repetir errores):
1. Intento 1 (`nohup ... &` DENTRO de un Bash run_in_background): el
   proceso real murió huérfano casi de inmediato porque el backgrounding
   se duplicó — el tool ya trackea background por sí solo, nunca envolver
   el comando en su propio `&`/`nohup` otra vez. Quedaron 120 cacheados.
2. Intento 2 (comando plano, sin nohup, con run_in_background:true — la
   forma CORRECTA): avanzó a 280, luego a 760+ (última cifra vista antes
   de cortar contexto), corriendo esta vez CON reintentos+backoff ya
   implementados. **Revisar si ya terminó** con:
   ```
   python3 -c "import json; print(len(json.load(open('data/derived/business_alignment_cache.json'))))"
   ```
   Si da 6000 (o cerca, menos algunos `failed_batches` reportados en el
   log de esa tarea en background), está listo — solo falta invocar
   `classify_business_alignment()` una vez más (sin `max_new_calls`, o con
   0 si ya está completo) para obtener el agregado final y seguir a Fase 9.
   Si quedó a medias, simplemente volver a correr
   `classify_business_alignment(max_new_calls=None)` — el caché es
   incremental, retoma donde quedó, es idempotente.

## Fase 8 — Orquestación del agente ✅ código completo, PENDIENTE de correr end-to-end
`src/orgconsultant/tools_schema.py`: las 11 herramientas registradas
(las 10 de las capas 1-4 + `search_best_practices` de Exa, opcional/aditiva
— nunca aporta cifras del diagnóstico, solo referencias externas citables).
`classify_business_alignment` como tool le quita `per_ticket` antes de
devolvérselo al LLM (6000 filas no caben en el contexto razonable) — el
informe final debe llamar la función Python directamente, no a través del
tool-dispatch, para tener el detalle completo.

`src/orgconsultant/agent.py`: `run_agent(max_turns=25)` — loop de tool-use
real contra Ollama Cloud, logueando CADA invocación a
`data/derived/agent_trace.jsonl` (se borra al iniciar cada corrida — no
acumula corridas viejas). System prompt = protocolo de investigación por
hipótesis de la especificación original, adaptado con `AGENT_NAME`.

**Todavía NO se ha corrido `run_agent()` de punta a punta** — depende de
que: (a) termine la clasificación de negocio (arriba), (b) termine de
instalar `sentence-transformers` para que `find_ticket_clusters` funcione
cuando el agente lo invoque (si el agente lo llama antes de que esté listo,
`call_tool` atrapa la excepción y se la devuelve como `{"error": ...}` al
LLM — no debería tumbar el loop, pero mejor esperar a que esté instalado
para una demo limpia).

Verificar antes de correr `python3 -m orgconsultant.agent`:
```
python3 -c "import sentence_transformers"  # no debe fallar
python3 -c "import json; d=json.load(open('data/derived/business_alignment_cache.json')); print(len(d))"  # debería ser 6000 o cerca
```

## ⚠️ Cambio de plan: sentence-transformers descartado, reemplazado por TF-IDF+SVD
La instalación de `sentence-transformers` (arrastra `torch`) se estancó
más de 1 hora sin completar (conexión lenta, 716MB descargados sin avanzar
más) — se mató el proceso y se reescribió `clustering.py` para usar
TF-IDF (word 1-2grams) + TruncatedSVD(50 componentes, random_state=42) +
HDBSCAN, todo con scikit-learn (ya instalado, sin dependencias pesadas).
Esto es ADEMÁS un mejor ajuste para este dataset (títulos con plantillas
casi-idénticas, la similitud léxica los agrupa perfectamente). Ya NO hace
falta sentence-transformers en absoluto — no reintentar esa instalación.

## Fase 4 — `find_ticket_clusters` + `get_ticket_samples` ✅ CONFIRMADA
Resultado sobre `category='mantenimiento_operativo'` (1.470 tickets):
- **0% ruido, exactamente 30 clusters = 30 títulos únicos** — el 100% de
  los tickets de esta categoría son repeticiones TEXTUALES EXACTAS de solo
  30 plantillas de incidente (combinación de servicio × tipo de incidente:
  "caído/reinicio manual", "alerta de memoria", "job nocturno falló",
  "limpieza de logs", "reinicio tras timeout", sobre payments-api/
  ledger-core/kyc-gateway/auth-service/billing-service/notif-service).
  Ningún ticket de mantenimiento_operativo es un problema genuinamente
  nuevo — 100% recurrente.
- Cruzando con el flag YA EXISTENTE en tickets.csv
  `is_hidden_operational_debt` (465/1470 = 31.6% del total, coincide con
  el ~35% objetivo del generador): el porcentaje de deuda oculta está
  DISTRIBUIDO PAREJO entre las 30 plantillas (32%-43% cada una, sin una
  plantilla claramente dominante) — el hallazgo correcto NO es "una causa
  raíz específica está oculta", es "aprox. un tercio de CUALQUIER
  incidente recurrente de mantenimiento, sin importar cuál, es en
  realidad síntoma de una causa raíz nunca resuelta" — un problema
  sistémico de falta de post-mortems/fixes permanentes, no un bug puntual.
  Esto es MÁS fuerte como hallazgo estructural que "un cluster dominante".

## Siguiente paso pendiente de confirmación del usuario
**Fase 4 — `find_ticket_clusters` + `get_ticket_samples`**: módulo ya
escrito en `src/orgconsultant/clustering.py`, pendiente de EJECUTAR porque
sentence-transformers se estaba instalando en background al cortarse el
contexto. Antes de continuar:
1. Verificar instalación: `python3 -c "import sentence_transformers"` (si
   falla, reinstalar: `pip3 install --break-system-packages -q
   sentence-transformers`, tarda varios minutos por torch).
2. Correr `PYTHONPATH=src python3 -m orgconsultant.clustering` y confirmar
   que aísla un cluster dominante en `mantenimiento_operativo` (esto es el
   checkpoint que pidió el usuario para esta fase, todavía no verificado).
3. Mostrar al usuario el resultado y esperar su confirmación antes de Fase 5.

## Fases pendientes (resumen, ver prompt original del usuario para detalle completo)
4. `find_ticket_clusters` + `get_ticket_samples` — código listo, falta
   ejecutar y confirmar (ver arriba) — SIGUIENTE
5. `classify_business_alignment` (Capa 2.5, ÚNICA parte con LLM en batch,
   structured output forzado, cacheado por ticket) — necesita
   `ANTHROPIC_API_KEY`, pedírsela al usuario
8. Orquestación del agente con Anthropic API (tool use real, iterativo,
   con traza de invocaciones logueada — este es el "demo" central) —
   necesita la misma `ANTHROPIC_API_KEY`
9. Informe final (Markdown/HTML) con las 6 secciones especificadas
   (resumen ejecutivo, matriz esfuerzo/valor, hallazgos por severidad,
   organigrama actual vs propuesto, plan de horizontes, anexo metodológico
   — debe mencionar: mutación WIP de esta sesión, y la nota de "costo de
   demora" de la Fase 7)
10. Validación manual del usuario contra `ground_truth.json` — NO la hago yo.

(Fases 6 y 7 ya completadas fuera de orden mientras se esperaba una
instalación — ver arriba. Faltan solo 4, 5, 8, 9, 10.)

## Recordatorios de alcance (qué NO construir, del prompt original)
Sin conectores reales Jira/Zendesk, sin anonimización real de PII, sin RACI
completo para todos los horizontes (solo el del horizonte de rediseño de
equipos), sin RAG, sin UI pulida (HTML simple o Streamlit básico basta).
