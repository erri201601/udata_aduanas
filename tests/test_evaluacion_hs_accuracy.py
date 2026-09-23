"""Tests del harness de hs_accuracy (§39).

TODOS LOS CASOS DE ESTE ARCHIVO SON SYNTHETIC. Ninguno es un ruling real ni se
presenta como tal: son dobles para fijar el comportamiento del harness antes de
que exista el adaptador de CBP CROSS. Los identificadores empiezan por «SIM-».

Los tests que deciden si el número vale algo son los de las cuatro reglas de
Persona 1: no persiste, sin fugas, seis dígitos del SA 2022, y cuesta dinero.
"""

from __future__ import annotations

import inspect
import pathlib
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from core.evaluation import (
    CasoDeEvaluacion,
    Clasificacion,
    ExtraccionConUso,
    Tarifas,
    UsoDeCaso,
    estimar_costo,
    evaluar,
    motivo_de_exclusion,
)
from core.product_dna.types import ProductDnaDraft, SourceDocument

pytestmark = pytest.mark.unit

TARIFAS = Tarifas(
    entrada_por_mtok=Decimal("2"),
    salida_por_mtok=Decimal("10"),
    embedding_por_mtok=Decimal("0.02"),
    fuente="tarifas de prueba",
)


def _caso(
    hs6: str = "847130",
    *,
    descripcion: str = "Computadora portátil de 14 pulgadas con procesador y teclado.",
    nomenclatura: str = "HS2022",
    fecha: date = date(2024, 3, 15),
    n: int = 1,
) -> CasoDeEvaluacion:
    return CasoDeEvaluacion(
        identificador=f"SIM-{n:03d}",
        descripcion=descripcion,
        hs6_esperado=hs6,
        fecha=fecha,
        fuente="SIMULADO",
        nomenclatura=nomenclatura,
        data_origin="SYNTHETIC",
    )


def _extraer(_doc: SourceDocument) -> ExtraccionConUso:
    return ExtraccionConUso(
        dna=ProductDnaDraft(summary="x"), uso=UsoDeCaso(entrada=1000, salida=200)
    )


def _clasificador(
    codigo: str | None,
    *,
    estado: str = "RESOLVED",
    rgi: tuple[str, ...] = ("RGI-1",),
    vectores: bool = True,
) -> Any:
    def clasificar(_dna: ProductDnaDraft, _fecha: date) -> Clasificacion:
        return Clasificacion(codigo=codigo, estado=estado, rgi_path=rgi, uso_vectores=vectores)

    return clasificar


def _correr(casos: list[CasoDeEvaluacion], clasificar: Any, **kw: Any) -> Any:
    return evaluar(
        casos, fuente="SIMULADO", extraer=_extraer, clasificar=clasificar, tarifas=TARIFAS, **kw
    )


# ── Regla 3: seis dígitos, SA 2022 ───────────────────────────────────────────


def test_se_comparan_solo_los_seis_primeros_digitos() -> None:
    """La fracción mexicana tiene ocho; el SA armonizado, seis."""
    r = _correr([_caso("847130")], _clasificador("84713001"))

    assert r.hs_accuracy.aciertos == 1
    assert r.resultados[0].hs6_obtenido == "847130"


def test_otra_nomenclatura_se_excluye_no_se_adapta() -> None:
    r = _correr([_caso(nomenclatura="HS2017")], _clasificador("84713001"))

    assert r.evaluados == 0
    assert r.excluidos == {"NOMENCLATURA_NO_SA2022": 1}
    assert r.hs_accuracy.porcentaje is None, "sin evaluados es desconocido, no cero"


def test_un_hts10_no_se_trunca_dentro_del_harness() -> None:
    """NUNCA HTS10 → TIGIE. Si llega un código de diez dígitos es un error del
    adaptador, y se excluye en vez de recortarlo en silencio."""
    assert motivo_de_exclusion(_caso("8471300100"), fecha_minima=None) == "HS6_INVALIDO"


def test_antes_de_la_tarifa_vigente_no_se_mide_al_motor() -> None:
    motivo = motivo_de_exclusion(_caso(fecha=date(2021, 5, 1)), fecha_minima=date(2022, 6, 7))

    assert motivo == "FUERA_DE_VIGENCIA_DEL_CATALOGO"


# ── Regla 2: sin fugas ───────────────────────────────────────────────────────


def test_al_extractor_solo_le_llega_la_descripcion() -> None:
    """EL TEST QUE IMPORTA. Si la respuesta entra por algún lado, el número no
    mide nada."""
    vistos: list[SourceDocument] = []

    def extraer(doc: SourceDocument) -> ExtraccionConUso:
        vistos.append(doc)
        return _extraer(doc)

    caso = _caso("847130", n=7)
    evaluar(
        [caso],
        fuente="SIMULADO",
        extraer=extraer,
        clasificar=_clasificador("84713001"),
        tarifas=TARIFAS,
    )

    (doc,) = vistos
    assert doc.text == caso.descripcion
    assert doc.reference is None, "ni el id del ruling viaja al motor"
    assert "847130" not in doc.model_dump_json()
    assert "SIM-007" not in doc.model_dump_json()


def test_el_clasificador_no_recibe_el_caso() -> None:
    """La firma lo impide: recibe DNA y fecha. Nada del ruling cabe ahí."""
    recibido: list[tuple[Any, ...]] = []

    def clasificar(*args: Any) -> Clasificacion:
        recibido.append(args)
        return Clasificacion(codigo="84713001", estado="RESOLVED", uso_vectores=True)

    _correr([_caso("847130")], clasificar)

    (args,) = recibido
    assert len(args) == 2
    assert isinstance(args[0], ProductDnaDraft)
    assert isinstance(args[1], date)


@pytest.mark.parametrize("texto", ["partida 8471.30 del SA", "código 847130", "8471 30 portátiles"])
def test_una_descripcion_con_la_respuesta_se_excluye(texto: str) -> None:
    r = _correr([_caso("847130", descripcion=texto)], _clasificador("84713001"))

    assert r.excluidos == {"POSIBLE_FUGA": 1}
    assert r.evaluados == 0


def test_un_numero_parecido_no_es_fuga() -> None:
    assert (
        motivo_de_exclusion(
            _caso("847130", descripcion="modelo 18471309 de 14 pulgadas"), fecha_minima=None
        )
        is None
    )


# ── Lo que el número no dice solo ────────────────────────────────────────────


def test_insuficiente_cuenta_como_no_acierto_pero_se_desglosa() -> None:
    """Un 50 % con la mitad de insuficientes no es el mismo motor que un 50 %
    que se equivoca de partida."""
    casos = [_caso("847130", n=1), _caso("847130", n=2)]
    respuestas = iter(
        [
            Clasificacion(codigo="84713001", estado="RESOLVED", uso_vectores=True),
            Clasificacion(codigo=None, estado="INSUFFICIENT_INFORMATION", uso_vectores=True),
        ]
    )
    r = _correr(casos, lambda _d, _f: next(respuestas))

    assert r.hs_accuracy.porcentaje == Decimal("50.00")
    assert r.acierto_cuando_responde.porcentaje == Decimal("100.00")
    assert r.tasa_insuficiente == Decimal("50.00")


def test_se_cuenta_el_desempate_por_rgi_3c_normalizado() -> None:
    r = _correr([_caso()], _clasificador("85285900", rgi=("RGI-1", "RGI3C")))

    assert r.tasa_rgi_3c == Decimal("100.00")


def test_se_cuenta_la_degradacion_a_busqueda_por_termino() -> None:
    r = _correr([_caso()], _clasificador("84713001", vectores=False))

    assert r.tasa_degradacion == Decimal("100.00")


def test_un_caso_que_falla_no_tumba_la_corrida() -> None:
    llamadas = iter([RuntimeError("429 Too Many Requests"), None])

    def clasificar(_d: ProductDnaDraft, _f: date) -> Clasificacion:
        error = next(llamadas)
        if error:
            raise error
        return Clasificacion(codigo="84713001", estado="RESOLVED", uso_vectores=True)

    r = _correr([_caso(n=1), _caso(n=2)], clasificar)

    assert r.errores == 1
    assert r.evaluados == 1
    assert "429" in (r.resultados[0].motivo or "")


def test_un_caso_synthetic_marca_el_reporte_como_simulacion() -> None:
    """§33: con un solo SYNTHETIC, el número no es una medición."""
    assert _correr([_caso()], _clasificador("84713001")).es_simulacion is True


def test_el_lote_respeta_el_limite() -> None:
    r = _correr([_caso(n=i) for i in range(50)], _clasificador("84713001"), limite=3)

    assert r.casos == 3


# ── Regla 4: cuesta dinero ───────────────────────────────────────────────────


def test_el_costo_se_calcula_en_decimal_con_las_tarifas() -> None:
    """1 000 in × $2 + 200 out × $10 = $0.004 por caso."""
    r = _correr([_caso(n=i) for i in range(10)], _clasificador("84713001"))

    assert r.costo_usd == Decimal("0.04")
    assert isinstance(r.costo_usd, Decimal)


def test_la_estimacion_con_el_consumo_medido() -> None:
    """1 842 in × $2 + 316 out × $10 + 100 emb × $0.02 ≈ $0.0068 por caso."""
    from apps.evaluacion.hs_accuracy import USO_DE_REFERENCIA

    assert estimar_costo(100, uso_por_caso=USO_DE_REFERENCIA, tarifas=TARIFAS) == Decimal("0.68")


# ── Regla 1: no persiste ─────────────────────────────────────────────────────


class _SesionEspia:
    def __init__(self, sospechosos: list[str] | None = None) -> None:
        self.sospechosos = sospechosos or []
        self.escrituras: list[str] = []
        self.rollbacks = 0

    def scalars(self, _s: Any) -> Any:
        r = type("R", (), {})()
        r.all = lambda: self.sospechosos
        return r

    def scalar(self, _s: Any) -> Any:
        return date(2022, 6, 7)

    def execute(self, s: Any, *a: Any, **k: Any) -> Any:
        return None

    def add(self, _x: Any) -> None:
        self.escrituras.append("add")

    def commit(self) -> None:
        self.escrituras.append("commit")

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.parametrize("metodo", ["add", "flush", "commit", "delete", "merge"])
def test_la_sesion_de_evaluacion_no_deja_escribir(metodo: str) -> None:
    from apps.evaluacion.hs_accuracy import EscrituraProhibidaError, SesionSoloLectura

    sesion = SesionSoloLectura(_SesionEspia())  # type: ignore[arg-type]

    with pytest.raises(EscrituraProhibidaError):
        getattr(sesion, metodo)


def test_la_sesion_de_evaluacion_rechaza_dml() -> None:
    import sqlalchemy as sa
    from apps.evaluacion.hs_accuracy import EscrituraProhibidaError, SesionSoloLectura
    from database.models import ClassificationDecision

    sesion = SesionSoloLectura(_SesionEspia())  # type: ignore[arg-type]

    with pytest.raises(EscrituraProhibidaError):
        sesion.execute(sa.delete(ClassificationDecision))
    sesion.execute(sa.select(ClassificationDecision))  # leer sí se puede


def test_la_tuberia_no_llama_a_save_classification() -> None:
    """Se mira el árbol del código, no el texto: el docstring lo menciona para
    decir justamente que no se llama."""
    import ast

    from apps.api import clasificacion

    arbol = ast.parse(inspect.getsource(clasificacion))
    nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
    atributos = {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
    importados = {
        alias.name for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom) for alias in n.names
    }
    assert "save_classification" not in nombres | atributos | importados


def test_sin_confirmar_no_se_llama_a_ningun_modelo() -> None:
    """Primero el presupuesto. Gastar es un acto explícito."""
    from apps.evaluacion.hs_accuracy import Presupuesto, ejecutar

    llamado = False

    def extraer(_d: SourceDocument) -> ExtraccionConUso:
        nonlocal llamado
        llamado = True
        return _extraer(_d)

    fuente = type("F", (), {"nombre": "SIMULADO", "casos": lambda _self: iter([_caso()])})()
    resultado = ejecutar(fuente, _SesionEspia(), lote=5, extraer=extraer)  # type: ignore[arg-type]

    assert isinstance(resultado, Presupuesto)
    assert resultado.costo_estimado_usd == Decimal("0.03")
    assert resultado.techo_con_reintentos_usd == Decimal("0.06")
    assert llamado is False


def test_un_corpus_con_rulings_aborta_antes_de_correr() -> None:
    """Si CROSS entrara al RAG, el motor podría citar la respuesta."""
    from apps.evaluacion.hs_accuracy import FugaEnCorpusError, ejecutar

    fuente = type("F", (), {"nombre": "SIMULADO", "casos": lambda _self: iter([])})()

    with pytest.raises(FugaEnCorpusError):
        ejecutar(fuente, _SesionEspia(sospechosos=["CBP_CROSS"]), confirmar=True)  # type: ignore[arg-type]


def test_el_nucleo_del_harness_no_conoce_la_base() -> None:
    """§29: `core/` nunca importa persistencia."""
    for archivo in pathlib.Path("core/evaluation").glob("*.py"):
        fuente = archivo.read_text()
        assert "from database" not in fuente and "import sqlalchemy" not in fuente, archivo
        assert "from apps" not in fuente, archivo


# ── La nomenclatura que no se podía citar (23-sep) ───────────────────────────


def _caso_del_catalogo(**kw: object):  # type: ignore[no-untyped-def]
    from core.evaluation.harness import CasoDeEvaluacion

    base: dict[str, object] = {
        "identificador": "26 47 9999 600001/2",
        "descripcion": "ESTROPAJO DE ACERO INOXIDABLE PARA LIMPIEZA DOMESTICA",
        "hs6_esperado": "732310",
        "fecha": date(2026, 8, 3),
        "fuente": "CORPUS_ESPEJO/corpus_espejo_v1",
        "nomenclatura": "TIGIE",
        "data_origin": "SYNTHETIC",
        "mismo_catalogo_a_la_fecha": True,
    }
    base.update(kw)
    return CasoDeEvaluacion(**base)  # type: ignore[arg-type]


def test_una_verdad_del_mismo_catalogo_no_necesita_declarar_el_sa() -> None:
    """Comparar la misma tabla contra sí misma es válido por construcción.

    Afirmar «SA 2022» aquí era conocimiento nuestro disfrazado de hecho: la
    LIGIE 2022 no menciona el Sistema Armonizado en su Artículo 1 ni en su
    preámbulo (Persona 2, 23-sep, sobre las 893 páginas).
    """
    from core.evaluation.harness import motivo_de_exclusion

    assert motivo_de_exclusion(_caso_del_catalogo(), fecha_minima=None) is None


def test_una_fuente_externa_sigue_teniendo_que_declarar_hs2022() -> None:
    """El filtro protege algo real cuando las nomenclaturas son distintas.

    Sin `mismo_catalogo_a_la_fecha`, un HTS10 de Estados Unidos comparado
    contra la TIGIE pasaría como si midiera algo.
    """
    from core.evaluation.harness import motivo_de_exclusion

    caso = _caso_del_catalogo(nomenclatura="HTS2022", mismo_catalogo_a_la_fecha=False)

    assert motivo_de_exclusion(caso, fecha_minima=None) == "NOMENCLATURA_NO_SA2022"


def test_el_campo_no_es_un_pase_libre() -> None:
    """Sólo levanta el filtro de nomenclatura. Las otras salvaguardas siguen.

    Si dejara pasar una fuga o un HS6 inválido, sería una grieta en vez de una
    excepción razonada.
    """
    from core.evaluation.harness import motivo_de_exclusion

    fuga = _caso_del_catalogo(descripcion="ESTROPAJO, fracción 7323.10, de acero")
    invalido = _caso_del_catalogo(hs6_esperado="7323")
    viejo = _caso_del_catalogo(fecha=date(2020, 1, 1))

    assert motivo_de_exclusion(fuga, fecha_minima=None) == "POSIBLE_FUGA"
    assert motivo_de_exclusion(invalido, fecha_minima=None) == "HS6_INVALIDO"
    assert motivo_de_exclusion(viejo, fecha_minima=date(2022, 6, 7)) == (
        "FUERA_DE_VIGENCIA_DEL_CATALOGO"
    )


def test_por_omision_una_fuente_no_hereda_la_excepcion() -> None:
    """Quien escriba un adaptador tiene que afirmarlo a propósito."""
    from core.evaluation.harness import CasoDeEvaluacion

    caso = CasoDeEvaluacion(
        identificador="HQ H123456",
        descripcion="Steel wool scouring pad",
        hs6_esperado="732310",
        fecha=date(2026, 8, 3),
        fuente="CBP_CROSS",
        nomenclatura="HS2022",
        data_origin="PUBLIC",
    )

    assert caso.mismo_catalogo_a_la_fecha is False
