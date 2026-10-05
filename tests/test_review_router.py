"""Tests de la bandeja de revisión humana.

El que importa es `test_la_correccion_no_borra_la_respuesta_de_la_maquina`:
medir «fraction accuracy» del §39 exige conservar las dos respuestas. Si la
revisión editara la decisión original, el numerador de esa métrica
desaparecería y con él la única forma de saber si el sistema mejora.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationDecision, Product
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
DECISION_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")


def _aud(fila: Any) -> Any:
    fila.id = fila.id or uuid.uuid4()
    fila.created_at = AHORA
    fila.updated_at = AHORA
    for campo, vacio in (
        ("legal_rule_ids", []),
        ("input_snapshot", {}),
        ("missing_information", []),
        ("rgi_path", ["RGI1"]),
    ):
        if hasattr(fila, campo) and getattr(fila, campo) is None:
            setattr(fila, campo, vacio)
    return fila


def _decision(*, origen: str = "SYNTHETIC", pendiente: bool = True) -> ClassificationDecision:
    d = ClassificationDecision(
        product_id=uuid.uuid4(),
        product_dna_id=uuid.uuid4(),
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="HUMAN_REVIEW_REQUIRED",
        fraction_code="84714902",
        reasoning="RGI 1: la partida 8471 comprende…",
        engine_version="0.1.0",
        confidence=Decimal("0.4200"),
        requires_human_review=pendiente,
        data_origin=origen,
    )
    d.id = DECISION_ID
    d.rgi_trace = [{"rule_id": "RGI-1", "status": "RESOLVED", "reasoning_summary": "x"}]
    return _aud(d)


def _producto() -> Product:
    p = Product(
        sku="LAP-DEMO-001",
        commercial_name='Laptop Demo 14" 8GB',
        data_origin="SYNTHETIC",
    )
    return _aud(p)


class SesionFalsa:
    def __init__(
        self,
        *,
        decision: ClassificationDecision | None,
        ya_revisada: bool = False,
        fraccion_en_catalogo: bool = True,
        hay_tarifa: bool = True,
        hermanas: tuple[str, ...] = (),
        nicos_vigentes: tuple[str, ...] = (),
    ) -> None:
        self._decision = decision
        self._ya_revisada = ya_revisada
        #: Por defecto la fracción existe, para que los tests que no hablan del
        #: catálogo sigan probando lo suyo. Los que sí, lo ponen en falso.
        self._fraccion_en_catalogo = fraccion_en_catalogo
        #: ¿Hay tarifa cargada? Con `False`, el guardarraíl no debe acusar a
        #: nadie: un catálogo vacío no demuestra que la fracción no exista.
        self._hay_tarifa = hay_tarifa
        self._hermanas = hermanas
        #: Los NICO cargados de la fracción del veredicto. Vacío por defecto,
        #: que es el hueco NUESTRO: sin códigos no se rechaza nada.
        self._nicos_vigentes = nicos_vigentes
        self.agregadas: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.sql_bandeja: list[str] = []

    def scalar(self, sentencia: Any) -> Any:
        # `revisar` hace DOS consultas escalares, y confundirlas hacía que
        # todos los tests de este fichero fallaran a la vez: ¿existe la
        # fracción del veredicto en la tarifa?, y ¿hay ya un veredicto que
        # apunte a esta decisión? Se distinguen por la tabla.
        sql = str(sentencia)
        if "tariff_fractions" in sql:
            # Dos consultas distintas sobre la misma tabla: «¿hay tarifa
            # cargada?» no lleva filtro de código y «¿existe ESTE código?» sí.
            # Confundirlas dejaría el guardarraíl sin poder probarse, porque un
            # catálogo vacío no acusa a nadie.
            if "tariff_fractions.code =" in sql:
                return uuid.uuid4() if self._fraccion_en_catalogo else None
            return uuid.uuid4() if self._hay_tarifa else None
        return uuid.uuid4() if self._ya_revisada else None

    def rollback(self) -> None:
        self.rollbacks += 1

    def get(self, modelo: type, _id: uuid.UUID, **_opciones: Any) -> Any:
        if modelo is Product:
            return _producto()
        return self._decision

    def scalars(self, sentencia: Any) -> Any:
        #: El SQL de la bandeja, para poder afirmar sobre su acotamiento: la
        #: sesión falsa ignora los WHERE, así que el comportamiento sólo se fija
        #: mirando la sentencia.
        self.sql_bandeja.append(str(sentencia))
        r = type("R", (), {})()
        # Los NICO van PRIMERO: su consulta hace JOIN con `tariff_fractions`,
        # así que la rama de las hermanas la atraparía y devolvería fracciones
        # donde se esperan dos dígitos.
        if "regulatory.nicos" in str(sentencia):
            r.all = lambda: list(self._nicos_vigentes)
        elif "tariff_fractions" in str(sentencia):
            # Las hermanas de una fracción que no existe: son códigos, no
            # decisiones. Devolver la decisión aquí metía un objeto en el
            # mensaje de error.
            r.all = lambda: list(self._hermanas)
        else:
            r.all = lambda: [self._decision] if self._decision else []
        return r

    def add(self, fila: Any) -> None:
        _aud(fila)
        self.agregadas.append(fila)

    def commit(self) -> None:
        self.commits += 1


def _cliente(*, decision: ClassificationDecision | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(decision=decision)
    return TestClient(app)


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    with _cliente(decision=_decision()) as c:
        yield c


# ── La bandeja ──────────────────────────────────────────────────────────────


def test_lista_lo_que_espera_revision(cliente: TestClient) -> None:
    r = cliente.get("/review")

    assert r.status_code == 200
    assert r.json()[0]["fraction_code"] == "84714902"


def test_la_bandeja_trae_contexto_para_decidir(cliente: TestClient) -> None:
    """Sin el producto, quien revisa tendría que abrir otra pantalla."""
    fila = cliente.get("/review").json()[0]

    assert fila["producto"] == 'Laptop Demo 14" 8GB'
    assert fila["sku"] == "LAP-DEMO-001"


def test_declara_si_consta_el_razonamiento(cliente: TestClient) -> None:
    """Cero pasos cambia cuánto puede fiarse quien revisa."""
    assert cliente.get("/review").json()[0]["pasos_traza"] == 1


# ── El veredicto ────────────────────────────────────────────────────────────


def test_la_correccion_no_borra_la_respuesta_de_la_maquina() -> None:
    """EL TEST QUE IMPORTA.

    Medir «fraction accuracy» (§39) exige las dos respuestas. Editar la
    original destruiría el numerador de esa métrica.
    """
    original = _decision()
    app = create_app()
    sesion = SesionFalsa(decision=original)
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(
            f"/review/{DECISION_ID}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": "ulises",
                "fraction_code": "84713001",
                "nota": "Es portátil completa, no unidad de proceso.",
            },
        )

    assert r.status_code == 201
    # La original conserva su fracción y su razonamiento.
    assert original.fraction_code == "84714902"
    assert original.data_origin == "SYNTHETIC"
    # Y hay una fila NUEVA con el veredicto humano.
    assert len(sesion.agregadas) == 1
    assert sesion.agregadas[0].fraction_code == "84713001"
    assert sesion.agregadas[0].data_origin == "HUMAN_VALIDATED"


def test_la_revision_comparte_el_dna_con_la_original() -> None:
    """Es lo que permite emparejarlas al evaluar."""
    original = _decision()
    app = create_app()
    sesion = SesionFalsa(decision=original)
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        c.post(
            f"/review/{DECISION_ID}",
            json={"veredicto": "CONFIRMA", "reviewer": "ulises"},
        )

    assert sesion.agregadas[0].product_dna_id == original.product_dna_id


def test_la_original_sale_de_la_bandeja() -> None:
    original = _decision()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(decision=original)

    with TestClient(app) as c:
        c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert original.requires_human_review is False


def test_la_revision_no_hereda_la_traza_del_motor() -> None:
    """Copiarla haría parecer que la persona siguió esas reglas.

    No las siguió: revisó su conclusión.
    """
    app = create_app()
    sesion = SesionFalsa(decision=_decision())
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert sesion.agregadas[0].rgi_trace is None


def test_corregir_sin_fraccion_se_rechaza(cliente: TestClient) -> None:
    """Una corrección sin la respuesta correcta no dice nada."""
    r = cliente.post(f"/review/{DECISION_ID}", json={"veredicto": "CORRIGE", "reviewer": "ulises"})

    assert r.status_code == 422


def test_una_fraccion_que_no_existe_en_la_tarifa_se_rechaza() -> None:
    """REGRESIÓN REAL (ensayo de la demo del 29-sep).

    Se aceptó `73239399` para un sartén de acero inoxidable. Bajo esa
    subpartida la única fracción es `73239305`. La decisión quedó guardada,
    contada en el tablero como dictaminada y pintada en verde en Classification
    —«la única verdad del sistema que no generamos nosotros»— con una fracción
    que no está en la TIGIE.

    Un clasificador es la autoridad sobre el CRITERIO, no sobre qué códigos
    existen: un dígito mal teclado no se convierte en fracción por venir de una
    persona (regla 2 de CLAUDE.md).
    """
    app = create_app()
    sesion = SesionFalsa(decision=_decision(), fraccion_en_catalogo=False, hermanas=("73239305",))
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(
            f"/review/{DECISION_ID}",
            json={"veredicto": "CORRIGE", "reviewer": "cesar", "fraction_code": "73239399"},
        )

    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert "73239399" in detalle
    # Y enseña lo que SÍ existe, para que quien teclea pueda corregirse.
    assert "73239305" in detalle
    # Nada se guardó: un veredicto a medias es peor que ninguno.
    assert sesion.agregadas == []


def test_el_rechazo_enseña_el_catalogo_no_propone_una_fraccion() -> None:
    """Si la subpartida está vacía, lo dice; no busca una parecida.

    Proponer un código sería el sistema eligiendo la fracción, que es justo lo
    que esta comprobación existe para impedir.
    """
    app = create_app()
    sesion = SesionFalsa(decision=_decision(), fraccion_en_catalogo=False, hermanas=())
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(
            f"/review/{DECISION_ID}",
            json={"veredicto": "CORRIGE", "reviewer": "cesar", "fraction_code": "99999999"},
        )

    assert r.status_code == 422
    assert "ninguna" in r.json()["detail"]


def test_confirmar_una_fraccion_que_ya_no_existe_tambien_se_rechaza() -> None:
    """El guardarraíl no es sólo para CORRIGE.

    Confirmar copia la fracción de la original, y si ésa no está en el catálogo
    el veredicto humano le daría el respaldo que no tiene.
    """
    app = create_app()
    sesion = SesionFalsa(decision=_decision(), fraccion_en_catalogo=False, hermanas=())
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "cesar"})

    assert r.status_code == 422
    assert sesion.agregadas == []


def test_coincidir_en_que_no_se_puede_no_se_comprueba_contra_el_catalogo() -> None:
    """Un veredicto sin fracción no tiene nada que comprobar.

    Si la comprobación se aplicara igual, el revisor que coincide en que la
    mercancía no se puede clasificar recibiría un 422, y coincidir en eso es un
    resultado legítimo del sistema.
    """
    original = _decision()
    original.fraction_code = None
    app = create_app()
    sesion = SesionFalsa(decision=original, fraccion_en_catalogo=False)
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "cesar"})

    assert r.status_code == 201
    assert sesion.agregadas[0].fraction_code is None


def test_sin_tarifa_cargada_el_veredicto_no_se_rechaza() -> None:
    """Un catálogo vacío no demuestra que la fracción no exista.

    Lo descubrieron los tests de integración, que corren sobre una base sin
    tarifa: la primera versión de este guardarraíl rechazaba TODOS los
    veredictos, los diez del camino del revisor externo. Y habría hecho lo
    mismo en una instalación nueva del cliente, que es mucho peor que el defecto
    que vino a arreglar.

    Misma disciplina que `hay_unidades` para el Anexo 22: sin catálogo no se
    acusa a nadie.
    """
    app = create_app()
    sesion = SesionFalsa(decision=_decision(), hay_tarifa=False, fraccion_en_catalogo=False)
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(
            f"/review/{DECISION_ID}",
            json={"veredicto": "CORRIGE", "reviewer": "cesar", "fraction_code": "73239399"},
        )

    assert r.status_code == 201
    assert sesion.agregadas[0].fraction_code == "73239399"


def test_la_correccion_registra_quien_la_hizo(cliente: TestClient) -> None:
    """Una corrección anónima no es auditable."""
    r = cliente.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA"})

    assert r.status_code == 422


def test_no_se_revisa_una_revision() -> None:
    """Una fila HUMAN_VALIDATED ya pasó por una persona."""
    with _cliente(decision=_decision(origen="HUMAN_VALIDATED")) as c:
        r = c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert r.status_code == 409


def test_decision_inexistente_da_404() -> None:
    with _cliente(decision=None) as c:
        assert (
            c.post(
                f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"}
            ).status_code
            == 404
        )


def test_el_motivo_queda_por_escrito() -> None:
    """Sin motivo se sabe que el sistema falló, no en qué."""
    app = create_app()
    sesion = SesionFalsa(decision=_decision())
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        c.post(
            f"/review/{DECISION_ID}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": "ulises",
                "fraction_code": "84713001",
                "nota": "Es portátil completa.",
            },
        )

    razon = sesion.agregadas[0].reasoning
    assert "ulises" in razon
    assert "84714902" in razon and "84713001" in razon
    assert "Es portátil completa." in razon


# ── La bandeja dice por qué está cada caso (Persona 1, 9-sep) ────────────────


def _caso(**kwargs: Any) -> Any:
    from database.models import ClassificationDecision

    campos: dict[str, Any] = {
        "trade_flow": "IMPORT",
        "operation_date": date(2026, 3, 15),
        "status": "HUMAN_REVIEW_REQUIRED",
        "data_origin": "SYNTHETIC",
        "requires_human_review": True,
    }
    campos.update(kwargs)
    return ClassificationDecision(**campos)


def test_falta_informacion_y_desempate_no_son_lo_mismo() -> None:
    """EL TEST QUE IMPORTA.

    En un caso falta información; en el otro sobra una respuesta que nadie
    debería firmar tal cual. Un revisor que no los distingue no sabe qué le
    están pidiendo.
    """
    from apps.api.routers.review import _causas

    sin_info = _causas(_caso(status="INSUFFICIENT_INFORMATION", rgi_path=["RGI-1"]))
    desempate = _causas(_caso(rgi_path=["RGI-1", "RGI-3c"], fraction_code="85285900"))

    assert "SIN_INFORMACION" in sin_info
    assert "DESEMPATE_POR_NUMERACION" not in sin_info
    assert "DESEMPATE_POR_NUMERACION" in desempate
    assert "SIN_INFORMACION" not in desempate


def test_la_causa_del_desempate_sale_del_camino_rgi() -> None:
    """El dato ya estaba persistido: `rgi_path` lleva las reglas aplicadas."""
    from apps.api.routers.review import _causas

    assert "DESEMPATE_POR_NUMERACION" not in _causas(
        _caso(rgi_path=["RGI-1", "RGI-3a"], fraction_code="84713001")
    )
    assert "DESEMPATE_POR_NUMERACION" in _causas(
        _caso(rgi_path=["RGI-1", "RGI-3c"], fraction_code="84713001")
    )


def test_las_causas_concurren_sin_orden_de_gravedad() -> None:
    """No se inventa jerarquía: un caso puede tener varias razones a la vez."""
    from apps.api.routers.review import _causas

    causas = _causas(_caso(status="INSUFFICIENT_INFORMATION", rgi_path=["RGI-3c"]))

    assert set(causas) >= {"SIN_INFORMACION", "DESEMPATE_POR_NUMERACION"}


def test_sin_fraccion_revisar_es_proponerla_no_validarla() -> None:
    from apps.api.routers.review import _causas

    assert "SIN_FRACCION_PROPUESTA" in _causas(_caso(fraction_code=None))
    assert "SIN_FRACCION_PROPUESTA" not in _causas(
        _caso(fraction_code="84713001", rgi_path=["RGI-1"])
    )


def test_una_decision_resuelta_y_marcada_no_se_queda_muda() -> None:
    """Sin causa, el caso llega a la bandeja y nadie sabe qué se le pide."""
    from apps.api.routers.review import _causas

    assert _causas(_caso(status="RESOLVED", fraction_code="84713001", rgi_path=["RGI-1"])) == [
        "RESUELTA_PERO_MARCADA"
    ]


def test_el_identificador_de_regla_se_compara_normalizado() -> None:
    """El seed escribió `RGI1` y el motor escribe `RGI-1`.

    Comparar en crudo dejaría casos sin causa según quién los escribiera, y un
    caso sin causa es lo que esta pantalla viene a eliminar.
    """
    from apps.api.routers.review import _causas, _normalizar

    assert _normalizar("RGI-3c") == _normalizar("RGI3C") == "RGI3C"
    assert "DESEMPATE_POR_NUMERACION" in _causas(
        _caso(rgi_path=["RGI3C"], fraction_code="85285900")
    )


def test_toda_causa_tiene_explicacion() -> None:
    """Nombrar la causa sin decir qué se pide dejaría el trabajo a medias."""
    from apps.api.routers.review import CAUSAS, _causas

    todas = set()
    for fila in (
        _caso(status="INSUFFICIENT_INFORMATION"),
        _caso(rgi_path=["RGI-3c"], fraction_code="85285900"),
        _caso(fraction_code=None),
        _caso(status="RESOLVED", fraction_code="84713001", rgi_path=["RGI-1"]),
    ):
        todas.update(_causas(fila))

    assert todas <= set(CAUSAS), "hay causas sin texto"
    assert all(CAUSAS[c].strip() for c in todas)


# ── El veredicto dice qué revisó (Persona 1, opción 1, 14-sep) ───────────────


def test_el_veredicto_guarda_que_decision_revisa() -> None:
    """Es lo que empareja el veredicto con SU decisión en la métrica."""
    app = create_app()
    sesion = SesionFalsa(decision=_decision())
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert sesion.agregadas[0].reviews_decision_id == DECISION_ID


def test_una_decision_con_veredicto_da_409_y_no_escribe() -> None:
    app = create_app()
    sesion = SesionFalsa(decision=_decision(), ya_revisada=True)
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert r.status_code == 409
    assert sesion.agregadas == []


def test_una_resuelta_limpia_vuelve_a_poder_revisarse() -> None:
    """Deshace la consecuencia del #79: muestrear lo que la bandeja deja pasar."""
    with _cliente(decision=_decision(pendiente=False)) as c:
        r = c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert r.status_code == 201


class _Diag:
    def __init__(self, constraint: str) -> None:
        self.constraint_name = constraint


class _OrigError(Exception):
    def __init__(self, constraint: str) -> None:
        super().__init__(constraint)
        self.diag = _Diag(constraint)


class _SesionQueChoca(SesionFalsa):
    def __init__(self, constraint: str) -> None:
        super().__init__(decision=_decision())
        self._constraint = constraint

    def commit(self) -> None:
        from sqlalchemy.exc import IntegrityError

        raise IntegrityError("INSERT", {}, _OrigError(self._constraint))


def test_si_el_unique_decide_se_responde_409() -> None:
    """Dos POST simultáneos que llegaron a escribir: la base decide."""
    from apps.api.routers.review import UNICO_VEREDICTO

    app = create_app()
    sesion = _SesionQueChoca(UNICO_VEREDICTO)
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert r.status_code == 409
    assert sesion.rollbacks == 1


def test_otra_violacion_de_integridad_no_se_disfraza_de_409() -> None:
    """Un CHECK o una FK rotos son un fallo real, no un «ya estaba revisada»."""
    from sqlalchemy.exc import IntegrityError

    app = create_app()
    app.dependency_overrides[get_session] = lambda: _SesionQueChoca(
        "ck_classification_decisions_revision_dice_que_revisa"
    )

    with TestClient(app) as c, pytest.raises(IntegrityError):
        c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})


# ── Un caso por ficha, no uno por vez que se clasificó (Persona 1, 23-sep) ──


def test_la_bandeja_no_repite_el_mismo_caso_por_cada_clasificacion() -> None:
    """Clasificar dos veces el mismo producto no son dos casos que revisar.

    La bandeja llegó a tener el mismo producto DIEZ veces —una por cada
    corrida de prueba— mientras los casos reales esperaban debajo. Quien revisa
    perdería la tarde en uno solo, y su veredicto describiría una decisión que
    el motor ya no toma.
    """
    sesion = SesionFalsa(decision=_decision())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion
    with TestClient(app) as c:
        c.get("/review")

    sql = sesion.sql_bandeja[0]
    assert "max(" in sql.lower(), "no se toma la decisión más reciente"
    assert "product_dna_id" in sql, "no se agrupa por ficha"


def test_una_decision_sin_ficha_no_se_pierde() -> None:
    """Sin `product_dna_id` no hay por qué agrupar, y descartarla sería perder
    un caso en silencio."""
    sesion = SesionFalsa(decision=_decision())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion
    with TestClient(app) as c:
        c.get("/review")

    assert "IS NULL" in sesion.sql_bandeja[0].upper()


# ── El NICO es otro nivel, y antes se perdía (César, 5-oct) ─────────────────


def _revision(cuerpo: dict[str, Any], **kw: Any) -> tuple[SesionFalsa, Any]:
    """Manda un veredicto y devuelve la sesión y la respuesta."""
    app = create_app()
    sesion = SesionFalsa(decision=kw.pop("decision", None) or _decision(), **kw)
    app.dependency_overrides[get_session] = lambda: sesion
    with TestClient(app) as c:
        return sesion, c.post(f"/review/{DECISION_ID}", json=cuerpo)


def test_el_nico_del_veredicto_se_guarda() -> None:
    """Sin esto se guardaba la fracción y se tiraba la mitad de lo que dijo.

    En el dictamen del 5-oct César dio NICO en casi todos los casos. El
    endpoint no tenía dónde ponerlo: Pydantic descarta los campos que no
    declara, así que el `02` del cable se habría perdido en silencio, con la
    pantalla diciendo «guardado» y la respuesta confirmando sólo la fracción.
    """
    sesion, r = _revision(
        {
            "veredicto": "CORRIGE",
            "reviewer": "cesar",
            "fraction_code": "73121005",
            "nico_code": "02",
        },
        nicos_vigentes=("01", "02"),
    )

    assert r.status_code == 201
    assert sesion.agregadas[0].nico_code == "02"
    # Y se devuelve: un campo que se acepta y no se confirma es indistinguible
    # de uno que se ignora.
    assert r.json()["nico_code"] == "02"


def test_un_nico_que_no_existe_en_la_fraccion_se_rechaza() -> None:
    """Mismo criterio que la fracción: la persona manda en el criterio, no en
    qué códigos existen."""
    sesion, r = _revision(
        {
            "veredicto": "CORRIGE",
            "reviewer": "cesar",
            "fraction_code": "73121005",
            "nico_code": "07",
        },
        nicos_vigentes=("01", "02"),
    )

    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert "07" in detalle
    # Enseña los que hay, no elige uno.
    assert "01, 02" in detalle
    assert sesion.agregadas == []


def test_sin_nico_cargados_el_veredicto_no_se_rechaza() -> None:
    """`()` es un hueco NUESTRO, no un error del revisor.

    Misma disciplina que `hay_tarifa` para la fracción: que el catálogo no
    tenga los NICO de esa fracción no demuestra que el `02` no exista. Sin esta
    condición el guardarraíl rechazaría todos los veredictos con NICO en
    cualquier entorno donde los NICO no estén cargados.
    """
    sesion, r = _revision(
        {
            "veredicto": "CORRIGE",
            "reviewer": "cesar",
            "fraction_code": "73121005",
            "nico_code": "02",
        },
        nicos_vigentes=(),
    )

    assert r.status_code == 201
    assert sesion.agregadas[0].nico_code == "02"


def test_un_nico_sin_fraccion_no_identifica_nada() -> None:
    """El mismo «02» existe en miles de fracciones."""
    sin_fraccion = _decision()
    sin_fraccion.fraction_code = None

    sesion, r = _revision(
        {"veredicto": "CONFIRMA", "reviewer": "cesar", "nico_code": "02"},
        decision=sin_fraccion,
    )

    assert r.status_code == 422
    assert sesion.agregadas == []


def test_un_nico_de_un_digito_se_rechaza() -> None:
    """`2` no es `02`.

    No empataría con ningún código del catálogo, y el rechazo habría parecido
    un NICO inexistente en vez de un dígito que falta — que es un error
    distinto y se arregla de otra forma.
    """
    _, r = _revision(
        {
            "veredicto": "CORRIGE",
            "reviewer": "cesar",
            "fraction_code": "73121005",
            "nico_code": "2",
        },
        nicos_vigentes=("01", "02"),
    )

    assert r.status_code == 422


def test_el_razonamiento_no_pega_el_nico_a_la_fraccion() -> None:
    """Son dos niveles. Escribirlos juntos es el error que César advirtió."""
    sesion, _ = _revision(
        {
            "veredicto": "CORRIGE",
            "reviewer": "cesar",
            "fraction_code": "73121005",
            "nico_code": "02",
        },
        nicos_vigentes=("02",),
    )

    razon = sesion.agregadas[0].reasoning
    assert "NICO 02" in razon
    assert "7312100502" not in razon


# ── «Falta información» es un veredicto, no una ausencia ────────────────────


def test_falta_informacion_no_hereda_la_fraccion_del_motor() -> None:
    """Heredarla convertiría un «no se puede determinar» en una confirmación.

    La original propone 84714902. Si el veredicto la copiara, la fila humana
    diría que esa fracción es correcta —firmada, `HUMAN_VALIDATED`, contada en
    la métrica— cuando la persona dijo exactamente lo contrario.
    """
    sesion, r = _revision(
        {
            "veredicto": "FALTA_INFORMACION",
            "reviewer": "cesar",
            "nota": "Falta el diámetro exterior: sin él no se separan 730511 y 730519.",
        }
    )

    assert r.status_code == 201
    fila = sesion.agregadas[0]
    assert fila.fraction_code is None
    # Pide un DATO, no otra opinión: `HUMAN_REVIEW_REQUIRED` mandaría el caso a
    # una bandeja donde el siguiente revisor llegaría a lo mismo.
    assert fila.status == "INSUFFICIENT_INFORMATION"
    assert fila.data_origin == "HUMAN_VALIDATED"


def test_falta_informacion_con_fraccion_se_contradice() -> None:
    sesion, r = _revision(
        {
            "veredicto": "FALTA_INFORMACION",
            "reviewer": "cesar",
            "fraction_code": "73051999",
            "nota": "falta el espesor",
        }
    )

    assert r.status_code == 422
    assert sesion.agregadas == []


def test_falta_informacion_exige_decir_que_dato_falta() -> None:
    """Sin eso el veredicto cierra el caso sin desatascarlo.

    Es la diferencia entre «pidan el diámetro exterior» —que un agente aduanal
    puede convertir en un correo al importador— y «no sé», que deja el caso
    igual de parado pero ya sin bandeja donde aparecer.
    """
    sesion, r = _revision({"veredicto": "FALTA_INFORMACION", "reviewer": "cesar"})

    assert r.status_code == 422
    assert sesion.agregadas == []

    sesion, r = _revision({"veredicto": "FALTA_INFORMACION", "reviewer": "cesar", "nota": "   "})
    assert r.status_code == 422
    assert sesion.agregadas == []


def test_falta_informacion_saca_el_caso_de_la_bandeja() -> None:
    """Lo que falta es un dato de la mercancía, no una opinión más."""
    original = _decision()
    _, r = _revision(
        {
            "veredicto": "FALTA_INFORMACION",
            "reviewer": "cesar",
            "nota": "Falta la construcción del cable (6x19 o 6x36).",
        },
        decision=original,
    )

    assert r.status_code == 201
    assert original.requires_human_review is False


def test_el_razonamiento_dice_que_el_dato_hay_que_pedirlo() -> None:
    sesion, _ = _revision(
        {
            "veredicto": "FALTA_INFORMACION",
            "reviewer": "cesar",
            "nota": "Falta el proceso de soldadura.",
        }
    )

    razon = sesion.agregadas[0].reasoning
    assert "84714902" in razon
    assert "pedirlo" in razon
    assert "Falta el proceso de soldadura." in razon
