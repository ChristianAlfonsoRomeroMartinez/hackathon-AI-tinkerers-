"""Tests unitarios de classify_change_severity — un caso sintético simple
por nivel de severidad, más los bordes de la regla de decisión.

Correr con: PYTHONPATH=src python3 -m pytest tests/test_severity.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orgconsultant.severity import (  # noqa: E402
    ESTRATEGICO,
    ESTRUCTURAL,
    ORGANIZACIONAL,
    TACTICA,
    Finding,
    classify_change_severity,
)


def _sev(**kwargs) -> str:
    f = Finding(finding_id=kwargs.pop("finding_id", "f-test"), **kwargs)
    return classify_change_severity(f)["severity"]


class TestNivelTactico:
    def test_cero_criterios(self):
        assert _sev(declared_teams_involved=["team_alpha"], months_present_last_6=0,
                    pct_tickets_high_or_medium_strategic=0.0) == TACTICA

    def test_un_solo_criterio_alcance(self):
        assert _sev(declared_teams_involved=["team_alpha", "team_beta"],
                    months_present_last_6=0, pct_tickets_high_or_medium_strategic=0.0) == TACTICA

    def test_un_solo_criterio_persistencia(self):
        assert _sev(declared_teams_involved=["team_alpha"],
                    months_present_last_6=6, pct_tickets_high_or_medium_strategic=0.0) == TACTICA

    def test_un_solo_criterio_impacto(self):
        assert _sev(declared_teams_involved=["team_alpha"],
                    months_present_last_6=0, pct_tickets_high_or_medium_strategic=0.9) == TACTICA


class TestNivelEstructural:
    def test_alcance_mas_impacto_sin_persistencia(self):
        assert _sev(declared_teams_involved=["team_alpha", "team_gamma"],
                    months_present_last_6=1,
                    pct_tickets_high_or_medium_strategic=0.30) == ESTRUCTURAL

    def test_spof_interdepartamental_cuenta_como_alcance(self):
        # is_interdepartmental_approval satisface el criterio de alcance
        # aunque declared_teams_involved solo liste un equipo "dueño".
        assert _sev(declared_teams_involved=["team_alpha"],
                    is_interdepartmental_approval=True,
                    months_present_last_6=0,
                    pct_tickets_high_or_medium_strategic=0.25) == ESTRUCTURAL


class TestNivelOrganizacional:
    def test_alcance_mas_persistencia_sin_impacto(self):
        assert _sev(declared_teams_involved=["team_alpha", "team_growth"],
                    months_present_last_6=5,
                    pct_tickets_high_or_medium_strategic=0.05) == ORGANIZACIONAL


class TestNivelEstrategico:
    def test_persistencia_mas_impacto_sin_alcance_multiequipo(self):
        assert _sev(declared_teams_involved=["team_alpha"],
                    months_present_last_6=6,
                    pct_tickets_high_or_medium_strategic=0.40) == ESTRATEGICO

    def test_los_tres_criterios(self):
        assert _sev(declared_teams_involved=["team_alpha", "team_beta", "team_gamma"],
                    months_present_last_6=6,
                    pct_tickets_high_or_medium_strategic=0.50) == ESTRATEGICO


class TestBordesDeUmbral:
    def test_persistencia_justo_en_el_umbral_cuenta(self):
        # months_present_last_6 == persistence_months_required (3 por default) debe CONTAR
        assert _sev(declared_teams_involved=["team_alpha", "team_beta"],
                    months_present_last_6=3,
                    pct_tickets_high_or_medium_strategic=0.0) == ORGANIZACIONAL

    def test_persistencia_justo_debajo_del_umbral_no_cuenta(self):
        assert _sev(declared_teams_involved=["team_alpha", "team_beta"],
                    months_present_last_6=2,
                    pct_tickets_high_or_medium_strategic=0.0) == TACTICA

    def test_impacto_justo_en_el_umbral_cuenta(self):
        # pct == 0.15 (umbral default) debe CONTAR (>=)
        assert _sev(declared_teams_involved=["team_alpha", "team_beta"],
                    months_present_last_6=0,
                    pct_tickets_high_or_medium_strategic=0.15) == ESTRUCTURAL

    def test_impacto_justo_debajo_del_umbral_no_cuenta(self):
        assert _sev(declared_teams_involved=["team_alpha", "team_beta"],
                    months_present_last_6=0,
                    pct_tickets_high_or_medium_strategic=0.1499) == TACTICA

    def test_un_solo_equipo_no_cuenta_como_alcance(self):
        assert _sev(declared_teams_involved=["team_alpha"],
                    months_present_last_6=6,
                    pct_tickets_high_or_medium_strategic=0.0) == TACTICA

    def test_umbral_configurable(self):
        # con un umbral de negocio más laxo (0.05), 0.06 sí debe contar
        assert _sev(declared_teams_involved=["team_alpha", "team_beta"],
                    months_present_last_6=0,
                    pct_tickets_high_or_medium_strategic=0.06,
                    strategic_volume_threshold=0.05) == ESTRUCTURAL


class TestContratoDeSalida:
    def test_devuelve_criteria_met_y_rationale(self):
        result = classify_change_severity(
            Finding(finding_id="f-x", declared_teams_involved=["team_alpha", "team_beta"],
                    months_present_last_6=6, pct_tickets_high_or_medium_strategic=0.5)
        )
        assert result["finding_id"] == "f-x"
        assert result["n_criteria_met"] == 3
        assert set(result["criteria_met"].keys()) == {"alcance_estructural", "persistencia", "impacto_core"}
        assert "rationale" in result and isinstance(result["rationale"], str)

    def test_acepta_dict_ademas_de_finding(self):
        result = classify_change_severity(
            {"finding_id": "f-dict", "declared_teams_involved": ["team_alpha"],
             "months_present_last_6": 0, "pct_tickets_high_or_medium_strategic": 0.0}
        )
        assert result["severity"] == TACTICA
