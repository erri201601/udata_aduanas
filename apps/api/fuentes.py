"""De qué fila sale cada expectativa del Espejo (§21 `source_ids`, §17).

Hasta el 13-oct ningún hallazgo guardado decía de dónde salía: 0 de 315 tenían
evidencia enlazada y `risk_findings` no tenía dónde poner una fuente. Una
«fracción equivocada» no decía contra qué texto de la LIGIE ni de qué fecha, y
eso es justo lo que hay que enseñar para defender un hallazgo ante el SAT.

`source_id` no basta: sólo dice quién publica —SNICE, DOF, Banxico— y en dos
tablas está vacío. Lo que se guarda es la FILA: tabla, id, documento, URL, hash
y vigencia (`core.shadow.SourceRef`).

Se buscan con los mismos filtros de vigencia que usó la expectativa, en la
fecha de la operación. Si una fila no aparece, la comprobación queda sin
fuente —no se inventa una—, y la lista vacía se ve en el hallazgo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from core.shadow import ExpectedItem, SourceRef
from core.shadow.compare import CAMPO_IDENTIFICADORES_DEL_DOCUMENTO
from database.models import (
    ClassificationDecision,
    CompensatoryDuty,
    ExchangeRate,
    FractionNomRequirement,
    Invoice,
    InvoiceItem,
    LegalDocument,
    LegalRule,
    Nico,
    PedimentoIdentifierRequirement,
    PedimentoItem,
    ProductDna,
    Supplier,
    TariffFraction,
    UnitOfMeasure,
)
from database.repositories.invoices import divisa_de_la_factura
from database.repositories.preguntas import dictamen_de

from apps.api.dna import version_vigente

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.orm import Session

#: Los artículos de la Ley Aduanera que fundan el dinero de una partida.
ARTICULO_BASE_GRAVABLE = "64"
"""La base gravable del IGI es el valor en aduana."""
ARTICULO_VALOR_DE_TRANSACCION = "65"
"""El valor de transacción: precio pagado más incrementables."""


def _vigente(modelo: Any, fecha: date) -> sa.ColumnElement[bool]:
    return sa.and_(
        modelo.valid_from <= fecha,
        sa.or_(modelo.valid_to.is_(None), modelo.valid_to >= fecha),
    )


def ref_de_fila(fila: Any, tabla: str, que: str) -> SourceRef:
    """Una fila con `RegulatoryMixin`, como fuente."""
    return SourceRef(
        what=que,
        table=tabla,
        row_id=str(fila.id),
        source_id=str(fila.source_id) if fila.source_id else None,
        document=fila.source_document,
        url=fila.source_url,
        content_hash=fila.content_hash,
        valid_from=fila.valid_from,
        valid_to=fila.valid_to,
        data_origin=fila.data_origin,
    )


def _fraccion(session: Session, fecha: date, codigo: str | None) -> list[SourceRef]:
    if not codigo:
        return []
    fila = session.scalars(
        sa.select(TariffFraction)
        .where(_vigente(TariffFraction, fecha), TariffFraction.code == codigo)
        .order_by(TariffFraction.valid_from.desc())
        .limit(1)
    ).first()
    if fila is None:
        return []
    return [ref_de_fila(fila, "regulatory.tariff_fractions", f"fracción {codigo} en la LIGIE")]


def _nico(session: Session, fecha: date, fraccion: str | None, nico: str | None) -> list[SourceRef]:
    if not fraccion or not nico:
        return []
    fila = session.scalars(
        sa.select(Nico)
        .where(_vigente(Nico, fecha), Nico.full_code == f"{fraccion}{nico}")
        .order_by(Nico.valid_from.desc())
        .limit(1)
    ).first()
    if fila is None:
        return []
    return [ref_de_fila(fila, "regulatory.nicos", f"NICO {nico} de la fracción {fraccion}")]


def _articulo(session: Session, fecha: date, numero: str) -> list[SourceRef]:
    fila = session.scalars(
        sa.select(LegalRule)
        .join(LegalDocument, LegalDocument.id == LegalRule.legal_document_id)
        .where(
            _vigente(LegalRule, fecha),
            LegalDocument.title == "Ley Aduanera",
            LegalRule.rule_number == numero,
        )
        .order_by(LegalRule.valid_from.desc())
        .limit(1)
    ).first()
    if fila is None:
        return []
    return [ref_de_fila(fila, "regulatory.legal_rules", f"Ley Aduanera, artículo {numero}")]


def _dictamen(session: Session, product_id: Any) -> list[SourceRef]:
    """El veredicto humano de la ficha vigente, como fuente.

    No es norma: es criterio firmado, y `data_origin = HUMAN_VALIDATED` lo dice.
    """
    if product_id is None:
        return []
    ficha = version_vigente(session, product_id)
    if ficha is None:
        return []
    veredicto: ClassificationDecision | None = dictamen_de(session, ficha.id)
    if veredicto is None:
        return []
    return [
        SourceRef(
            what=f"dictamen de un clasificador del {veredicto.created_at.date().isoformat()}",
            table="intelligence.classification_decisions",
            row_id=str(veredicto.id),
            data_origin=veredicto.data_origin,
        )
    ]


def _ficha(session: Session, product_id: Any) -> list[SourceRef]:
    if product_id is None:
        return []
    ficha: ProductDna | None = version_vigente(session, product_id)
    if ficha is None:
        return []
    return [
        SourceRef(
            what="ficha técnica vigente del producto (Product DNA)",
            table="intelligence.product_dnas",
            row_id=str(ficha.id),
            data_origin=ficha.data_origin,
        )
    ]


def _proveedor(session: Session, partida: PedimentoItem) -> list[SourceRef]:
    if partida.invoice_item_id is None:
        return []
    fila = session.execute(
        sa.select(Supplier.id, Supplier.data_origin)
        .select_from(InvoiceItem)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .join(Supplier, Supplier.id == Invoice.supplier_id)
        .where(InvoiceItem.id == partida.invoice_item_id)
    ).first()
    if fila is None:
        return []
    return [
        SourceRef(
            what="país del proveedor de la factura",
            table="operational.suppliers",
            row_id=str(fila.id),
            data_origin=fila.data_origin,
        )
    ]


def _factura(session: Session, partida: PedimentoItem) -> list[SourceRef]:
    if partida.invoice_item_id is None:
        return []
    fila = session.execute(
        sa.select(Invoice.id, Invoice.invoice_number, Invoice.data_origin)
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .where(InvoiceItem.id == partida.invoice_item_id)
    ).first()
    if fila is None:
        return []
    return [
        SourceRef(
            what=f"flete y seguro que cobra la factura {fila.invoice_number}",
            table="operational.invoices",
            row_id=str(fila.id),
            data_origin=fila.data_origin,
        )
    ]


def _tipo_de_cambio(
    session: Session, partida: PedimentoItem, fecha: date, moneda: str | None = None
) -> list[SourceRef]:
    """El FIX de `moneda`; por omisión, el de la divisa de la factura."""
    moneda = moneda or divisa_de_la_factura(session, partida)
    if moneda is None or moneda == "MXN":
        return []
    fila = session.scalars(
        sa.select(ExchangeRate)
        .where(_vigente(ExchangeRate, fecha), ExchangeRate.currency == moneda)
        .order_by(ExchangeRate.valid_from.desc())
        .limit(1)
    ).first()
    if fila is None:
        return []
    return [ref_de_fila(fila, "regulatory.exchange_rates", f"tipo de cambio FIX de {moneda}")]


def _cuotas(session: Session, partida: PedimentoItem, fecha: date) -> list[SourceRef]:
    if partida.country_of_origin is None or not partida.declared_fraction_code:
        return []
    filas = session.scalars(
        sa.select(CompensatoryDuty).where(
            _vigente(CompensatoryDuty, fecha),
            CompensatoryDuty.origin_country == partida.country_of_origin,
            CompensatoryDuty.fraction_code == partida.declared_fraction_code,
        )
    ).all()
    return [
        ref_de_fila(
            f,
            "regulatory.compensatory_duties",
            f"cuota compensatoria {f.origin_country} · {f.fraction_code}",
        )
        for f in filas
    ]


def _unidades(session: Session, fecha: date) -> list[SourceRef]:
    fila = session.scalars(
        sa.select(UnitOfMeasure).where(_vigente(UnitOfMeasure, fecha)).limit(1)
    ).first()
    if fila is None:
        return []
    return [ref_de_fila(fila, "regulatory.units_of_measure", "catálogo de unidades (Apéndice 7)")]


def _nom(session: Session, fecha: date, fraccion: str | None) -> list[SourceRef]:
    if not fraccion:
        return []
    filas = session.scalars(
        sa.select(FractionNomRequirement).where(
            _vigente(FractionNomRequirement, fecha),
            FractionNomRequirement.fraction_code == fraccion,
            FractionNomRequirement.scope_note.is_(None),
        )
    ).all()
    return [
        ref_de_fila(
            f,
            "regulatory.fraction_nom_requirements",
            f"{f.nom_code} para la fracción {fraccion} (Anexo 2.4.1)",
        )
        for f in filas
    ]


def _identificadores(
    session: Session,
    fecha: date,
    *,
    codigos: tuple[str, ...],
    pedimento_key: str | None,
    partida: PedimentoItem,
) -> list[SourceRef]:
    if not codigos:
        return []
    fraccion = partida.declared_fraction_code
    hechos = [
        ("PEDIMENTO_KEY", pedimento_key),
        ("FRACTION", fraccion),
        (
            "NICO",
            f"{fraccion}{partida.declared_nico_code}"
            if fraccion and partida.declared_nico_code
            else None,
        ),
    ]
    condicion = sa.or_(
        *(
            sa.and_(
                PedimentoIdentifierRequirement.condition_kind == tipo,
                PedimentoIdentifierRequirement.condition_value == valor,
            )
            for tipo, valor in hechos
            if valor
        )
    )
    filas = session.scalars(
        sa.select(PedimentoIdentifierRequirement).where(
            _vigente(PedimentoIdentifierRequirement, fecha),
            PedimentoIdentifierRequirement.identifier_code.in_(codigos),
            condicion,
        )
    ).all()
    return [
        ref_de_fila(
            f,
            "regulatory.pedimento_identifier_requirements",
            f"identificador {f.identifier_code} exigido por {f.condition_kind} "
            f"{f.condition_value} (Apéndice 8)",
        )
        for f in filas
    ]


def fuentes_de_la_partida(
    session: Session,
    *,
    partida: PedimentoItem,
    fecha: date,
    esperada: ExpectedItem,
    pedimento_key: str | None,
) -> dict[str, tuple[SourceRef, ...]]:
    """Las fuentes de cada expectativa, por el `field` de su divergencia.

    Sólo para lo que la expectativa tiene: un campo sin expectativa no tiene
    divergencia que sostener.
    """
    fuentes: dict[str, list[SourceRef]] = {}
    declarada = partida.declared_fraction_code
    tarifa_declarada = _fraccion(session, fecha, declarada)

    if esperada.fraction_code:
        fuentes["fraction_code"] = [
            *_fraccion(session, fecha, esperada.fraction_code),
            *(_dictamen(session, partida.product_id) if esperada.fraction_source else []),
        ]
    if esperada.nico_code or esperada.valid_nico_codes is not None:
        fuentes["nico_code"] = (
            [
                *_nico(session, fecha, esperada.fraction_code, esperada.nico_code),
                *(_dictamen(session, partida.product_id) if esperada.nico_source else []),
            ]
            if esperada.nico_code
            else list(tarifa_declarada)
        )
    if esperada.igi_amount is not None:
        fuentes["igi_amount"] = [
            *tarifa_declarada,
            *_articulo(session, fecha, ARTICULO_BASE_GRAVABLE),
        ]
    if esperada.vat_amount is not None:
        fuentes["vat_amount"] = list(tarifa_declarada)
    if esperada.customs_value is not None:
        fuentes["customs_value"] = [
            *_articulo(session, fecha, ARTICULO_VALOR_DE_TRANSACCION),
            # El FIX sólo si el precio pagado de la PARTIDA viene en otra
            # divisa: es lo que convierte `_valor_esperado`. La divisa de la
            # factura no entra aquí (ver su docstring).
            *(
                _tipo_de_cambio(session, partida, fecha, partida.price_paid_currency)
                if partida.price_paid_currency and partida.price_paid_currency != "MXN"
                else []
            ),
        ]
        fuentes["customs_value_currency"] = fuentes["customs_value"]
    if esperada.minimum_incrementables is not None:
        fuentes["incrementables"] = [
            *_articulo(session, fecha, ARTICULO_VALOR_DE_TRANSACCION),
            *_factura(session, partida),
            *_tipo_de_cambio(session, partida, fecha),
        ]
    if esperada.exchange_rate is not None:
        fuentes["exchange_rate"] = _tipo_de_cambio(session, partida, fecha)
    if esperada.compensatory_duty_applies:
        fuentes["cc_amount"] = _cuotas(session, partida, fecha)
    if esperada.declared_unit_is_known is not None:
        fuentes["unit"] = _unidades(session, fecha)
    if esperada.country_of_origin:
        fuentes["country_of_origin"] = _proveedor(session, partida)
    if esperada.required_nom_codes:
        fuentes["applied_nom_codes"] = _nom(session, fecha, esperada.fraction_code)
    if esperada.missing_technical_fields:
        fuentes["missing_information"] = _ficha(session, partida.product_id)
    for campo, codigos in (
        ("identifiers", esperada.required_identifiers),
        (CAMPO_IDENTIFICADORES_DEL_DOCUMENTO, esperada.required_document_identifiers),
    ):
        if codigos:
            fuentes[campo] = _identificadores(
                session, fecha, codigos=codigos, pedimento_key=pedimento_key, partida=partida
            )
    return {campo: tuple(refs) for campo, refs in fuentes.items() if refs}
