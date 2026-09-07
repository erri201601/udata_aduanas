"""Tests del Evidence Contract.

El orden importa: primero lo que el contrato debe IMPEDIR, después lo que debe
permitir. Un contrato de evidencia que sólo prueba el camino feliz no sirve
para nada — su valor entero está en lo que rechaza.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from core.evidence import builder, contract, questions
from core.evidence.errors import (
    EvidenceOutOfValidityError,
    IncompleteEvidenceError,
    NotLegalBasisError,
    UnsupportedClaimError,
)
from core.evidence.kinds import EvidenceKind
from core.evidence.types import DocumentRef

pytestmark = pytest.mark.unit

OPERACION = date(2024, 3, 15)

LIGIE = DocumentRef(
    document="LIGIE 2022 (DOF)",
    article="Capítulo 84",
    url="https://www.snice.gob.mx/cs/avi/snice/ligie.info22.html",
    published_at=date(2022, 7, 7),
    content_hash="sha256:aaaa1111bbbb2222",
)


def norma_vigente(**cambios: object):  # type: ignore[no-untyped-def]
    """Una fuente jurídica válida, para no repetirla en cada test."""
    kwargs = {
        "summary": "La partida 84.71 comprende máquinas automáticas para tratamiento de datos.",
        "source_id": uuid.uuid4(),
        "document_ref": LIGIE,
        "valid_from": date(2022, 7, 7),
        "content_hash": "sha256:aaaa1111bbbb2222",
    }
    kwargs.update(cambios)
    return builder.legal_source(**kwargs)  # type: ignore[arg-type]


# ── Lo que el contrato debe IMPEDIR ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("source_id", None),
        ("document_ref", None),
        ("valid_from", None),
        ("content_hash", None),
        ("content_hash", "   "),  # una cadena en blanco no documenta nada
    ],
)
def test_fuente_juridica_incompleta_no_se_construye(campo: str, valor: object) -> None:
    """Sin cualquiera de sus campos obligatorios, la evidencia legal no existe.

    El error tiene que salir al CONSTRUIR. Si sólo fallara al insertar, el
    traceback apuntaría a la capa de base de datos y no a la línea que olvidó
    el dato.
    """
    with pytest.raises(IncompleteEvidenceError) as exc:
        norma_vigente(**{campo: valor})

    assert exc.value.kind is EvidenceKind.LEGAL_SOURCE
    assert campo in exc.value.missing


@pytest.mark.parametrize("campo", ["model_provider", "model_name", "prompt_id", "prompt_version"])
def test_salida_de_modelo_sin_trazabilidad_no_se_construye(campo: str) -> None:
    """Una salida de modelo irreproducible no es evidencia.

    Sin prompt_version no se puede saber con qué instrucciones se generó, y
    entonces no hay forma de reproducirla ni de auditarla.
    """
    kwargs: dict[str, object] = {
        "summary": "El producto es una computadora portátil.",
        "model_provider": "anthropic",
        "model_name": "claude-opus-5",
        "prompt_id": "product_dna.extract",
        "prompt_version": "0.1",
    }
    kwargs[campo] = None

    with pytest.raises(IncompleteEvidenceError) as exc:
        builder.model_output(**kwargs)  # type: ignore[arg-type]

    assert campo in exc.value.missing


def test_validacion_humana_anonima_no_se_construye() -> None:
    """Una validación sin autor no se puede repreguntar."""
    with pytest.raises(IncompleteEvidenceError):
        builder.human(summary="Confirmado", reviewer=None, reviewed_at=datetime.now(UTC))  # type: ignore[arg-type]


def test_comparable_no_es_fundamento_juridico() -> None:
    """Un precedente de CBP CROSS no sostiene una clasificación mexicana.

    Es el error más peligroso del sistema porque parece fundamento: cita un
    documento oficial, de una autoridad aduanera, sobre el mismo producto. Pero
    una resolución estadounidense no obliga en México y el §11 prohíbe
    convertir HTS10 directamente a TIGIE.
    """
    caso = builder.comparable(
        summary="CBP clasificó un producto equivalente en 8471.30.0100.",
        jurisdiction="US",
        case_ref="NY N123456",
        document_ref=DocumentRef(document="CBP CROSS NY N123456", url="https://rulings.cbp.gov/"),
    )

    with pytest.raises(NotLegalBasisError) as exc:
        contract.assert_legal_basis([caso], claim="clasificación 8471.30.01")

    assert exc.value.kind is EvidenceKind.COMPARABLE


def test_salida_de_modelo_sola_no_es_fundamento_juridico() -> None:
    """ "Lo dedujo el modelo" no es fundamento (§8.1)."""
    salida = builder.model_output(
        summary="Corresponde a la partida 84.71.",
        model_provider="anthropic",
        model_name="claude-opus-5",
        prompt_id="classification.support",
        prompt_version="0.1",
    )

    with pytest.raises(NotLegalBasisError):
        contract.assert_legal_basis([salida], claim="clasificación 8471.30.01")


def test_afirmacion_sin_ninguna_evidencia_se_rechaza() -> None:
    """Sin fuente recuperada no hay afirmación jurídica (§8.1)."""
    with pytest.raises(UnsupportedClaimError):
        contract.assert_legal_basis([], claim="la mercancía está exenta de IGI")


def test_norma_posterior_a_la_operacion_se_rechaza() -> None:
    """No se juzga una operación de 2024 con una regla que entró en 2026 (§14).

    Es el fallo más caro de todos porque no da error: produce un hallazgo con
    toda la apariencia de estar fundado, y nadie cuestiona un hallazgo fundado.
    """
    rgce_2026 = norma_vigente(
        summary="Regla 3.7.35 de las RGCE 2026.",
        document_ref=DocumentRef(document="RGCE 2026", published_at=date(2026, 1, 15)),
        valid_from=date(2026, 1, 15),
    )

    with pytest.raises(EvidenceOutOfValidityError) as exc:
        contract.assert_temporal_validity([rgce_2026], operation_date=OPERACION)

    assert exc.value.operation_date == OPERACION
    assert exc.value.valid_from == date(2026, 1, 15)


def test_norma_derogada_antes_de_la_operacion_se_rechaza() -> None:
    """Tampoco vale una norma que ya había dejado de regir."""
    derogada = norma_vigente(valid_from=date(2020, 1, 1), valid_to=date(2022, 6, 30))

    with pytest.raises(EvidenceOutOfValidityError):
        contract.assert_temporal_validity([derogada], operation_date=OPERACION)


# ── Lo que el contrato debe PERMITIR ─────────────────────────────────────────


def test_norma_vigente_sin_fecha_de_fin_cubre_la_operacion() -> None:
    """`valid_to = None` significa vigente, no "sin datos" (§14)."""
    norma = norma_vigente()

    assert norma.covers(OPERACION)
    assert norma.is_legal_basis
    contract.assert_defensible([norma], claim="clasificación", operation_date=OPERACION)


def test_comparable_acompanando_a_una_norma_si_pasa() -> None:
    """El comparable no estorba: aporta interpretación mientras haya fundamento."""
    caso = builder.comparable(
        summary="CBP llegó a la misma partida en un caso equivalente.",
        jurisdiction="US",
        case_ref="NY N123456",
        document_ref=DocumentRef(document="CBP CROSS NY N123456"),
    )

    contract.assert_defensible(
        [norma_vigente(), caso], claim="clasificación", operation_date=OPERACION
    )


def test_evidencias_sin_vigencia_no_restringen_la_fecha() -> None:
    """Una salida de modelo no tiene vigencia y no debe bloquear nada."""
    salida = builder.model_output(
        summary="Es una computadora portátil.",
        model_provider="anthropic",
        model_name="claude-opus-5",
        prompt_id="product_dna.extract",
        prompt_version="0.1",
    )

    contract.assert_temporal_validity([norma_vigente(), salida], operation_date=OPERACION)


# ── Las diez preguntas del §49 ───────────────────────────────────────────────


def test_una_decision_completa_contesta_las_diez_preguntas() -> None:
    """La prueba de fuego: §49 dice que si no las contesta, no está terminado."""
    dossier = questions.answer_all(
        what="La fracción declarada (8471.30.99) no coincide con la esperada (8471.30.01).",
        evidences=[
            norma_vigente(),
            builder.deterministic(
                summary="RGI 1: la partida se determina por los textos de partida y las notas.",
                rule_id="RGI-1",
                engine_version="0.1.0",
                inputs={"descripcion": "computadora portátil", "peso_kg": "1.4"},
            ),
            builder.model_output(
                summary="La ficha técnica describe una máquina automática de tratamiento de datos.",
                model_provider="anthropic",
                model_name="claude-opus-5",
                prompt_id="classification.support",
                prompt_version="0.1",
                confidence=Decimal("0.9200"),
            ),
        ],
        operation_date=OPERACION,
        money_impact="MXN 12,450.00 (simulado)",
        requires_human_review=False,
    )

    assert dossier.is_complete, f"sin responder: {dossier.unanswered}"
    assert "8471.30.99" in dossier.what
    assert "RGI-1" in dossier.which_rule
    assert any("LIGIE 2022" in f for f in dossier.which_source)
    assert any("aaaa1111bbbb" in v for v in dossier.source_version)
    assert any("2022-07-07" in v for v in dossier.validity)
    assert dossier.data_used["descripcion"] == "computadora portátil"
    assert dossier.confidence == Decimal("0.9200")
    assert dossier.money_impact.startswith("MXN")
    assert dossier.requires_human_review is False


def test_lo_que_falta_se_declara_en_vez_de_inventarse() -> None:
    """§36: no se rellenan huecos. Lo que no se sabe se nombra.

    Este test protege la propiedad más importante del sistema. Un dossier que
    devolviera cadenas vacías o valores plausibles para lo que no sabe sería
    peor que inútil: sería engañoso.
    """
    dossier = questions.answer_all(
        what="Posible sobrepago de IGI.",
        evidences=[norma_vigente()],
        operation_date=OPERACION,
    )

    assert not dossier.is_complete
    assert "money_impact" in dossier.unanswered
    assert "confidence" in dossier.unanswered
    assert "data_used" in dossier.unanswered
    assert dossier.money_impact == questions.UNKNOWN
    assert dossier.confidence is None


def test_la_confianza_del_conjunto_es_la_del_eslabon_mas_debil() -> None:
    """Una cadena de evidencia no es más fuerte que su pieza menos confiable."""
    dossier = questions.answer_all(
        what="Clasificación propuesta.",
        evidences=[
            norma_vigente(),
            builder.model_output(
                summary="Interpretación de la ficha.",
                model_provider="anthropic",
                model_name="claude-opus-5",
                prompt_id="p",
                prompt_version="0.1",
                confidence=Decimal("0.9500"),
            ),
            builder.human(
                summary="Revisado por el agente aduanal.",
                reviewer="ulises@udata.com.mx",
                reviewed_at=datetime(2024, 3, 20, tzinfo=UTC),
                confidence=Decimal("0.6000"),
            ),
        ],
        operation_date=OPERACION,
    )

    assert dossier.confidence == Decimal("0.6000")


def test_la_revision_humana_se_exige_por_defecto() -> None:
    """El sistema falla hacia la cautela, igual que el default de la base."""
    dossier = questions.answer_all(
        what="Hallazgo.", evidences=[norma_vigente()], operation_date=OPERACION
    )

    assert dossier.requires_human_review is True


def test_una_norma_fuera_de_vigencia_se_marca_en_el_dossier() -> None:
    """Si se cuela una norma que no aplica, el dossier lo dice a la vista.

    `assert_temporal_validity` es la barrera; esto es la segunda línea, para
    que un dossier ensamblado sin pasar por ella no engañe a quien lo lea.
    """
    dossier = questions.answer_all(
        what="Hallazgo.",
        evidences=[norma_vigente(valid_from=date(2026, 1, 1))],
        operation_date=OPERACION,
    )

    assert any("NO CUBRE LA OPERACIÓN" in v for v in dossier.validity)


# ── Frontera con la capa de persistencia ─────────────────────────────────────


def test_el_mapeo_a_la_tabla_no_importa_la_capa_de_datos() -> None:
    """§29: `core/` no depende de la persistencia. Devuelve un dict plano."""
    campos = norma_vigente().to_record_fields()

    assert campos["evidence_kind"] == "LEGAL_SOURCE"
    assert campos["created_by"] == "engine"
    assert campos["document_refs"][0]["document"] == "LIGIE 2022 (DOF)"
    assert "sha256:aaaa1111bbbb2222" in campos["content_hashes"]
    assert len(campos["source_ids"]) == 1


def test_el_origen_humano_se_distingue_en_la_tabla() -> None:
    """`created_by` tiene que reflejar que lo validó una persona."""
    campos = builder.human(
        summary="Confirmado por el agente aduanal.",
        reviewer="brandon@udata.com.mx",
        reviewed_at=datetime(2024, 3, 20, tzinfo=UTC),
    ).to_record_fields()

    assert campos["created_by"] == "human"
    assert campos["evidence_kind"] == "HUMAN"


def test_la_evidencia_es_inmutable() -> None:
    """Una evidencia emitida no se edita: se emite otra.

    Si se pudiera mutar, el registro dejaría de ser un hecho histórico y el
    audit trail perdería su sentido.
    """
    norma = norma_vigente()

    with pytest.raises(Exception, match=r"frozen|immutable"):
        norma.summary = "otra cosa"  # type: ignore[misc]
