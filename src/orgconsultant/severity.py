"""
Capa 3 — Clasificación de severidad de cambio (determinista, NO delegada
al LLM).

Esta es lógica de negocio codificada a mano, no una llamada a modelo. El
LLM invoca esta función con los datos de un hallazgo ya confirmado con
evidencia cuantitativa (de flow_metrics / handoff_graph / clustering /
business_alignment) — nunca decide él mismo si algo es "táctico" o "macro".

Regla (tal como fue especificada):

    Un hallazgo escala a "macro" si cumple >=2 de 3 criterios:
    1. Alcance estructural: el hallazgo involucra >=2 equipos declarados
       distintos (silo detectado cruza equipos, o SPOF conecta >1 equipo,
       o aprobación es interdepartamental).
    2. Persistencia: el patrón aparece de forma estable en >=3 de los
       últimos 6 "meses" simulados del dataset (no es un pico puntual).
    3. Impacto en core de negocio: el hallazgo está asociado a tickets con
       criticidad estratégica "alto" o "medio", en volumen significativo
       (>15% de los tickets del hallazgo, umbral configurable).

    0-1 criterios -> "tactica"
    2-3 criterios -> {"estructural", "organizacional", "estrategico"}

Heurística de desempate (documentada aquí porque el enunciado la deja
abierta) cuando se cumplen exactamente 2 de 3 criterios — qué par de
criterios se cumple determina la etiqueta, siguiendo el orden de severidad
creciente táctico -> estructural -> organizacional -> estratégico que pide
el informe final:

    {alcance, persistencia}       (sin impacto de negocio probado)  -> "organizacional"
        Cruza equipos y es crónico, pero todavía no hay evidencia de que
        golpee el core de negocio: es un problema de diseño organizacional
        (cómo están cortados los equipos/procesos), no necesariamente una
        prioridad estratégica hoy.
    {alcance, impacto}            (sin persistencia probada)        -> "estructural"
        Cruza equipos y golpea valor de negocio, pero podría ser reciente/
        puntual: amerita rediseño de proceso/estructura, no necesariamente
        toda una reestructuración ni foco estratégico de largo plazo.
    {persistencia, impacto}       (sin alcance multi-equipo probado) -> "estrategico"
        Es crónico Y golpea el core de negocio, aunque estructuralmente
        parezca contenido en un solo equipo: merece atención estratégica
        de todas formas porque el costo acumulado y la relevancia de
        negocio ya están confirmados.
    los 3 criterios a la vez                                        -> "estrategico"
        Escalación máxima: alcance + cronicidad + impacto en negocio
        alineados es el caso que más justifica una reestructuración
        organizacional completa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TACTICA = "tactica"
ESTRUCTURAL = "estructural"
ORGANIZACIONAL = "organizacional"
ESTRATEGICO = "estrategico"

_PAIR_TO_SEVERITY = {
    frozenset({"alcance_estructural", "persistencia"}): ORGANIZACIONAL,
    frozenset({"alcance_estructural", "impacto_core"}): ESTRUCTURAL,
    frozenset({"persistencia", "impacto_core"}): ESTRATEGICO,
}

DEFAULT_STRATEGIC_VOLUME_THRESHOLD = 0.15
DEFAULT_PERSISTENCE_MONTHS_REQUIRED = 3
DEFAULT_PERSISTENCE_WINDOW_MONTHS = 6


@dataclass
class Finding:
    """Contrato de entrada para classify_change_severity.

    Se espera que el LLM orquestador construya este dict (o un objeto
    equivalente) a partir de los resultados YA CALCULADOS por las otras
    herramientas — nunca inventando estos números.
    """

    finding_id: str
    declared_teams_involved: list[str] = field(default_factory=list)
    is_interdepartmental_approval: bool = False
    months_present_last_6: int = 0  # 0-6, cuántos de los últimos 6 meses el patrón estuvo presente de forma estable
    pct_tickets_high_or_medium_strategic: float = 0.0  # 0.0-1.0
    strategic_volume_threshold: float = DEFAULT_STRATEGIC_VOLUME_THRESHOLD
    persistence_months_required: int = DEFAULT_PERSISTENCE_MONTHS_REQUIRED


def classify_change_severity(finding: dict | Finding) -> dict:
    """Aplica la regla de decisión de severidad. Determinista y testeable
    (ver tests/test_severity.py).
    """
    if isinstance(finding, dict):
        finding = Finding(**finding)

    n_teams = len(set(finding.declared_teams_involved))
    criterio_alcance = n_teams >= 2 or finding.is_interdepartmental_approval
    criterio_persistencia = (
        finding.months_present_last_6 >= finding.persistence_months_required
    )
    criterio_impacto = (
        finding.pct_tickets_high_or_medium_strategic >= finding.strategic_volume_threshold
    )

    criteria_met = {
        "alcance_estructural": criterio_alcance,
        "persistencia": criterio_persistencia,
        "impacto_core": criterio_impacto,
    }
    n_criteria = sum(criteria_met.values())

    if n_criteria <= 1:
        severity = TACTICA
        rationale = (
            f"Solo {n_criteria}/3 criterio(s) cumplido(s) "
            f"({[k for k, v in criteria_met.items() if v]}) -> táctico."
        )
    elif n_criteria == 3:
        severity = ESTRATEGICO
        rationale = "Los 3 criterios cumplidos -> escalación máxima (estratégico)."
    else:  # n_criteria == 2
        met_keys = frozenset(k for k, v in criteria_met.items() if v)
        severity = _PAIR_TO_SEVERITY[met_keys]
        rationale = f"Criterios cumplidos: {sorted(met_keys)} -> {severity} (ver heurística de desempate)."

    return {
        "finding_id": finding.finding_id,
        "criteria_met": criteria_met,
        "n_criteria_met": n_criteria,
        "severity": severity,
        "rationale": rationale,
        "inputs": {
            "n_declared_teams_involved": n_teams,
            "is_interdepartmental_approval": finding.is_interdepartmental_approval,
            "months_present_last_6": finding.months_present_last_6,
            "pct_tickets_high_or_medium_strategic": finding.pct_tickets_high_or_medium_strategic,
        },
    }


if __name__ == "__main__":
    import json

    ejemplos = [
        Finding("f-tactico", declared_teams_involved=["team_alpha"], months_present_last_6=1, pct_tickets_high_or_medium_strategic=0.05),
        Finding("f-estructural", declared_teams_involved=["team_alpha", "team_gamma"], months_present_last_6=1, pct_tickets_high_or_medium_strategic=0.30),
        Finding("f-organizacional", declared_teams_involved=["team_alpha", "team_growth"], months_present_last_6=5, pct_tickets_high_or_medium_strategic=0.05),
        Finding("f-estrategico-2crit", declared_teams_involved=["team_alpha"], months_present_last_6=6, pct_tickets_high_or_medium_strategic=0.40),
        Finding("f-estrategico-3crit", declared_teams_involved=["team_alpha", "team_beta", "team_gamma"], months_present_last_6=6, pct_tickets_high_or_medium_strategic=0.50),
    ]
    for f in ejemplos:
        print(json.dumps(classify_change_severity(f), indent=2, ensure_ascii=False))
