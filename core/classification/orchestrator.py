"""El orquestador: une los cuatro motores en una decisión defendible.

    Product DNA  →  RGI Engine  →  Evidence  →  Money Finder
      (P3)           (P1)          (P1)          (P1)

Es el eslabón que faltaba del §42. Cada motor sabe hacer una cosa y ninguno
conoce a los demás: el Product DNA no sabe de clasificación, el RGI no sabe de
evidencia, el Money Finder no sabe de fracciones. Esa ignorancia mutua es
deliberada, y este módulo es el único que los ve a todos.

POR QUÉ NO BASTA CON ENCADENARLOS

Entre paso y paso hay decisiones que ningún motor puede tomar solo:

- Que el RGI resuelva un código NO significa que sea defendible. El contrato de
  evidencia puede rechazarlo por falta de fundamento o por vigencia. Si eso
  pasa, el código no se devuelve — devolverlo sería declarar una fracción que
  no se puede sostener ante una auditoría.
- Un producto con atributos críticos ausentes no debería llegar al RGI: se
  detiene antes y se pide la información, en vez de clasificar sobre huecos.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from core.classification.nico_por_medida import medidas_de, nico_por_medida
from core.classification.result import ClassificationOutcome
from core.evidence import EvidenceError, builder, contract, questions
from core.product_dna import PROMPT_ID, PROMPT_VERSION
from core.rgi_engine import ClassificationContext, ProductFact, RGIStatus, classify
from core.taxation import compute_divergence, compute_taxes

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date
    from decimal import Decimal

    from core.evidence import Evidence, LegalRef
    from core.product_dna import ProductDnaDraft
    from core.rgi_engine import ClassificationTrace, Interpreter, LegalNotes, TariffCatalog
    from core.taxation import Money, TaxRates


class NicoCatalog(Protocol):
    """Los NICO vigentes de una fracción. Lo implementa
    `database/repositories/tariff.py::TariffCatalogRepository`.

    `None` = la fracción no está vigente; `()` = no tiene NICO cargados."""

    def nicos(self, *, on_date: date, fraction_code: str) -> tuple[str, ...] | None: ...


@runtime_checkable
class NicoTexts(Protocol):
    """Los NICO vigentes con su texto, para la regla de medidas (ADR 0016).
    Mismas tres respuestas que `NicoCatalog.nicos`."""

    def nicos_con_texto(
        self, *, on_date: date, fraction_code: str
    ) -> tuple[tuple[str, str], ...] | None: ...


def nico_de(
    nicos: NicoCatalog,
    *,
    on_date: date,
    fraction_code: str,
    medidas: Mapping[str, Decimal] | None = None,
) -> tuple[str | None, str]:
    """El NICO de una fracción ya decidida, y por qué (§19).

    Dos reglas, cada una medida sola:

    1. Un único NICO vigente en la LIGIE: no hay elección (ADR 0013). Medido el
       13-oct: 14 de 14 con los veredictos de César.
    2. Varios, distinguidos SÓLO por rangos de medidas que la ficha trae
       observadas (`nico_por_medida`, ADR 0016). Si algún NICO distingue por
       materia, uso o presentación, no se elige.

    Sin `medidas`, o con un catálogo sin textos, sólo se aplica la primera.
    """
    vigentes = nicos.nicos(on_date=on_date, fraction_code=fraction_code)
    if vigentes is None:
        return None, f"la fracción {fraction_code} no está vigente en el catálogo de NICO"
    if not vigentes:
        return None, f"la fracción {fraction_code} no tiene NICO cargados"
    if len(vigentes) == 1:
        return vigentes[0], f"único NICO vigente de la fracción {fraction_code} en la LIGIE"
    varios = (
        f"la fracción {fraction_code} tiene {len(vigentes)} NICO vigentes ({', '.join(vigentes)})"
    )
    if medidas is not None and isinstance(nicos, NicoTexts):
        textos = nicos.nicos_con_texto(on_date=on_date, fraction_code=fraction_code)
        if textos:
            elegido, motivo = nico_por_medida(textos, medidas)
            if elegido is not None:
                return elegido, f"{varios}; por medidas: {motivo}"
            return None, f"{varios}; no se elige: {motivo}"
    return None, (
        f"{varios}; elegir uno exige distinguir por materia, uso o "
        "presentación, y no se elige sin una regla que lo sostenga"
    )


def medidas_de_la_ficha(dna: ProductDnaDraft) -> dict[str, Decimal]:
    """Las medidas observadas o extraídas de la ficha. Lo inferido no cuenta."""
    return medidas_de([(a.name, a.value) for a in dna.solid()])


def classify_product(
    dna: ProductDnaDraft,
    *,
    operation_date: date,
    catalog: TariffCatalog,
    notes: LegalNotes,
    interpreter: Interpreter | None = None,
    search_terms: Sequence[str] = (),
    legal_refs: Sequence[LegalRef] = (),
    trade_flow: str = "IMPORT",
    exclusiones: Sequence[tuple[str, str]] = (),
    equivalencias: Sequence[tuple[str, str]] = (),
    nicos: NicoCatalog | None = None,
) -> ClassificationOutcome:
    """Clasifica un producto y devuelve la decisión con lo que la sostiene.

    `legal_refs` son las normas recuperadas que respaldan la clasificación,
    como `(document_ref, valid_from, content_hash)`. Sin al menos una, el
    resultado se marca no defendible: es la regla del §8.1 aplicada al
    conjunto, no a cada pieza.

    Nunca lanza por no poder clasificar. Un `INSUFFICIENT_INFORMATION` con su
    razón es un resultado legítimo, no un error.

    Con `nicos`, una fracción defendible baja también al NICO cuando la LIGIE
    sólo tiene uno (`nico_de`). Sin `nicos` no se intenta.
    """
    hechos = tuple(ProductFact(**a.to_fact_fields()) for a in dna.attributes)

    contexto = ClassificationContext(
        description=dna.summary or "",
        operation_date=operation_date,
        facts=hechos,
        trade_flow=trade_flow,
        search_terms=tuple(search_terms),
        exclusiones=tuple(exclusiones),
        equivalencias=tuple(equivalencias),
    )

    traza = classify(contexto, catalog=catalog, notes=notes, interpreter=interpreter)

    evidencias = _evidencias_de(traza, dna=dna, legal_refs=legal_refs)

    # El contrato juzga el CONJUNTO. Cada evidencia puede estar completa y aun
    # así faltar el fundamento, o citarse una norma que no regía ese día.
    bloqueo: str | None = None
    if traza.final_status is RGIStatus.RESOLVED:
        try:
            contract.assert_defensible(
                evidencias,
                claim=f"clasificación {traza.resolved_code}",
                operation_date=operation_date,
            )
        except EvidenceError as exc:
            bloqueo = str(exc)

    dossier = questions.answer_all(
        what=_que_se_detecto(traza),
        evidences=evidencias,
        operation_date=operation_date,
        confidence=traza.confidence,
        requires_human_review=traza.requires_human_review or bloqueo is not None,
        data_used=contexto.as_input_facts(),
    )

    nico: str | None = None
    motivo_nico: str | None = None
    if nicos is not None and bloqueo is None and traza.resolved_code:
        nico, motivo_nico = nico_de(
            nicos,
            on_date=operation_date,
            fraction_code=traza.resolved_code,
            medidas=medidas_de_la_ficha(dna),
        )

    return ClassificationOutcome(
        trace=traza,
        operation_date=operation_date,
        evidences=tuple(evidencias),
        dossier=dossier,
        blocked_by=bloqueo,
        facts_used=contexto.as_input_facts(),
        nico_code=nico,
        nico_reason=motivo_nico,
    )


def with_money_impact(
    outcome: ClassificationOutcome,
    *,
    transaction_value: Money,
    declared_rates: TaxRates,
    expected_rates: TaxRates,
    incrementables: Sequence[Money] = (),
    is_simulation: bool = True,
) -> ClassificationOutcome:
    """Añade el impacto económico de la divergencia.

    Va aparte de `classify_product` porque clasificar y cuantificar son cosas
    distintas: un producto se puede clasificar sin que exista un pedimento
    contra el que compararlo. Sólo cuando hay operación declarada tiene sentido
    preguntar cuánto dinero representa la diferencia.

    El dossier se rehace para que `money_impact` deje de ser UNKNOWN — es la
    novena pregunta del §49 y hasta aquí no se podía responder.
    """
    declarado = compute_taxes(
        transaction_value=transaction_value,
        rates=declared_rates,
        incrementables=incrementables,
        is_simulation=is_simulation,
    )
    esperado = compute_taxes(
        transaction_value=transaction_value,
        rates=expected_rates,
        incrementables=incrementables,
        is_simulation=is_simulation,
    )
    impacto = compute_divergence(declared=declarado, expected=esperado)

    dossier = questions.answer_all(
        what=_que_se_detecto(outcome.trace),
        evidences=outcome.evidences,
        operation_date=outcome.operation_date,
        confidence=outcome.confidence,
        money_impact=impacto.as_money_impact(),
        requires_human_review=outcome.requires_human_review,
        data_used=outcome.facts_used,
    )

    return outcome.model_copy(update={"impact": impacto, "dossier": dossier})


# ── Auxiliares ───────────────────────────────────────────────────────────────


#: Qué instrumentos pueden FUNDAMENTAR una clasificación arancelaria.
#:
#: `a_legal_refs` ya filtraba por PROCEDENCIA —lo sintético no fundamenta—
#: pero nadie filtraba por MATERIA, y son dos cosas distintas. El artículo 78
#: de la Ley Aduanera es OFICIAL, está vigente y su hash es verificable; y aun
#: así no sustenta una clasificación, porque habla de cómo determinar el valor
#: en aduana cuando no aplica el valor de transacción. Es derecho aplicable a
#: la operación, no a la nomenclatura.
#:
#: Una clasificación se funda en la nomenclatura: el texto de las partidas, las
#: Notas de Sección y de Capítulo y las Reglas Generales de Interpretación, que
#: viven en la LIGIE. La Ley Aduanera regula el procedimiento —valoración,
#: despacho, obligaciones— y no decide dónde clasifica una mercancía.
#:
#: Sin este filtro, el expediente de defensa citaba los artículos 64, 65, 67,
#: 71, 78, 79 y 80 —el capítulo de valor en aduana— diciendo «sustenta la
#: clasificación» (Persona 1, 22-sep-2026, ensayo de la demo). No era una cita
#: inventada: era una cita correcta de una norma que no venía al caso, que ante
#: un agente aduanal es peor, porque parece rigor y no lo es.
#:
#: Crecerá cuando haya con qué: los criterios de clasificación del Anexo 6 de
#: las RGCE y las resoluciones del Consejo son fundamento y hoy no están
#: cargados.
FUNDAMENTAN_CLASIFICACION: Final[frozenset[str]] = frozenset({"TARIFF"})


def fundamenta_clasificacion(kind: str | None) -> bool:
    """¿Un documento de este tipo puede sostener una clasificación?

    `None` es no: un documento sin tipo conocido no se presume fundamento.
    """
    return kind in FUNDAMENTAN_CLASIFICACION


def _evidencias_de(
    traza: ClassificationTrace,
    *,
    dna: ProductDnaDraft,
    legal_refs: Sequence[LegalRef],
) -> list[Evidence]:
    """Convierte la traza y el DNA en evidencia, cada pieza con su tipo.

    Aquí es donde importa la distinción de `EvidenceKind`: las reglas del RGI
    son DETERMINISTIC, la extracción del DNA es MODEL_OUTPUT, y las normas son
    LEGAL_SOURCE — el único fundamento jurídico. Meterlas todas en el mismo
    saco daría la misma autoridad a "lo dice la LIGIE" y a "lo dedujo un
    modelo".
    """
    evidencias: list[Evidence] = []

    # Las normas recuperadas: lo único que fundamenta.
    for norma in legal_refs:
        doc = norma.document_ref
        evidencias.append(
            builder.legal_source(
                summary=f"{doc.document}"
                + (f", {doc.article}" if doc.article else "")
                + " sustenta la clasificación.",
                source_id=uuid.uuid5(uuid.NAMESPACE_URL, doc.url or doc.document),
                document_ref=doc,
                valid_from=norma.valid_from,
                valid_to=norma.valid_to,
                content_hash=norma.content_hash,
                data_origin=norma.data_origin,
                # Sin esto la evidencia sabe QUÉ norma cita pero no CUÁL fila
                # es, y el Sentinel no puede contrastarla contra una reforma.
                legal_rule_ids=(norma.legal_rule_id,) if norma.legal_rule_id else (),
            )
        )

    # Cada regla evaluada, con su razonamiento.
    for paso in traza.steps:
        if not paso.reasoning_summary:
            continue
        evidencias.append(
            builder.deterministic(
                summary=paso.reasoning_summary,
                rule_id=paso.rule_id,
                engine_version=traza.engine_version,
                inputs=dict(paso.input_facts),
            )
        )

    # La extracción del Product DNA, sólo si hubo modelo de por medio.
    inferidos = [a for a in dna.attributes if a.status == "INFERRED"]
    if inferidos:
        evidencias.append(
            builder.model_output(
                summary=(
                    "Atributos deducidos por el extractor: " + ", ".join(a.name for a in inferidos)
                ),
                model_provider="anthropic",
                model_name="claude-sonnet-5",
                prompt_id=PROMPT_ID,
                prompt_version=PROMPT_VERSION,
                confidence=min((a.confidence for a in inferidos if a.confidence), default=None),
            )
        )

    return evidencias


def _que_se_detecto(traza: ClassificationTrace) -> str:
    """La primera respuesta del §49: ¿qué detectaste?"""
    if traza.final_status is RGIStatus.RESOLVED and traza.resolved_code:
        return f"Clasificación propuesta: fracción {traza.resolved_code}."
    if traza.final_status is RGIStatus.INSUFFICIENT_INFORMATION:
        falta = ", ".join(traza.missing_information) or "información del producto"
        return f"No se pudo clasificar: falta {falta}."
    return "La clasificación requiere revisión humana."
