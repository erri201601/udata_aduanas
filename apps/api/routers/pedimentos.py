"""Revisión de un pedimento completo: Espejo → Money Finder → Audit → Opportunity.

POR QUÉ ESTE ENDPOINT EXISTE

Los cuatro motores estaban construidos y probados pero ninguno llegaba al
producto. La única fila de `risk_findings` la había escrito el seed, y
`opportunity_findings` estaba vacía. Se podía enseñar que el sistema clasifica;
no que encuentra dinero (Persona 1, 2026-09-08).

EL PAÍS DE ORIGEN SE CONTRASTA CONTRA EL PROVEEDOR

No hace falta fuente externa: el documento ya dice de dónde es el proveedor, y
una partida cuyo país difiere del suyo merece una mirada. NO es un error —un
pedimento con orígenes mixtos es legítimo— y por eso viaja con
`origin_source = SUPPLIER`, que hace que el Espejo lo emita como revisión
humana con el motivo escrito, no como acusación (Persona 1, 21-sep).

Si la partida no está ligada a una factura no hay proveedor que consultar, y
entonces no se compara: la partida declara que el origen no se pudo contrastar
en vez de darse por limpia.

DE DÓNDE SALEN LAS TASAS

El IGI sale del catálogo, por fracción y por fecha de operación: es lo propio
de cada mercancía y es lo que hace la diferencia cuando la fracción declarada
no es la correcta.

El IVA, el DTA y el IEPS los pasa quien llama. No están codificados aquí a
propósito: serían fundamento jurídico inventado, y quedarían congelados el día
que cambien en el DOF. Cuando Persona 2 cargue la Ley del IVA y la Ley Federal
de Derechos como fuentes, esto las consultará y registrará su `source_id`.

Si falta cualquiera de las dos tasas de IGI —porque la fracción declarada no
existe en la tarifa cargada— la partida NO se cuantifica. El hallazgo se emite
igual, sin monto: es un riesgo de cumplimiento real aunque no se sepa cuánto
cuesta. Inventar un cero daría una cifra plausible y falsa.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from core.classification import classify_product
from core.review import LineInput, PedimentoReview, review_pedimento
from core.shadow import DeclaredItem, ExpectedItem
from core.shadow.types import ORIGEN_DEL_PROVEEDOR
from core.taxation import Money, TaxRates
from database.models import Invoice, InvoiceItem, Pedimento, PedimentoItem, Supplier
from database.repositories import save_review
from database.repositories.notes import LegalNotesRepository
from database.repositories.tariff import TariffCatalogRepository
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.db import SessionDep
from apps.api.dna import cargar_borrador, terminos

router = APIRouter(prefix="/pedimentos", tags=["pedimentos"])


class ReviewRequest(BaseModel):
    """Las tasas de la operación. Todas opcionales; sin ellas no hay monto."""

    iva_rate: Decimal | None = Field(
        default=None,
        description="Fracción, no porcentaje: 0.16, no 16. En región fronteriza 0.08.",
    )
    dta_rate: Decimal | None = Field(
        default=None, description="Derecho de Trámite Aduanero ad valorem. El 8 al millar es 0.008."
    )
    dta_fixed: Decimal | None = Field(
        default=None, description="Cuota fija de DTA, cuando el régimen la usa en vez de la tasa."
    )
    ieps_rate: Decimal | None = Field(default=None, description="Sólo en mercancías que lo causan.")


class ReviewResponse(BaseModel):
    """Lo que se encontró, y sobre todo lo que no se pudo comprobar."""

    review_id: uuid.UUID
    pedimento_id: uuid.UUID
    findings: int
    worst_severity: str | None = None

    is_complete: bool
    """`False` significa que algo quedó sin revisar. Un pedimento incompleto
    NO está limpio: está sin verificar."""

    unverifiable: list[str] = Field(default_factory=list)

    total_exposure: Decimal | None = None
    total_recoverable: Decimal | None = None
    currency: str | None = None
    mixed_currencies: bool = False

    opportunities: int = 0
    quantified_opportunities: int = 0

    is_simulation: bool = True
    """§33: mientras alguna entrada sea SYNTHETIC, esto es una simulación."""

    lines_without_expectation: int = 0
    """Partidas para las que no se pudo construir un espejo — sin producto
    ligado, o sin Product DNA. Son las que hacen `is_complete` falso."""

    summary: str


@router.post(
    "/{pedimento_id}/review",
    status_code=status.HTTP_201_CREATED,
    summary="Revisa el pedimento contra su espejo y persiste los hallazgos",
)
def revisar(
    pedimento_id: uuid.UUID, peticion: ReviewRequest, session: SessionDep
) -> ReviewResponse:
    """Corre los cuatro motores sobre el pedimento y guarda el resultado.

    Nunca devuelve 500 por no poder revisar una partida. Una partida sin
    espejo es un resultado legítimo —va a `unverifiable`— y la revisión se
    persiste igual: saber qué NO se revisó es justamente lo que este endpoint
    aporta sobre no tener nada.
    """
    pedimento = session.get(Pedimento, pedimento_id)
    if pedimento is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pedimento no encontrado")

    partidas = session.scalars(
        sa.select(PedimentoItem)
        .where(PedimentoItem.pedimento_id == pedimento_id)
        .order_by(PedimentoItem.line_number)
    ).all()
    if not partidas:
        raise HTTPException(status.HTTP_409_CONFLICT, "el pedimento no tiene partidas")

    catalogo = TariffCatalogRepository(session)
    notas = LegalNotesRepository(session)
    fecha = pedimento.operation_date

    lineas: list[LineInput] = []
    sin_espejo = 0

    for partida in partidas:
        esperada = _construir_espejo(session, partida, fecha, catalogo, notas)
        if esperada is None:
            sin_espejo += 1

        valor = _valor(partida)
        declaradas, esperadas = _tasas(
            catalogo,
            fecha,
            peticion,
            declarada=partida.declared_fraction_code,
            esperada=esperada.fraction_code if esperada else None,
        )

        lineas.append(
            LineInput(
                declared=_declarada(partida),
                expected=esperada,
                transaction_value=valor,
                declared_rates=declaradas,
                expected_rates=esperadas,
                # Lo derivado de un pedimento sintético es sintético (§10).
                is_simulation=pedimento.is_simulation or partida.data_origin == "SYNTHETIC",
            )
        )

    revision = review_pedimento(lineas)

    corrida = save_review(
        session,
        revision,
        pedimento_id=pedimento_id,
        item_ids={p.line_number: p.id for p in partidas},
        data_origin=pedimento.data_origin,
    )
    session.commit()

    return _respuesta(corrida.id, pedimento_id, revision, sin_espejo)


# ── Armado de cada partida ───────────────────────────────────────────────────


def _declarada(partida: PedimentoItem) -> DeclaredItem:
    """La partida tal como viene en el pedimento, sin interpretarla."""
    return DeclaredItem(
        line_number=partida.line_number,
        description=partida.description,
        fraction_code=partida.declared_fraction_code,
        nico_code=partida.declared_nico_code,
        country_of_origin=partida.country_of_origin,
        customs_value=partida.customs_value,
        customs_value_currency=partida.customs_value_currency,
        applied_nom_codes=tuple(partida.applied_nom_codes or ()),
        identifiers=dict(partida.identifiers or {}),
    )


def _pais_del_proveedor(session: SessionDep, partida: PedimentoItem) -> str | None:
    """País del proveedor de la factura de esta partida. `None` si no consta.

    `Pedimento` no guarda proveedor: se llega por la factura
    (`partida → invoice_item → invoice → supplier`). Sin ese enlace no hay
    contra qué contrastar, y se devuelve `None` en vez de suponer.
    """
    if partida.invoice_item_id is None:
        return None
    return session.scalar(
        sa.select(Supplier.country)
        .select_from(InvoiceItem)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .join(Supplier, Supplier.id == Invoice.supplier_id)
        .where(InvoiceItem.id == partida.invoice_item_id)
    )


def _construir_espejo(
    session: SessionDep,
    partida: PedimentoItem,
    fecha: date,
    catalogo: TariffCatalogRepository,
    notas: LegalNotesRepository,
) -> ExpectedItem | None:
    """Clasifica el producto de la partida SIN mirar lo declarado (§36).

    Devuelve `None` cuando no hay con qué: sin producto ligado o sin Product
    DNA no hay expectativa, y la partida se reporta como no verificable. Un
    `ExpectedItem` vacío la haría pasar por limpia.
    """
    pais_proveedor = _pais_del_proveedor(session, partida)

    if (
        partida.product_id is None
        or (borrador := cargar_borrador(session, partida.product_id)) is None
    ):
        # Sin producto ligado no se puede clasificar, pero el país SÍ se puede
        # contrastar. Se devuelve una expectativa que sólo habla de origen en
        # vez de dejar la partida sin mirar.
        if pais_proveedor is None:
            return None
        return ExpectedItem(
            line_number=partida.line_number,
            is_resolved=False,
            country_of_origin=pais_proveedor,
            origin_source=ORIGEN_DEL_PROVEEDOR,
            required_nom_codes=None,
            required_identifiers=None,
        )

    outcome = classify_product(
        borrador,
        operation_date=fecha,
        catalog=catalogo,
        notes=notas,
        search_terms=terminos(borrador),
        trade_flow="IMPORT",
    )

    return ExpectedItem(
        line_number=partida.line_number,
        fraction_code=outcome.code,
        # `is_resolved` sale del contrato de evidencia, no de que el motor haya
        # llegado a un código: una clasificación que no se sostiene no puede
        # usarse para acusar a nadie.
        is_resolved=outcome.code is not None,
        confidence=outcome.trace.confidence,
        country_of_origin=pais_proveedor,
        origin_source=ORIGEN_DEL_PROVEEDOR if pais_proveedor else None,
        customs_value=partida.customs_value,
        customs_value_currency=partida.customs_value_currency,
        # `None`, no `()`: no existe la correlación fracción → NOM ni el
        # Apéndice 8. Decir «no exige ninguna» sería afirmar sin fuente.
        required_nom_codes=None,
        required_identifiers=None,
    )


def _valor(partida: PedimentoItem) -> Money | None:
    if partida.customs_value is None or partida.customs_value_currency is None:
        return None
    return Money(amount=partida.customs_value, currency=partida.customs_value_currency)


def _tasas(
    catalogo: TariffCatalogRepository,
    fecha: date,
    peticion: ReviewRequest,
    *,
    declarada: str | None,
    esperada: str | None,
) -> tuple[TaxRates | None, TaxRates | None]:
    """Tasas de la fracción declarada y de la esperada.

    Si falta cualquiera de las dos se devuelven las dos en `None`: cuantificar
    con una sola daría una diferencia contra cero, que es un número inventado.
    """
    if declarada is None or esperada is None:
        return None, None

    igi_declarada = catalogo.igi_rate(on_date=fecha, fraction_code=declarada)
    igi_esperada = catalogo.igi_rate(on_date=fecha, fraction_code=esperada)
    if igi_declarada is None or igi_esperada is None:
        return None, None

    comunes = {
        "iva_rate": peticion.iva_rate or Decimal("0"),
        "dta_rate": peticion.dta_rate or Decimal("0"),
        "dta_fixed": peticion.dta_fixed,
        "ieps_rate": peticion.ieps_rate or Decimal("0"),
    }
    return (
        TaxRates(igi_rate=igi_declarada, **comunes),
        TaxRates(igi_rate=igi_esperada, **comunes),
    )


def _respuesta(
    review_id: uuid.UUID,
    pedimento_id: uuid.UUID,
    revision: PedimentoReview,
    sin_espejo: int,
) -> ReviewResponse:
    oportunidades = revision.opportunities
    return ReviewResponse(
        review_id=review_id,
        pedimento_id=pedimento_id,
        findings=len(revision.findings),
        worst_severity=revision.worst_severity,
        is_complete=revision.is_complete,
        unverifiable=list(revision.unverifiable),
        total_exposure=revision.total_exposure,
        total_recoverable=revision.total_recoverable,
        currency=revision.currency,
        mixed_currencies=revision.mixed_currencies,
        opportunities=len(oportunidades.opportunities) if oportunidades else 0,
        quantified_opportunities=sum(1 for o in oportunidades.opportunities if o.is_quantified)
        if oportunidades
        else 0,
        is_simulation=revision.is_simulation,
        lines_without_expectation=sin_espejo,
        summary=revision.summary(),
    )
