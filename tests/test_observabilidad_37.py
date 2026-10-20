"""§37: cada pipeline y motor registra run_id, módulo, inicio, fin, estado,
duración, registros, errores, modelo y versión de prompt."""

from __future__ import annotations

import pytest
import structlog
from apps.api.logging import con_corrida, registrar, run_context
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit


def _eventos(logs: list[dict], nombre: str) -> list[dict]:  # type: ignore[type-arg]
    return [e for e in logs if e.get("event") == nombre]


def test_el_run_id_llega_a_los_logs_de_dentro_y_el_cierre_lleva_lo_anotado() -> None:
    with (
        capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs,
        run_context("prueba.modulo") as corrida,
    ):
        structlog.get_logger("core.lo_que_sea").info("dentro")
        registrar(records=3, model="claude-x", prompt_version="0.2")
        registrar(records=2)
    [dentro] = _eventos(logs, "dentro")
    assert dentro["run_id"] == corrida.run_id
    assert dentro["module"] == "prueba.modulo"
    [fin] = _eventos(logs, "run.finished")
    assert fin["status"] == "OK"
    assert fin["records"] == 5
    assert (fin["model"], fin["prompt_version"]) == ("claude-x", "0.2")
    assert fin["errors"] == 0
    assert {"started_at", "finished_at", "duration_ms"} <= set(fin)


def test_fuera_de_una_corrida_registrar_no_hace_nada() -> None:
    registrar(records=1)


def test_el_contexto_se_limpia_al_salir() -> None:
    with run_context("a"):
        pass
    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        structlog.get_logger("x").info("despues")
    assert "run_id" not in logs[0]


def test_un_systemexit_con_error_es_failed_y_uno_limpio_es_ok() -> None:
    @con_corrida("cli.que_falla")
    def falla() -> int:
        raise SystemExit("no hay FIX cargado")

    @con_corrida("cli.que_termina")
    def termina() -> int:
        raise SystemExit(0)

    with capture_logs() as logs:
        with pytest.raises(SystemExit):
            falla()
        with pytest.raises(SystemExit):
            termina()
    fines = _eventos(logs, "run.finished")
    assert [f["status"] for f in fines] == ["FAILED", "OK"]
    assert fines[0]["errors"] == 1


def test_una_excepcion_es_failed_y_se_propaga() -> None:
    with capture_logs() as logs, pytest.raises(ValueError), run_context("motor"):
        raise ValueError("roto")
    [fin] = _eventos(logs, "run.finished")
    assert fin["status"] == "FAILED"
    assert "ValueError: roto" in fin["error"]
