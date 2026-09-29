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
    nodos: list[list[Mapping[str, Any]]] = [[fraccion], [nico], [regla]] + [[] for _ in range(8)]
    relaciones: list[list[Mapping[str, Any]]] = [[{"tariff_fraction_id": FRACCION, "id": NICO}]] + [
        [] for _ in range(9)
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
    for ausente in ("NOM", "PROSECSector", "Treaty", "RegulatoryEvent", "Manufacturer"):
        assert ausente in doc, f"falta decir por qué no está {ausente}"
    assert "Anexo 2.4.1" in doc, "hay que decir qué fuente desbloquea cada uno"


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
