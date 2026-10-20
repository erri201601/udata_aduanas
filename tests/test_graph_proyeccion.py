"""Tests de la proyección a grafo (§28).

Con un grafo de mentira: CI no tiene Neo4j y no se finge que sí. Lo que estos
tests fijan es lo que no se puede comprobar mirando el grafo terminado — que
la proyección sea idempotente, que `data_origin` viaje, que la vigencia NO se
duplique en las relaciones, y que los nombres sean los del §28.

La corrida real contra el dev server va en el PR, con sus números.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from graph.proyeccion import Resumen, proyectar

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

pytestmark = pytest.mark.unit


class GrafoFalso:
    """Guarda lo que le mandan, con la misma semántica de MERGE por clave."""

    def __init__(self) -> None:
        self.nodos: dict[str, dict[str, dict[str, Any]]] = {}
        self.relaciones: dict[str, set[tuple[str, str]]] = {}
        self.claves: dict[str, str] = {}

    def merge_nodos(
        self, etiqueta: str, filas: Sequence[Mapping[str, Any]], *, clave: str = "id"
    ) -> int:
        self.claves[etiqueta] = clave
        destino = self.nodos.setdefault(etiqueta, {})
        for fila in filas:
            destino[str(fila[clave])] = dict(fila)
        return len(filas)

    def merge_relaciones(
        self,
        tipo: str,
        origen: str,
        destino: str,
        pares: Sequence[tuple[str, str]],
        *,
        clave_origen: str = "id",
        clave_destino: str = "id",
    ) -> int:
        self.relaciones.setdefault(tipo, set()).update(pares)
        return len(pares)

    def conteos(self) -> dict[str, int]:
        return {e: len(n) for e, n in self.nodos.items()} | {
            t: len(p) for t, p in self.relaciones.items()
        }


FRACCION = uuid.uuid4()
NICO = uuid.uuid4()
DECISION = uuid.uuid4()
REGLA = uuid.uuid4()


class _Fila(tuple):
    """Imita la fila de SQLAlchemy: se desempaca como tupla y tiene `_mapping`."""

    campos: tuple[str, ...] = ()

    def __new__(cls, datos: Mapping[str, Any]) -> _Fila:
        fila = super().__new__(cls, tuple(datos.values()))
        fila.campos = tuple(datos)
        return fila

    @property
    def _mapping(self) -> dict[str, Any]:
        return dict(zip(self.campos, self, strict=True))


class SesionFalsa:
    """Devuelve lotes fijos, en el orden en que el proyector pregunta."""

    def __init__(self, lotes: list[list[Mapping[str, Any]]]) -> None:
        self._lotes = lotes
        self.consultas = 0

    def execute(self, _sentencia: Any) -> Any:
        lote = self._lotes[self.consultas] if self.consultas < len(self._lotes) else []
        self.consultas += 1
        filas = [_Fila(d) for d in lote]
        return type("R", (), {"all": lambda _s: filas})()


def _escenario() -> list[list[Mapping[str, Any]]]:
    """Una fracción, su NICO y una norma. El resto de consultas, vacías."""
    fraccion = {
        "id": FRACCION,
        "code": "84713001",
        "chapter": "84",
        "heading": "8471",
        "subheading": "847130",
        "description": "Máquinas portátiles",
        "valid_from": date(2022, 6, 7),
        "valid_to": None,
        "data_origin": "OFFICIAL",
    }
    nico = {
        "id": NICO,
        "code": "00",
        "full_code": "8471300100",
        "description": "Los demás",
        "valid_from": date(2022, 6, 7),
        "valid_to": None,
        "data_origin": "OFFICIAL",
    }
    regla = {
        "id": REGLA,
        "rule_number": "58",
        "path": None,
        "valid_from": date(2020, 1, 1),
        "valid_to": None,
        "data_origin": "OFFICIAL",
    }
    # 14 consultas de nodos (NOM, PROSECSector y RegulatoryEvent al final).
    nodos: list[list[Mapping[str, Any]]] = [[fraccion], [nico], [regla]] + [[] for _ in range(11)]
    # 13 de relaciones (SUBJECT_TO, ELIGIBLE_UNDER y AFFECTED_BY al final).
    relaciones: list[list[Mapping[str, Any]]] = [[{"tariff_fraction_id": FRACCION, "id": NICO}]] + [
        [] for _ in range(12)
    ]
    return nodos + relaciones


def test_los_nombres_son_los_del_maestro() -> None:
    """Alguien va a leer el §28 y luego el grafo: mismo vocabulario."""
    import inspect

    from graph import proyeccion

    fuente = inspect.getsource(proyeccion)
    for nombre in ("HAS_NICO", "CLASSIFIED_AS", "SUPPLIED_BY", "LOCATED_IN", "SUPPORTED_BY"):
        assert f'"{nombre}"' in fuente, f"el §28 nombra {nombre}"
    for nombre in ("CITES", "BELONGS_TO", "HAS_ITEM", "DECLARES"):
        assert f'"{nombre}"' in fuente


def test_las_omisiones_del_28_estan_escritas() -> None:
    """Una omisión documentada es una decisión; una silenciosa parece un olvido."""
    from graph import proyeccion

    doc = proyeccion.__doc__ or ""
    for ausente in ("Treaty", "Manufacturer"):
        assert ausente in doc, f"falta decir por qué no está {ausente}"
    # Y los que salieron de la lista, con la fuente que los desbloqueó.
    for nombre in ("NOM", "RegulatoryEvent", "Anexo 2.4.1", "PROSECSector", "Decreto PROSEC"):
        assert nombre in doc


def test_el_grafo_no_fundamenta_nada() -> None:
    from graph import proyeccion

    doc = (proyeccion.__doc__ or "").upper()
    assert "NO FUNDAMENTA NADA" in doc
    assert "CONTENT_HASH" in doc


def test_ninguna_relacion_lleva_propiedades() -> None:
    """La vigencia vive en los nodos. Dos copias se desincronizan."""
    import inspect

    from graph.ports import Grafo

    firma = inspect.signature(Grafo.merge_relaciones)
    assert "propiedades" not in firma.parameters
    assert set(firma.parameters) == {
        "self",
        "tipo",
        "origen",
        "destino",
        "pares",
        "clave_origen",
        "clave_destino",
    }


def test_proyectar_dos_veces_deja_el_mismo_grafo() -> None:
    """La idempotencia se demuestra, no se declara."""
    grafo = GrafoFalso()

    primero = proyectar(SesionFalsa(_escenario()), grafo)  # type: ignore[arg-type]
    conteos = grafo.conteos()
    segundo = proyectar(SesionFalsa(_escenario()), grafo)  # type: ignore[arg-type]

    assert grafo.conteos() == conteos, "la segunda corrida cambió el grafo"
    assert primero.nodos == segundo.nodos
    assert conteos["TariffFraction"] == 1
    assert conteos["HAS_NICO"] == 1


def test_data_origin_viaja_en_cada_nodo_que_lo_tiene() -> None:
    """Con el corpus dentro, 180 partidas SYNTHETIC junto a lo real (§33)."""
    grafo = GrafoFalso()
    proyectar(SesionFalsa(_escenario()), grafo)  # type: ignore[arg-type]

    fraccion = next(iter(grafo.nodos["TariffFraction"].values()))
    assert fraccion["data_origin"] == "OFFICIAL"
    assert fraccion["valid_from"] == date(2022, 6, 7), "la vigencia viaja como fecha"


def test_el_id_de_la_fila_es_la_identidad_del_nodo() -> None:
    """Por eso hay un nodo por VERSIÓN: en SQL también hay una fila por versión."""
    grafo = GrafoFalso()
    proyectar(SesionFalsa(_escenario()), grafo)  # type: ignore[arg-type]

    assert grafo.claves["TariffFraction"] == "id"
    assert grafo.claves["Country"] == "code", "el país no sale de ninguna tabla"


def test_el_resumen_suma_lo_que_se_proyecto() -> None:
    r = Resumen(nodos={"TariffFraction": 8136, "Nico": 11503}, relaciones={"HAS_NICO": 11503})

    assert r.total_nodos == 19639
    assert r.total_relaciones == 11503


# ── NOM y cuándo se proyectó (13-oct) ───────────────────────────────────────

NOM_ID = uuid.uuid4()


def _escenario_con_nom() -> list[list[Mapping[str, Any]]]:
    """La fracción del escenario y una correlación del Anexo 2.4.1."""
    lotes = _escenario()
    nom = {
        "id": NOM_ID,
        "code": "NOM-019-SCFI-1998",
        "fraction_code": "84713001",
        "numeral": 1,
        "scope_note": "Únicamente: equipos con alimentación de la red",
        "valid_from": date(2023, 1, 1),
        "valid_to": None,
        "data_origin": "OFFICIAL",
    }
    lotes[11] = [nom]  # la 12.ª consulta de nodos es la de NOM
    lotes[14 + 10] = [{"tariff_fraction_id": FRACCION, "id": NOM_ID}]  # SUBJECT_TO
    return lotes


def test_la_nom_se_proyecta_con_su_alcance_y_su_vigencia() -> None:
    """Un nodo por correlación: el «Únicamente: …» y la vigencia son suyos."""
    grafo = GrafoFalso()
    proyectar(SesionFalsa(_escenario_con_nom()), grafo)  # type: ignore[arg-type]

    nom = grafo.nodos["NOM"][str(NOM_ID)]
    assert nom["code"] == "NOM-019-SCFI-1998"
    assert nom["scope_note"].startswith("Únicamente")
    assert nom["valid_from"] == date(2023, 1, 1)
    assert nom["data_origin"] == "OFFICIAL"
    assert grafo.relaciones["SUBJECT_TO"] == {(str(FRACCION), str(NOM_ID))}


PROSEC_ID = uuid.uuid4()


def test_el_prosec_se_proyecta_por_fila_y_sin_la_tasa() -> None:
    """Un nodo por fila del decreto: la acotación y la vigencia son suyas. La
    tasa no viaja aunque la consulta la trajera: el dinero no va al grafo."""
    lotes = _escenario()
    lotes[12] = [  # la 13.ª consulta de nodos es la de PROSECSector
        {
            "id": PROSEC_ID,
            "code": "I",
            "name": "Industria Eléctrica",
            "fraction_code": "84713001",
            "is_partial": True,
            "scope_note": "Únicamente: portátiles",
            "valid_from": date(2024, 8, 26),
            "valid_to": None,
            "data_origin": "OFFICIAL",
        }
    ]
    lotes[14 + 11] = [{"tariff_fraction_id": FRACCION, "id": PROSEC_ID}]  # ELIGIBLE_UNDER
    grafo = GrafoFalso()
    proyectar(SesionFalsa(lotes), grafo)  # type: ignore[arg-type]

    sector = grafo.nodos["PROSECSector"][str(PROSEC_ID)]
    assert sector["code"] == "I" and sector["scope_note"].startswith("Únicamente")
    assert sector["data_origin"] == "OFFICIAL"
    assert grafo.relaciones["ELIGIBLE_UNDER"] == {(str(FRACCION), str(PROSEC_ID))}


def test_la_consulta_del_prosec_no_pide_la_tasa() -> None:
    import inspect

    from graph import proyeccion

    fuente = inspect.getsource(proyeccion)
    assert "ProsecRate.igi_rate" not in fuente


def test_sin_eventos_no_se_crea_ningun_nodo_vacio() -> None:
    grafo = GrafoFalso()
    proyectar(SesionFalsa(_escenario()), grafo)  # type: ignore[arg-type]

    assert grafo.nodos.get("RegulatoryEvent", {}) == {}
    assert grafo.relaciones.get("AFFECTED_BY", set()) == set()


def test_la_proyeccion_dice_cuando_se_hizo() -> None:
    """Un grafo de septiembre no puede leerse como si fuera de hoy."""
    from datetime import UTC, datetime

    grafo = GrafoFalso()
    ahora = datetime(2026, 10, 13, 22, 0, tzinfo=UTC)
    proyectar(SesionFalsa(_escenario()), grafo, ahora=ahora)  # type: ignore[arg-type]

    [marca] = grafo.nodos["Proyeccion"].values()
    assert marca["at"] == "2026-10-13T22:00:00+00:00"
    assert marca["decisiones"] == 0
    assert marca["nodos"] == 3
