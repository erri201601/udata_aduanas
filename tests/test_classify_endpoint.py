"""Tests del endpoint que crea decisiones.

Es el único que escribe, y el que convierte el sistema en algo que se puede
enseñar: hasta ahora todas las pantallas leían un caso precargado.

Los tests del catálogo son los que más importan: la tarifa real tiene
versiones solapadas del mismo código —`84713001` tiene una que venció en
2022 y otra vigente— y clasificar con la equivocada da un resultado que
parece correcto y no lo es (§14).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from database.models import LegalRule, TariffFraction
from database.repositories.notes import LegalNotesRepository
from database.repositories.tariff import MAX_CANDIDATOS, TariffCatalogRepository

pytestmark = pytest.mark.unit

FECHA = date(2026, 3, 15)


def _sql(sentencia: object) -> str:
    """La consulta compilada con sus valores, para poder afirmar sobre ella."""
    return " ".join(
        str(sentencia.compile(compile_kwargs={"literal_binds": True})).split()  # type: ignore[attr-defined]
    )


def _capturar(metodo: str, **kwargs: object) -> str:
    sesion = MagicMock()
    getattr(TariffCatalogRepository(sesion), metodo)(**kwargs)
    llamada = sesion.scalars.call_args or sesion.execute.call_args
    return _sql(llamada.args[0])


# ── La vigencia no es opcional ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metodo", "kwargs"),
    [
        ("headings", {"on_date": FECHA, "terms": ["laptop"]}),
        ("subheadings", {"on_date": FECHA, "heading": "8471"}),
        ("fractions", {"on_date": FECHA, "subheading": "847130"}),
    ],
)
def test_toda_consulta_filtra_por_vigencia(metodo: str, kwargs: dict) -> None:
    """EL TEST QUE IMPORTA.

    La tarifa tiene versiones solapadas del mismo código. Sin el filtro, una
    operación de 2024 podría clasificarse con la tarifa de 2026.
    """
    sql = _capturar(metodo, **kwargs)

    assert "valid_from <= '2026-03-15'" in sql
    assert "valid_to IS NULL" in sql
    assert "valid_to >= '2026-03-15'" in sql


def test_el_filtro_se_aplica_en_sql_no_despues() -> None:
    """Si se trajeran todas las versiones y se descartaran en Python,
    cualquier consulta que olvidara el paso devolvería la fila incorrecta.

    Se mira la cláusula WHERE y no la sentencia entera: `valid_from` también
    aparece en la lista de columnas del SELECT, así que buscarlo en todo el
    SQL no probaría nada.
    """
    sql = _capturar("fractions", on_date=FECHA, subheading="847130")
    where = sql.split("WHERE", 1)[1]

    assert "valid_from <= '2026-03-15'" in where
    assert "valid_to" in where


@pytest.mark.parametrize(
    ("metodo", "kwargs"),
    [
        ("headings", {"on_date": FECHA, "terms": ["x"]}),
        ("subheadings", {"on_date": FECHA, "heading": "8471"}),
        ("fractions", {"on_date": FECHA, "subheading": "847130"}),
    ],
)
def test_toda_consulta_esta_acotada(metodo: str, kwargs: dict) -> None:
    """Cien partidas no ayudan a decidir: hacen la traza ilegible."""
    assert f"LIMIT {MAX_CANDIDATOS}" in _capturar(metodo, **kwargs)


def test_las_fracciones_salen_de_la_tabla_correcta() -> None:
    sql = _capturar("fractions", on_date=FECHA, subheading="847130")

    assert "regulatory.tariff_fractions" in sql
    assert "subheading = '847130'" in sql


def test_ordena_por_especificidad() -> None:
    """La RGI 3 a) prefiere la partida más específica."""
    assert "specificity DESC" in _capturar("fractions", on_date=FECHA, subheading="847130")


# ── Notas legales: hoy no hay corpus, y se dice ─────────────────────────────


def test_las_notas_tambien_filtran_por_vigencia() -> None:
    """Nunca una norma posterior a la operación (§14)."""
    sesion = MagicMock()
    LegalNotesRepository(sesion).notes_for(on_date=FECHA, chapter="84")

    sql = _sql(sesion.scalars.call_args.args[0])
    assert "valid_from <= '2026-03-15'" in sql
    assert "regulatory.legal_rules" in sql


def test_hay_corpus_distingue_vacio_de_no_consultado() -> None:
    """Sin notas, una clasificación es menos fundamentada — y hay que decirlo.

    La RGI 1 se determina por los textos de las partidas Y por las notas.
    Devolver «no excluye» sin haberlas consultado sería mentir por omisión.
    """
    sesion = MagicMock()
    sesion.scalar.return_value = 0

    assert LegalNotesRepository(sesion).hay_corpus(on_date=FECHA) is False

    sesion.scalar.return_value = 12
    assert LegalNotesRepository(sesion).hay_corpus(on_date=FECHA) is True


def test_sin_terminos_no_hay_exclusion_inventada() -> None:
    """Sin con qué buscar, no se afirma que algo excluya."""
    assert (
        LegalNotesRepository(MagicMock()).excludes(on_date=FECHA, heading="8471", terms=[]) is None
    )


# ── Contrato con el motor ───────────────────────────────────────────────────


def test_los_repositorios_cumplen_los_puertos_del_motor() -> None:
    """Si un puerto cambia, esto falla antes de que falle una clasificación."""
    from core.rgi_engine.ports import LegalNotes, TariffCatalog

    assert isinstance(TariffCatalogRepository(MagicMock()), TariffCatalog)
    assert isinstance(LegalNotesRepository(MagicMock()), LegalNotes)


def test_las_columnas_usadas_existen() -> None:
    """Evita el fallo que tuve: asumir `rule_type` y `scope_code`, que no existen."""
    columnas_regla = {c.name for c in LegalRule.__table__.columns}
    columnas_fraccion = {c.name for c in TariffFraction.__table__.columns}

    assert {"path", "rule_number", "text", "valid_from", "valid_to"} <= columnas_regla
    assert {"code", "heading", "subheading", "specificity"} <= columnas_fraccion


def test_el_codigo_viaja_como_texto() -> None:
    """Los ceros a la izquierda son significativos: 08471301 ≠ 8471301."""
    assert isinstance(TariffFraction.__table__.c.code.type, sa.String)


# ── Una nota no excluye por compartir una palabra ────────────────────────────


def test_las_notas_no_excluyen_por_coincidencia_de_termino() -> None:
    """EL TEST QUE IMPORTA.

    `excludes()` buscaba una nota del capítulo cuyo texto contuviera alguno de
    los términos de búsqueda. Con `legal_rules` vacía nunca encontraba nada y
    el defecto no se veía. El 8 de septiembre Persona 2 cargó las 92 notas
    reales y entonces excluyó TODAS las partidas candidatas de una computadora
    portátil: la nota del Capítulo 84 menciona «portátiles» hablando de
    herramientas de mano.

    Una exclusión falsa descarta la partida correcta, y el sistema clasifica
    mal con apariencia de rigor. Es el error más caro de los dos posibles.
    """
    sesion = MagicMock()
    resultado = LegalNotesRepository(sesion).excludes(
        on_date=FECHA, heading="8471", terms=["portátil", "Laptop"]
    )

    assert resultado is None
    # Y no lo decide consultando: no hay consulta que hacer.
    sesion.scalar.assert_not_called()


def test_las_notas_aplicables_se_buscan_por_la_partida_no_por_el_termino() -> None:
    """`applicable()` entrega lo que hay que leer, sin afirmar que excluya."""
    sql = _capturar_applicable(on_date=FECHA, heading="84713001")

    # La LIGIE escribe la partida con punto; el texto real usa las dos formas.
    assert "84.71" in sql
    assert "partida 8471" in sql
    # Y se acota al capítulo, no a toda la ley.
    assert "capítulo 84" in sql


def _capturar_applicable(**kwargs: object) -> str:
    sesion = MagicMock()
    LegalNotesRepository(sesion).applicable(**kwargs)  # type: ignore[arg-type]
    return _sql(sesion.scalars.call_args.args[0])


# ── El embedder no puede tumbar una clasificación ────────────────────────────


def test_la_respuesta_declara_como_se_buscó() -> None:
    """Dos clasificaciones con distinto modo se apoyan en normas distintas.

    Quien audite la decisión tiene que poder saberlo: la decisión persiste y
    el modo no.
    """
    from apps.api.routers.products import ClassifyResponse

    assert "modo_busqueda" in ClassifyResponse.model_fields
    assert "degradado_por" in ClassifyResponse.model_fields
    assert ClassifyResponse.model_fields["degradado_por"].default is None


def test_siempre_hay_una_razon_que_dar_por_no_usar_vectores() -> None:
    """Degradar en silencio sería tan malo como fallar (Persona 1, 9-sep)."""
    from apps.api.routers.products import _porque_no_vectores
    from core.llm.errors import ProviderResponseError
    from rag.embedder import EmbedderDegradable

    assert "no hay proveedor" in _porque_no_vectores(None)

    class Falla:
        name = "openai"
        default_embedding_model = "text-embedding-3-small"

        def embed(self, text: str, *, model: str | None = None) -> list[float]:
            raise ProviderResponseError("429 Too Many Requests", provider="openai")

    e = EmbedderDegradable(Falla())  # type: ignore[arg-type]
    e.embed(["x"])

    razon = _porque_no_vectores(e)
    assert "429" in razon
    assert "se siguió por término" in razon


def test_clasificar_pide_el_embedder_opcional_no_uno_obligatorio() -> None:
    """La garantía vive aquí: `embedder_opcional` devuelve `None` en vez de
    lanzar, así que no hay camino por el que la falta de llave impida
    clasificar."""
    import inspect

    from apps.api import clasificacion
    from apps.api.routers import products

    # La tubería vive en `apps.api.clasificacion` desde que el harness de
    # evaluación la comparte; el router la llama.
    tuberia = inspect.getsource(clasificacion.clasificar_borrador)
    assert "embedder_opcional()" in tuberia
    assert "build_provider" not in tuberia, "la tubería no construye proveedores"
    assert "clasificar_borrador(" in inspect.getsource(products.clasificar)
