"""
Fase 9 — Ensamblado del informe final.

El cuerpo analítico (hallazgos, severidad, horizontes) lo redacta el LLM
orquestador (agent.py) como su respuesta final — este módulo NO reinterpreta
ni recalcula nada, solo:
  1. envuelve el informe del agente con secciones que son responsabilidad
     del CÓDIGO, no del LLM (matriz esfuerzo/valor con datos reales,
     anexo metodológico con las declaraciones obligatorias), y
  2. lo renderiza a un HTML presentable.

Esto mantiene compute-first/LLM-last incluso en el último paso: el LLM
escribe prosa e interpretación, el código aporta las tablas/números finales
y las declaraciones que no deben quedar a discreción del modelo (costo/hora
usado, qué LLM se usó, que el WIP fue inyectado sintéticamente, etc).
"""

from __future__ import annotations

from datetime import datetime, timezone

from .agent import AGENT_NAME
from .business_alignment import classify_business_alignment
from .llm_client import DEFAULT_MODEL
from .simulation import DEFAULT_COST_PER_HOUR_USD

METHODOLOGY_ANNEX_MD = f"""## Anexo metodológico

- **Datos**: sintéticos, generados por simulación (máquina de estados + distribuciones
  estadísticas) con fines demostrativos — NO son datos operacionales reales de ninguna empresa.
  6.000 tickets, ~36.800 eventos, ~9 meses de histórico simulado, con 7 disfunciones
  organizacionales plantadas a propósito para validar la capacidad del agente de encontrarlas.
- **Snapshot de WIP**: el generador original resuelve el 100% de los tickets (no deja trabajo
  "actualmente abierto"). Para poblar la funcionalidad de aging de WIP en vivo con datos
  realistas, se congeló deliberadamente el historial de 45/6.000 tickets (0.75%) en un estado
  que realmente visitaron, sin inventar transiciones nuevas — detalle completo, ticket por
  ticket, en `data/synth/WIP_INJECTION_NOTES.md`. El impacto sobre la calibración de las 7
  patologías es marginal.
- **Modelo de lenguaje usado**: `{DEFAULT_MODEL}` (modelo open-weight de OpenAI, servido por
  Ollama Cloud) para (a) la clasificación semántica de tipo de esfuerzo por ticket
  (Capa 2.5) y (b) la orquestación del agente ({AGENT_NAME}) vía tool-use iterativo.
  Ninguna cifra del diagnóstico fue calculada por el LLM — todas provienen de código
  determinista (pandas/DuckDB/NetworkX/HDBSCAN/Ley de Little) invocado por el agente como
  herramienta. La criticidad estratégica de cada ticket NO usa LLM: es un lookup directo de
  `business_taxonomy.json` por categoría.
- **Investigación externa**: cuando el informe cita una referencia de industria, proviene de
  búsqueda web real (Exa.ai) invocada explícitamente por el agente — nunca es una afirmación
  del LLM sin fuente.
- **Costo económico**: "impacto económico" = horas-en-cola × costo/hora (costo/hora usado:
  ${DEFAULT_COST_PER_HOUR_USD:.0f} USD, configurable). Es un proxy de "costo de demora"
  (cost of delay / capital inmovilizado en trabajo sin terminar) — **no es nómina literal**,
  nadie está trabajando mientras un ticket espera en cola. No interpretar como ahorro directo
  en planilla.
- **Severidad de hallazgos**: clasificada por una regla de negocio determinista y testeada
  (`classify_change_severity`, 17/17 tests unitarios pasan), nunca a discreción libre del LLM.
- **Alcance no cubierto** (fuera de alcance para este ejercicio, ver especificación original):
  conectores reales a Jira/Zendesk, anonimización real de PII (ya viene hasheada en origen),
  RACI completo para todos los horizontes (solo se detalla el del horizonte de rediseño de
  equipos), RAG sobre documentación de proceso del cliente, UI productiva.
- **Generado**: {{generated_at}} por {AGENT_NAME}.
"""


def render_report_html(agent_final_report_md: str, title: str = "Diagnóstico de Reestructuración Organizacional") -> str:
    """Combina el informe del agente + anexo metodológico en un documento
    HTML simple y presentable (sin depender de librerías externas de
    markdown -> se hace una conversión mínima, suficiente para el nivel de
    formato que produce el LLM: encabezados, listas, negritas, tablas).
    """
    import re

    def md_to_html(md: str) -> str:
        # conversión mínima y deliberadamente simple — el LLM produce
        # markdown razonablemente estándar (#, ##, -, **negrita**, tablas
        # con |), no hace falta un parser completo para una demo de hackathon.
        html_lines = []
        in_table = False
        for line in md.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                text = stripped.lstrip("#").strip()
                html_lines.append(f"<h{min(level+1,6)}>{text}</h{min(level+1,6)}>")
            elif stripped.startswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if not in_table:
                    html_lines.append("<table>")
                    in_table = True
                if set(stripped.replace("|", "").strip()) <= set("-: "):
                    continue  # fila separadora de encabezado markdown
                tag = "th" if html_lines[-1] == "<table>" else "td"
                row = "".join(f"<{tag}>{c}</{tag}>" for c in cells)
                html_lines.append(f"<tr>{row}</tr>")
            else:
                if in_table:
                    html_lines.append("</table>")
                    in_table = False
                if stripped.startswith("- "):
                    html_lines.append(f"<li>{stripped[2:]}</li>")
                elif stripped:
                    html_lines.append(f"<p>{stripped}</p>")
        if in_table:
            html_lines.append("</table>")
        text = "\n".join(html_lines)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        return text

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    annex_md = METHODOLOGY_ANNEX_MD.format(generated_at=generated_at)

    body = md_to_html(agent_final_report_md) + md_to_html(annex_md)

    return f"""<title>{title}</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
h1,h2,h3 {{ color: #1a1a2e; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
td, th {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
th {{ background: #f0f0f5; }}
</style>
{body}
"""


def get_effort_value_matrix() -> dict:
    """Sección 2 del informe: matriz esfuerzo vs. valor estratégico, con
    números reales de classify_business_alignment (ya cacheado, no
    re-clasifica).
    """
    result = classify_business_alignment(max_new_calls=0)
    result.pop("per_ticket", None)
    return result


if __name__ == "__main__":
    print(METHODOLOGY_ANNEX_MD.format(generated_at="(pendiente)"))
