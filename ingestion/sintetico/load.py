"""VALIDATED -> DATABASE del corpus espejo V1.

Puebla `operational.*` con lo OBSERVADO de cada partida (nunca lo esperado)
y `intelligence.ground_truth_records` con la verdad de referencia — la
frontera que exige el §26: si `expected` tocara una tabla operativa, el
motor vería la respuesta antes de responder y la medición dejaría de valer.

LA CADENA DEL PROVEEDOR (hallazgo de Ulises, 2026-09-21)

`Pedimento` no guarda proveedor. El único camino para comprobar
`country_of_origin` contra un dato "impreso" es
`pedimento_item.invoice_item_id -> invoice_item.invoice_id -> invoice.supplier_id
-> supplier.country`. Por eso todo pedimento materializa Client, Supplier,
Invoice e InvoiceItem aunque el corpus no los pida explícitamente como
tablas — sin la cadena completa, `invoice_item_id` queda NULL y los 6 casos
de PAIS_ORIGEN_INCONSISTENTE no se pueden comprobar.

IDEMPOTENCIA

Se decide por pedimento completo: si `Pedimento.pedimento_number` ya existe,
se salta TODO lo de ese documento (cliente, proveedor, factura, partidas,
ground truth) — nunca una mezcla de "ya estaba" y "se repite". Correr el
cargador dos veces no duplica nada porque la segunda vez no crea nada.

UN PRODUCT POR FICHA DE CATÁLOGO, UNA ProductDna POR PARTIDA
(corrección de Persona 1, 22-sep-2026 — la primera versión de este módulo
creaba un `Product` distinto por cada partida y lo tenía mal)

El corpus define 12 productos de catálogo (`P001`..`P012`) que se repiten
entre pedimentos distintos. `Product` es UNO por `product_id`
(`client_id`/`supplier_id` en NULL: no pertenece a un importador ni a un
proveedor en particular). Compartirlo es lo que hace posible
`INCONSISTENT_SKU_CLASSIFICATION` — "el mismo SKU clasificado distinto en
dos pedimentos" no puede existir si cada partida tiene su propio producto
aislado.

`ProductDna` sí es una versión NUEVA por partida (nunca compartida): cada
declaración trae su propia ficha, completa o recortada, y las 21 con
`classification_evaluable=false` necesitan la suya sin afectar a las demás
versiones del mismo producto. Las características que `technical_spec`
omite respecto de la ficha de catálogo (`product_specs[product_id].spec`)
quedan como `ProductAttribute` con `status=MISSING` — así el motor de RGI
las ve vacías y puede decir `SIN_VERIFICAR`, en vez de que el cargador
decida por él. `summary` es la descripción COMERCIAL de esa partida
(`commercial_description`), no `classification_reason` — ese fue el otro
bug real: un resumen de producto no es el motivo por el que se puede o no
clasificar.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from database.models.intelligence import GroundTruthRecord, ProductAttribute, ProductDna
from database.models.operational import (
    Client,
    Invoice,
    InvoiceItem,
    Pedimento,
    PedimentoItem,
    Product,
    Supplier,
    SyntheticScenario,
)
from database.models.regulatory import Nico, TariffFraction

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from sqlalchemy.orm import Session

    from ingestion.sintetico.corpus_espejo import (
        ParsedCorpus,
        ParsedPartida,
        ParsedPedimento,
        ParsedProductSpec,
    )

DATA_ORIGIN = "SYNTHETIC"
SCENARIO_SLUG = "corpus_espejo_v1"
MXN = "MXN"

#: ISO 3166-1 alfa-3 -> alfa-2. El corpus trae los países en alfa-3
#: ("CHN"/"IND"/"TUR"/"BRA"); `Supplier.country` y
#: `PedimentoItem.country_of_origin` son `VARCHAR(2)`, mismo convenio que ya
#: usa `Client.country` (`server_default='MX'`) en el resto del sistema.
#: Sólo cubre los países que de verdad aparecen en el corpus V1 (verificado
#: contra el JSON completo, no una lista genérica de internet) — si aparece
#: uno nuevo en una versión futura, `_alpha2` falla ruidoso en vez de
#: adivinar un código.
_ALPHA3_A_ALPHA2 = {
    "CHN": "CN",
    "IND": "IN",
    "TUR": "TR",
    "BRA": "BR",
}


def _alpha2(codigo_alpha3: str) -> str:
    try:
        return _ALPHA3_A_ALPHA2[codigo_alpha3]
    except KeyError:
        raise ValueError(
            f"país {codigo_alpha3!r} no está en el mapeo alfa-3->alfa-2 del corpus "
            "espejo V1 -- agrégalo explícitamente (ISO 3166-1), nunca lo adivines."
        ) from None


@dataclass(frozen=True)
class LoadReport:
    """Los números que pide Persona 1 para el reporte del §46."""

    pedimentos_creados: int
    pedimentos_saltados: int
    partidas_creadas: int
    partidas_con_invoice_item: int
    ground_truth_creados: int
    ground_truth_expected_true: int


def get_or_create_scenario(session: Session, *, seed: int) -> SyntheticScenario:
    existing = session.query(SyntheticScenario).filter_by(slug=SCENARIO_SLUG).one_or_none()
    if existing is not None:
        return existing
    scenario = SyntheticScenario(
        slug=SCENARIO_SLUG,
        name="Corpus espejo V1 — 15 pedimentos sintéticos",
        description=(
            "Benchmark de precisión (§26): 180 partidas, 60 anomalías sembradas "
            "en 10 tipos, 21 con ficha técnica recortada a propósito."
        ),
        seed=seed,
        generator_version="1.0",
        data_origin=DATA_ORIGIN,
        parameters={},
    )
    session.add(scenario)
    session.flush()
    return scenario


def _get_or_create_client(
    session: Session, ped: ParsedPedimento, scenario: SyntheticScenario
) -> Client:
    existing = session.query(Client).filter_by(rfc=ped.importer_rfc).one_or_none()
    if existing is not None:
        return existing
    client = Client(
        legal_name=ped.importer_name,
        rfc=ped.importer_rfc,
        address={"texto": ped.importer_address},
        data_origin=DATA_ORIGIN,
        synthetic_scenario_id=scenario.id,
        seed=scenario.seed,
    )
    session.add(client)
    session.flush()
    return client


def _get_or_create_supplier(
    session: Session, ped: ParsedPedimento, scenario: SyntheticScenario
) -> Supplier:
    existing = (
        session.query(Supplier)
        .filter_by(legal_name=ped.provider_name, country=_alpha2(ped.provider_country))
        .one_or_none()
    )
    if existing is not None:
        return existing
    supplier = Supplier(
        legal_name=ped.provider_name,
        country=_alpha2(ped.provider_country),
        address={"texto": ped.provider_address},
        data_origin=DATA_ORIGIN,
        synthetic_scenario_id=scenario.id,
        seed=scenario.seed,
    )
    session.add(supplier)
    session.flush()
    return supplier


def _create_invoice(
    session: Session,
    ped: ParsedPedimento,
    *,
    client: Client,
    supplier: Supplier,
    scenario: SyntheticScenario,
) -> Invoice:
    """Una factura por pedimento: el corpus no distingue varias por documento.

    `total_amount` en la moneda del proveedor, derivado de
    `totals.precio_pagado_mxn / exchange_rate` — el corpus no trae un total
    en moneda extranjera explícito. Documentado como derivado, no observado
    directo, porque no hay otra fuente en el JSON.
    """
    total_extranjero = (ped.totals_valor_aduana_mxn / ped.exchange_rate).quantize(Decimal("0.01"))
    invoice = Invoice(
        client_id=client.id,
        supplier_id=supplier.id,
        invoice_number=ped.document_id,
        invoice_date=ped.date_entry,
        incoterm=ped.provider_incoterm,
        currency=ped.provider_currency,
        total_amount=total_extranjero,
        total_amount_currency=ped.provider_currency,
        data_origin=DATA_ORIGIN,
        synthetic_scenario_id=scenario.id,
        seed=scenario.seed,
    )
    session.add(invoice)
    session.flush()
    return invoice


def _create_invoice_item(
    session: Session,
    parte: ParsedPartida,
    *,
    invoice: Invoice,
    scenario: SyntheticScenario,
    exchange_rate: Decimal,
) -> InvoiceItem:
    """`country_of_origin` queda NULL a propósito (instrucción de Persona 1,
    21-sep-2026): el corpus no incluye facturas reales, y llenarlo con el
    país esperado metería la respuesta en las tablas operativas. La
    comprobación de país se apoya en `supplier.country`, dato impreso."""
    observado = parte.observed
    cantidad = _d(observado["cantidad_umc"])
    precio_pagado_mxn = _d(observado["precio_pagado_mxn"])
    unit_price = (precio_pagado_mxn / exchange_rate / cantidad).quantize(Decimal("0.000001"))
    line_total = (unit_price * cantidad).quantize(Decimal("0.01"))
    item = InvoiceItem(
        invoice_id=invoice.id,
        line_number=parte.line_number,
        description=parte.commercial_description,
        quantity=cantidad,
        unit_of_measure=str(observado["umc"]),
        country_of_origin=None,
        unit_price=unit_price,
        unit_price_currency=invoice.currency,
        line_total=line_total,
        line_total_currency=invoice.currency,
        data_origin=DATA_ORIGIN,
        synthetic_scenario_id=scenario.id,
        seed=scenario.seed,
    )
    session.add(item)
    session.flush()
    return item


def _create_product_con_dna(
    session: Session,
    parte: ParsedPartida,
    *,
    client: Client,
    supplier: Supplier,
    spec: ParsedProductSpec,
    scenario: SyntheticScenario,
    document_id: str,
) -> Product:
    """Un `Product`+`ProductDna` POR PARTIDA.

    NO se comparte un solo `Product` por `product_id` de catálogo, aunque
    varias partidas (en el mismo pedimento o en otro) declaren la misma
    mercancía — decisión de Persona 1, 22-sep-2026, revirtiendo un intento
    anterior de compartirlo. La razón no es de estilo: `ProductDna` cuelga
    de `product_id` y `apps/api/dna.py` resuelve la ficha vigente con
    `where(product_id=..., is_current=True).order_by(version.desc())`. Con
    un `Product` compartido, cada partida crea una versión nueva y todas
    quedan con `is_current=True` (nada las cierra) — el Espejo devuelve LA
    ÚLTIMA cargada para CUALQUIER partida de ese producto. Las ~15 partidas
    de un mismo producto terminarían compartiendo una sola ficha, y las 21
    con `classification_evaluable=false` recibirían la ficha completa de
    otra partida según el orden de carga — exactamente lo que el corpus
    existe para impedir que pase desapercibido.

    (Para compartir el `Product` de verdad haría falta que el Espejo
    resolviera la ficha vigente POR PARTIDA, no por producto — cambio de
    contrato que no toca esta tarea.)

    La identidad de catálogo (qué partidas son la misma mercancía) no se
    pierde: `Product.model` guarda el `product_id` del corpus (`P001`..
    `P012`), aunque cada partida tenga su propio `Product`+`sku`.
    """
    faltantes = sorted(set(spec.spec) - set(parte.technical_spec))
    product = Product(
        client_id=client.id,
        supplier_id=supplier.id,
        sku=f"{document_id}-{parte.sec}",
        model=spec.id,
        commercial_name=parte.commercial_description[:200],
        description=parte.commercial_description,
        data_origin=DATA_ORIGIN,
        synthetic_scenario_id=scenario.id,
        seed=scenario.seed,
    )
    session.add(product)
    session.flush()

    dna = ProductDna(
        product_id=product.id,
        version=1,
        is_current=True,
        input_kinds=["TEXT"],
        # Descripción COMERCIAL de esta partida, no `classification_reason`
        # (el motivo de por qué se puede o no clasificar no es un resumen
        # de producto) — corrección de Persona 1, 22-sep-2026.
        summary=parte.commercial_description,
        missing_information=faltantes,
        data_origin=DATA_ORIGIN,
        synthetic_scenario_id=scenario.id,
        seed=scenario.seed,
    )
    session.add(dna)
    session.flush()

    for nombre, valor in parte.technical_spec.items():
        session.add(
            ProductAttribute(
                product_dna_id=dna.id,
                name=nombre,
                value=str(valor),
                status="OBSERVED",
                data_origin=DATA_ORIGIN,
            )
        )
    for nombre in faltantes:
        session.add(
            ProductAttribute(
                product_dna_id=dna.id,
                name=nombre,
                value=None,
                status="MISSING",
                data_origin=DATA_ORIGIN,
            )
        )
    session.flush()
    return product


def _d(valor: object) -> Decimal:
    return Decimal(str(valor))


def _resolver_fraccion(session: Session, code: str, on_date: date) -> uuid.UUID | None:
    return session.execute(
        sa.select(TariffFraction.id).where(
            TariffFraction.code == code,
            TariffFraction.valid_from <= on_date,
            sa.or_(TariffFraction.valid_to.is_(None), TariffFraction.valid_to >= on_date),
        )
    ).scalar_one_or_none()


def _resolver_nico(
    session: Session, fraccion_id: uuid.UUID | None, nico_code: str, on_date: date
) -> uuid.UUID | None:
    if fraccion_id is None:
        return None
    return session.execute(
        sa.select(Nico.id).where(
            Nico.tariff_fraction_id == fraccion_id,
            Nico.code == nico_code,
            Nico.valid_from <= on_date,
            sa.or_(Nico.valid_to.is_(None), Nico.valid_to >= on_date),
        )
    ).scalar_one_or_none()


def _create_pedimento_item(
    session: Session,
    parte: ParsedPartida,
    *,
    pedimento: Pedimento,
    product: Product,
    invoice_item: InvoiceItem,
    scenario: SyntheticScenario,
    on_date: date,
) -> PedimentoItem:
    observado = parte.observed
    fraccion_id = _resolver_fraccion(session, observado["fraccion"], on_date)
    nico_id = _resolver_nico(session, fraccion_id, observado["nico"], on_date)

    item = PedimentoItem(
        pedimento_id=pedimento.id,
        product_id=product.id,
        invoice_item_id=invoice_item.id,
        line_number=parte.line_number,
        description=parte.commercial_description,
        declared_fraction_code=observado["fraccion"],
        declared_nico_code=observado["nico"],
        tariff_fraction_id=fraccion_id,
        nico_id=nico_id,
        quantity=_d(observado["cantidad_umc"]),
        commercial_unit=str(observado["umc"]),
        country_of_origin=_alpha2(observado["pais_origen"]),
        customs_value=_d(observado["valor_aduana_mxn"]),
        customs_value_currency=MXN,
        igi_amount=_d(observado["igi_mxn"]),
        igi_amount_currency=MXN,
        vat_amount=_d(observado["iva_mxn"]),
        vat_amount_currency=MXN,
        price_paid=_d(observado["precio_pagado_mxn"]),
        price_paid_currency=MXN,
        incrementables=_d(observado["incrementables_mxn"]),
        incrementables_currency=MXN,
        data_origin=DATA_ORIGIN,
        synthetic_scenario_id=scenario.id,
        seed=scenario.seed,
    )
    session.add(item)
    session.flush()
    return item


def _ground_truth_rows(
    parte: ParsedPartida,
    *,
    pedimento: Pedimento,
    pedimento_item: PedimentoItem,
    scenario: SyntheticScenario,
) -> list[GroundTruthRecord]:
    rows = []
    for anomalia in parte.anomalies:
        error_type, expected_field = anomalia.error_type_y_campo
        rows.append(
            GroundTruthRecord(
                pedimento_id=pedimento.id,
                pedimento_item_id=pedimento_item.id,
                error_type=error_type,
                original_value=anomalia.expected_value,
                mutated_value=anomalia.observed_value,
                expected_detection=anomalia.expected_detection,
                expected_field=expected_field,
                data_origin=DATA_ORIGIN,
                synthetic_scenario_id=scenario.id,
                seed=scenario.seed,
            )
        )
    return rows


def load_pedimento(
    session: Session,
    ped: ParsedPedimento,
    *,
    scenario: SyntheticScenario,
    product_specs: dict[str, ParsedProductSpec],
) -> tuple[Pedimento | None, int, int]:
    """Carga un pedimento completo. Devuelve `(pedimento_o_None, n_partidas, n_ground_truth)`.

    `None` si ya existía (idempotencia por `pedimento_number`) — no toca nada
    de ese documento, ni siquiera para "completar" lo que faltara.
    """
    existente = (
        session.query(Pedimento).filter_by(pedimento_number=ped.pedimento_number).one_or_none()
    )
    if existente is not None:
        return None, 0, 0

    client = _get_or_create_client(session, ped, scenario)
    supplier = _get_or_create_supplier(session, ped, scenario)
    invoice = _create_invoice(session, ped, client=client, supplier=supplier, scenario=scenario)

    pedimento = Pedimento(
        client_id=client.id,
        pedimento_number=ped.pedimento_number,
        customs_office=ped.entry_customs,
        pedimento_key=ped.pedimento_key,
        regime=ped.regime,
        trade_flow=ped.trade_flow,
        operation_date=ped.date_entry,
        entry_date=ped.date_entry,
        currency=MXN,
        exchange_rate=ped.exchange_rate,
        customs_value=ped.totals_valor_aduana_mxn,
        customs_value_currency=MXN,
        is_simulation=True,
        data_origin=DATA_ORIGIN,
        synthetic_scenario_id=scenario.id,
        seed=scenario.seed,
    )
    session.add(pedimento)
    session.flush()

    n_ground_truth = 0
    for parte in ped.parts:
        invoice_item = _create_invoice_item(
            session, parte, invoice=invoice, scenario=scenario, exchange_rate=ped.exchange_rate
        )
        spec = product_specs[parte.product_id]
        product = _create_product_con_dna(
            session,
            parte,
            client=client,
            supplier=supplier,
            spec=spec,
            scenario=scenario,
            document_id=ped.document_id,
        )
        item = _create_pedimento_item(
            session,
            parte,
            pedimento=pedimento,
            product=product,
            invoice_item=invoice_item,
            scenario=scenario,
            on_date=ped.date_entry,
        )
        for gt in _ground_truth_rows(
            parte, pedimento=pedimento, pedimento_item=item, scenario=scenario
        ):
            session.add(gt)
            n_ground_truth += 1

    session.flush()
    return pedimento, len(ped.parts), n_ground_truth


def load_corpus(session: Session, corpus: ParsedCorpus, *, seed: int = 20260921) -> LoadReport:
    scenario = get_or_create_scenario(session, seed=seed)

    pedimentos_creados = 0
    pedimentos_saltados = 0
    partidas_creadas = 0
    partidas_con_invoice_item = 0
    ground_truth_creados = 0

    for ped in corpus.pedimentos:
        pedimento, n_partidas, n_gt = load_pedimento(
            session, ped, scenario=scenario, product_specs=corpus.product_specs
        )
        if pedimento is None:
            pedimentos_saltados += 1
            continue
        pedimentos_creados += 1
        partidas_creadas += n_partidas
        partidas_con_invoice_item += n_partidas  # toda partida creada aquí trae invoice_item
        ground_truth_creados += n_gt

    session.flush()

    gt_true = (
        session.query(GroundTruthRecord)
        .filter_by(synthetic_scenario_id=scenario.id, expected_detection=True)
        .count()
    )

    return LoadReport(
        pedimentos_creados=pedimentos_creados,
        pedimentos_saltados=pedimentos_saltados,
        partidas_creadas=partidas_creadas,
        partidas_con_invoice_item=partidas_con_invoice_item,
        ground_truth_creados=ground_truth_creados,
        ground_truth_expected_true=gt_true,
    )


def delete_scenario_data(session: Session, *, slug: str = SCENARIO_SLUG) -> int:
    """Borra TODO lo que carga este módulo para un escenario, sin dejar restos (§24).

    Necesario para corregir una carga hecha con una versión anterior del
    cargador (p. ej. el bug real del 22-sep-2026: `Product` por partida en
    vez de por ficha de catálogo) sin arrastrar filas huérfanas. Respeta el
    orden de dependencias — hijos antes que padres — porque varias FK son
    `RESTRICT`, no `CASCADE`. No borra `SyntheticScenario`: `load_corpus()`
    la reutiliza en la siguiente carga (`get_or_create_scenario`).

    Devuelve cuántos `Pedimento` se borraron. `0` si el escenario no existe
    o ya estaba vacío — no es un error, es un cargador que corre sobre una
    base limpia.
    """
    scenario = session.query(SyntheticScenario).filter_by(slug=slug).one_or_none()
    if scenario is None:
        return 0
    sid = scenario.id

    session.query(GroundTruthRecord).filter_by(synthetic_scenario_id=sid).delete()
    n_pedimentos = session.query(Pedimento).filter_by(synthetic_scenario_id=sid).count()
    session.query(PedimentoItem).filter_by(synthetic_scenario_id=sid).delete()
    session.query(Pedimento).filter_by(synthetic_scenario_id=sid).delete()

    dna_ids = [
        row.id
        for row in session.query(ProductDna.id)
        .join(Product, Product.id == ProductDna.product_id)
        .filter(Product.synthetic_scenario_id == sid)
    ]
    if dna_ids:
        session.query(ProductAttribute).filter(ProductAttribute.product_dna_id.in_(dna_ids)).delete(
            synchronize_session=False
        )
        session.query(ProductDna).filter(ProductDna.id.in_(dna_ids)).delete(
            synchronize_session=False
        )
    session.query(Product).filter_by(synthetic_scenario_id=sid).delete()

    session.query(InvoiceItem).filter_by(synthetic_scenario_id=sid).delete()
    session.query(Invoice).filter_by(synthetic_scenario_id=sid).delete()
    session.query(Supplier).filter_by(synthetic_scenario_id=sid).delete()
    session.query(Client).filter_by(synthetic_scenario_id=sid).delete()

    session.flush()
    return n_pedimentos
