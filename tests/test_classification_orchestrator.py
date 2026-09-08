"""Tests del Classification Orchestrator.

Prueban lo que ningún motor por separado puede garantizar: que la decisión que
sale de aquí sea DEFENDIBLE, no sólo que exista. Un código que el contrato de
evidencia rechazó no debe salir por la puerta, por muy bien que lo haya
resuelto el RGI.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from core.classification import classify_product, with_money_impact
from core.evidence import DocumentRef, LegalRef
from core.product_dna import ExtractedAttribute, ProductDnaDraft
from core.rgi_engine import RGIStatus, TariffCandidate
from core.taxation import Money, TaxRates

pytestmark = pytest.mark.unit

OPERACION = date(2024, 3, 15)

LIGIE = DocumentRef(
    document="LIGIE 2022 (DOF)",
    article="Capítulo 84",
    url="https://www.snice.gob.mx/cs/avi/snice/ligie.info22.html",
    published_at=date(2022, 7, 7),
    content_hash="sha256:aaaa1111bbbb2222",
)
NORMAS = [
    LegalRef(
        document_ref=LIGIE,
        valid_from=date(2022, 7, 7),
        content_hash="sha256:aaaa1111bbbb2222",
        data_origin="OFFICIAL",
    )
]

PARTIDA = TariffCandidate(
    code="8471",
    text="Máquinas automáticas para tratamiento o procesamiento de datos",
    level="HEADING",
    source_id="src-ligie-84",
    specificity=8,
)
SUB = TariffCandidate(
    code="847130",
    text="Portátiles de peso inferior a 10 kg",
    level="SUBHEADING",
    source_id="src-8471",
    specificity=5,
)
FRACCION = TariffCandidate(
    code="84713001",
    text="Unidades de proceso digitales portátiles",
    level="FRACTION",
    source_id="src-847130",
    specificity=5,
)


class Catalogo:
    def __init__(self, h=None, s=None, f=None) -> None:  # type: ignore[no-untyped-def]
        self._h, self._s, self._f = h or [PARTIDA], s or [SUB], f or [FRACCION]

    def headings(self, *, on_date, terms):  # type: ignore[no-untyped-def]
        return list(self._h)

    def subheadings(self, *, on_date, heading):  # type: ignore[no-untyped-def]
        return [x for x in self._s if x.code.startswith(heading)]

    def fractions(self, *, on_date, subheading):  # type: ignore[no-untyped-def]
        return [x for x in self._f if x.code.startswith(subheading)]


class Notas:
    def __init__(self, excl=None) -> None:  # type: ignore[no-untyped-def]
        self._excl = excl or {}

    def notes_for(self, *, on_date, chapter):  # type: ignore[no-untyped-def]
        return []

    def excludes(self, *, on_date, heading, terms):  # type: ignore[no-untyped-def]
        return self._excl.get(heading)


def dna(*attrs: ExtractedAttribute, resumen: str = "Computadora portátil de 14 pulgadas"):
    return ProductDnaDraft(
        attributes=attrs
        or (
            ExtractedAttribute(
                name="function",
                value="tratamiento de datos",
                status="OBSERVED",
                confidence=Decimal("0.99"),
                locator="p.1",
            ),
            ExtractedAttribute(
                name="weight_kg",
                value="1.4",
                status="EXTRACTED",
                confidence=Decimal("0.95"),
                locator="p.2",
            ),
        ),
        summary=resumen,
    )


def clasificar(**kw):  # type: ignore[no-untyped-def]
    # `dna` se saca ANTES de mezclar: si no, acaba en `base` y en `kw`, y
    # classify_product lo recibe dos veces.
    entrada = kw.pop("dna", None) or dna()
    base = {
        "operation_date": OPERACION,
        "catalog": Catalogo(),
        "notes": Notas(),
        "search_terms": ("máquina automática para tratamiento de datos",),
        "legal_refs": NORMAS,
    }
    base.update(kw)
    return classify_product(entrada, **base)


# ── El camino completo ───────────────────────────────────────────────────────


def test_las_cuatro_piezas_producen_una_decision_defendible() -> None:
    """El vertical slice del §42, de punta a punta."""
    r = clasificar()

    assert r.status is RGIStatus.RESOLVED
    assert r.code == "84713001"
    assert r.blocked_by is None
    assert r.requires_human_review is False


def test_la_traza_del_rgi_llega_entera_al_resultado() -> None:
    """Sin la traza no hay nada que auditar (§18)."""
    r = clasificar()

    assert [p.rule_id for p in r.trace.steps] == ["RGI-1", "RGI-6"]
    assert r.to_decision_fields()["rgi_path"] == ["RGI-1", "RGI-6"]


def test_cada_pieza_de_evidencia_lleva_su_tipo() -> None:
    """La norma fundamenta; la regla y el modelo, no.

    Meterlas en el mismo saco daría la misma autoridad a "lo dice la LIGIE" y
    a "lo dedujo un modelo".
    """
    r = clasificar()

    tipos = {e.kind.value for e in r.evidences}
    assert "LEGAL_SOURCE" in tipos
    assert "DETERMINISTIC" in tipos
    assert sum(1 for e in r.evidences if e.is_legal_basis) >= 1


def test_un_atributo_inferido_produce_evidencia_de_modelo() -> None:
    """Lo deducido se declara como deducido, con su prompt y su versión."""
    r = clasificar(
        dna=dna(
            ExtractedAttribute(name="function", value="datos", status="OBSERVED", locator="p.1"),
            ExtractedAttribute(
                name="chassis_material",
                value="aluminio",
                status="INFERRED",
                confidence=Decimal("0.58"),
            ),
        )
    )

    modelo = [e for e in r.evidences if e.kind.value == "MODEL_OUTPUT"]
    assert modelo, "un atributo INFERRED debe dejar evidencia de modelo"
    assert modelo[0].prompt_version
    assert "chassis_material" in modelo[0].summary


# ── Lo que el orquestador debe IMPEDIR ───────────────────────────────────────


def test_sin_norma_recuperada_el_codigo_no_sale() -> None:
    """§8.1: sin fuente recuperada no hay afirmación jurídica.

    Éste es el test que justifica que exista el orquestador. El RGI resuelve
    perfectamente —la traza lo demuestra— pero el resultado NO es defendible, y
    devolver la fracción sería declarar algo que no se sostiene ante una
    auditoría.
    """
    r = clasificar(legal_refs=[])

    assert r.trace.resolved_code == "84713001", "el RGI sí resolvió"
    assert r.code is None, "pero no es defendible, así que no sale"
    assert r.blocked_by is not None
    assert r.requires_human_review is True


def test_una_norma_fuera_de_vigencia_bloquea_el_resultado() -> None:
    """§14: no se clasifica una operación de 2024 con una norma de 2026."""
    futura = DocumentRef(document="RGCE 2026", published_at=date(2026, 1, 15))

    r = clasificar(
        legal_refs=[
            LegalRef(
                document_ref=futura,
                valid_from=date(2026, 1, 15),
                content_hash="sha256:ffff",
                data_origin="OFFICIAL",
            )
        ]
    )

    assert r.code is None
    assert r.blocked_by is not None
    assert "2024-03-15" in r.blocked_by


def test_sin_terminos_no_clasifica_y_dice_que_falta() -> None:
    """Un INSUFFICIENT_INFORMATION con su razón es un resultado, no un error."""
    r = clasificar(search_terms=())

    assert r.status is RGIStatus.INSUFFICIENT_INFORMATION
    assert r.code is None
    assert r.trace.missing_information


def test_una_nota_de_exclusion_impide_la_clasificacion() -> None:
    r = clasificar(notes=Notas({"8471": "Este capítulo no comprende las máquinas de 84.70."}))

    assert r.status is RGIStatus.INSUFFICIENT_INFORMATION
    assert r.code is None


# ── Las diez preguntas del §49 ───────────────────────────────────────────────


def test_el_dossier_contesta_salvo_el_dinero() -> None:
    """Sin pedimento contra el que comparar, el impacto no se puede responder —
    y se declara, no se inventa (§36)."""
    r = clasificar()

    assert r.dossier is not None
    assert "money_impact" in r.dossier.unanswered
    assert r.dossier.which_source
    assert r.dossier.data_used["function"] == "tratamiento de datos"


def test_con_el_impacto_el_dossier_queda_completo() -> None:
    """La novena pregunta del §49, respondida."""
    r = with_money_impact(
        clasificar(),
        transaction_value=Money(amount=Decimal("100000.00"), currency="MXN"),
        declared_rates=TaxRates(igi_rate=Decimal("0.05"), iva_rate=Decimal("0.16")),
        expected_rates=TaxRates(igi_rate=Decimal("0.15"), iva_rate=Decimal("0.16")),
    )

    assert r.impact is not None
    assert r.impact.direction == "OMISION"
    assert r.impact.difference.amount == Decimal("11600.00")
    assert r.dossier is not None
    assert "money_impact" not in r.dossier.unanswered
    assert r.dossier.is_complete, f"sin responder: {r.dossier.unanswered}"


def test_el_impacto_se_marca_como_simulado() -> None:
    """§33: un número sin esa marca se lee como real."""
    r = with_money_impact(
        clasificar(),
        transaction_value=Money(amount=Decimal("100000.00"), currency="MXN"),
        declared_rates=TaxRates(igi_rate=Decimal("0.05")),
        expected_rates=TaxRates(igi_rate=Decimal("0.15")),
    )

    assert r.impact is not None
    assert "(simulado)" in r.impact.as_money_impact()


# ── Frontera con la persistencia ─────────────────────────────────────────────


def test_el_mapeo_a_la_tabla_no_importa_la_capa_de_datos() -> None:
    """§29: `core/` devuelve un dict plano; quien escribe la fila ensambla."""
    campos = clasificar().to_decision_fields()

    assert campos["fraction_code"] == "84713001"
    assert campos["status"] == "RESOLVED"
    assert campos["engine_version"]
    assert campos["requires_human_review"] is False
    assert "evidence_id" not in campos, "el id no existe cuando el motor termina"


def test_un_resultado_bloqueado_no_persiste_la_fraccion() -> None:
    """Lo que no es defendible tampoco llega a la base."""
    campos = clasificar(legal_refs=[]).to_decision_fields()

    assert campos["fraction_code"] is None
    assert campos["requires_human_review"] is True


def test_el_relato_menciona_lo_que_importa() -> None:
    """Para que un LLM lo narre — nunca para que lo recalcule (§22)."""
    texto = clasificar().explain()

    assert "84713001" in texto
    assert "RGI-1" in texto
