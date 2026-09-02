"""Fixtures mínimas del Canonical Data Model v0.1.

Un escenario coherente de punta a punta (fuente → fracción → producto →
Product DNA → factura → pedimento → decisión → hallazgo → ground truth) para
poder ejercitar el modelo sin depender todavía de la ingestión real.

**Todo aquí es `SYNTHETIC`** (§10 maestro): la fracción, el NICO y el documento
jurídico son inventados para la demo. La ingestión real de fuentes P0 (LIGIE,
NICO, RGCE…) los reemplaza por filas `OFFICIAL`. Nada de esto se presenta como
real en la UI.

Uso:
    python -m database.seeds.canonical_v0_1        # contra el .env local
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from apps.api.config import get_settings
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    ClassificationCandidate,
    ClassificationDecision,
    Client,
    Cove,
    EvidenceRecord,
    GroundTruthRecord,
    Invoice,
    InvoiceItem,
    LegalDocument,
    LegalSource,
    Nico,
    Pedimento,
    PedimentoItem,
    Product,
    ProductAttribute,
    ProductDna,
    RiskFinding,
    Supplier,
    SyntheticScenario,
    TariffFraction,
)

SCENARIO_SLUG = "demo-laptop-v0-1"
SEED = 20260101
_SYNTHETIC = "SYNTHETIC"
_RETRIEVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def seed(session: Session) -> SyntheticScenario:
    """Inserta el escenario demo. Idempotente por `SCENARIO_SLUG`."""
    existing = session.scalar(
        select(SyntheticScenario).where(SyntheticScenario.slug == SCENARIO_SLUG)
    )
    if existing is not None:
        return existing

    scenario = SyntheticScenario(
        slug=SCENARIO_SLUG,
        name="Demo — laptop importada de China",
        description="Escenario mínimo end-to-end para v0.1. Datos inventados.",
        seed=SEED,
        generator_version="0.1.0",
        data_origin=_SYNTHETIC,
        parameters={"hs_chapter": "84", "origin": "CN"},
    )
    session.add(scenario)
    session.flush()

    reg = {
        "data_origin": _SYNTHETIC,
        "valid_from": date(2022, 1, 1),
        "source_url": "https://example.invalid/demo",
        "content_hash": "sha256:demo",
        "retrieved_at": _RETRIEVED_AT,
    }
    syn = {"data_origin": _SYNTHETIC, "synthetic_scenario_id": scenario.id, "seed": SEED}

    source = LegalSource(
        slug="demo-snice",
        name="SNICE (demo)",
        authority="Secretaría de Economía",
        kind="PUBLIC",
    )
    session.add(source)
    session.flush()

    tigie = LegalDocument(
        title="TIGIE (demo)",
        short_name="TIGIE",
        kind="TARIFF",
        source_id=source.id,
        **reg,
    )
    session.add(tigie)
    session.flush()

    fraction = TariffFraction(
        code="84713001",
        chapter="84",
        heading="8471",
        subheading="847130",
        description="Máquinas automáticas para tratamiento o procesamiento de datos, portátiles, de peso <= 10 kg",
        unit="06",
        igi_rate=Decimal("0.000000"),
        legal_document_id=tigie.id,
        source_id=source.id,
        **reg,
    )
    session.add(fraction)
    session.flush()

    nico = Nico(
        tariff_fraction_id=fraction.id,
        code="00",
        full_code="8471300100",
        description="Los demás (demo)",
        source_id=source.id,
        **reg,
    )
    session.add(nico)

    client = Client(legal_name="Importadora Demo, S.A. de C.V.", rfc="IDE010101AAA", **syn)
    supplier = Supplier(
        legal_name="Shenzhen Demo Electronics Co., Ltd.",
        country="CN",
        is_manufacturer=True,
        **syn,
    )
    session.add_all([client, supplier])
    session.flush()

    product = Product(
        client_id=client.id,
        supplier_id=supplier.id,
        sku="LAP-DEMO-001",
        commercial_name='Laptop Demo 14" 8GB',
        brand="DemoBrand",
        model="DB-14",
        manufacturer_name="Shenzhen Demo Electronics Co., Ltd.",
        country_of_manufacture="CN",
        unit_of_measure="PZA",
        **syn,
    )
    session.add(product)
    session.flush()

    evidence = EvidenceRecord(
        subject_kind="classification_decision",
        summary="Clasificación demo sustentada en TIGIE capítulo 84.",
        source_ids=[source.id],
        content_hashes=["sha256:demo"],
        engine_version="0.1.0",
        data_origin=_SYNTHETIC,
        source_id=source.id,
    )
    session.add(evidence)
    session.flush()

    dna = ProductDna(
        product_id=product.id,
        version=1,
        input_kinds=["text"],
        summary="Laptop portátil, 14 pulgadas, 8 GB RAM, peso 1.4 kg.",
        evidence_id=evidence.id,
        confidence=Decimal("0.9100"),
        model_provider="anthropic",
        **syn,
    )
    session.add(dna)
    session.flush()

    session.add_all(
        [
            ProductAttribute(
                product_dna_id=dna.id,
                name="weight_kg",
                value="1.4",
                unit="kg",
                status="EXTRACTED",
                confidence=Decimal("0.9500"),
                evidence_reference=evidence.id,
                data_origin=_SYNTHETIC,
            ),
            ProductAttribute(
                product_dna_id=dna.id,
                name="ram_gb",
                value="8",
                unit="GB",
                status="OBSERVED",
                confidence=Decimal("0.9900"),
                data_origin=_SYNTHETIC,
            ),
        ]
    )

    invoice = Invoice(
        client_id=client.id,
        supplier_id=supplier.id,
        invoice_number="DEMO-0001",
        invoice_date=date(2026, 2, 10),
        incoterm="FOB",
        currency="USD",
        total_amount=Decimal("5000.000000"),
        total_amount_currency="USD",
        **syn,
    )
    session.add(invoice)
    session.flush()

    session.add(
        InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            line_number=1,
            description='Laptop Demo 14" 8GB',
            quantity=Decimal("10.000000"),
            unit_of_measure="PZA",
            country_of_origin="CN",
            unit_price=Decimal("500.000000"),
            unit_price_currency="USD",
            line_total=Decimal("5000.000000"),
            line_total_currency="USD",
            **syn,
        )
    )
    session.add(Cove(invoice_id=invoice.id, cove_number="COVEDEMO0001", cove_type="E", **syn))

    pedimento = Pedimento(
        client_id=client.id,
        pedimento_number="26  47  3801  6000123",
        customs_office="470",
        pedimento_key="A1",
        regime="IMD",
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        entry_date=date(2026, 3, 15),
        currency="MXN",
        exchange_rate=Decimal("17.500000"),
        customs_value=Decimal("1575000.000000"),
        customs_value_currency="MXN",
        is_simulation=True,
        **syn,
    )
    session.add(pedimento)
    session.flush()

    ped_item = PedimentoItem(
        pedimento_id=pedimento.id,
        product_id=product.id,
        line_number=1,
        description='Laptop Demo 14" 8GB',
        declared_fraction_code="84714902",  # fracción declarada errónea a propósito
        declared_nico_code="00",
        tariff_fraction_id=fraction.id,
        nico_id=nico.id,
        quantity=Decimal("10.000000"),
        commercial_unit="PZA",
        country_of_origin="CN",
        customs_value=Decimal("1575000.000000"),
        customs_value_currency="MXN",
        applied_nom_codes=[],
        **syn,
    )
    session.add(ped_item)
    session.flush()

    decision = ClassificationDecision(
        product_id=product.id,
        product_dna_id=dna.id,
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="RESOLVED",
        chapter="84",
        heading="8471",
        subheading="847130",
        fraction_code="84713001",
        nico_code="00",
        tariff_fraction_id=fraction.id,
        nico_id=nico.id,
        reasoning="RGI 1: la partida 8471 comprende las máquinas portátiles de tratamiento de datos.",
        rgi_path=["RGI1"],
        engine_version="0.1.0",
        evidence_id=evidence.id,
        confidence=Decimal("0.9100"),
        model_provider="anthropic",
        **syn,
    )
    session.add(decision)
    session.flush()

    session.add(
        ClassificationCandidate(
            classification_decision_id=decision.id,
            rank=1,
            fraction_code="84713001",
            nico_code="00",
            tariff_fraction_id=fraction.id,
            confidence=Decimal("0.9100"),
            reasoning="Coincide con la descripción y el peso < 10 kg.",
            is_selected=True,
            data_origin=_SYNTHETIC,
        )
    )

    session.add(
        RiskFinding(
            pedimento_id=pedimento.id,
            pedimento_item_id=ped_item.id,
            classification_decision_id=decision.id,
            finding_type="FRACTION_MISMATCH",
            field="tariff_fraction",
            declared_value="84714902",
            expected_value="84713001",
            severity="HIGH",
            rationale="La fracción declarada corresponde a unidades de proceso, no a la máquina completa.",
            impact_amount=Decimal("0.000000"),
            impact_amount_currency="MXN",
            is_simulation=True,
            evidence_id=evidence.id,
            **syn,
        )
    )

    session.add(
        GroundTruthRecord(
            pedimento_id=pedimento.id,
            pedimento_item_id=ped_item.id,
            error_type="WRONG_FRACTION",
            original_value="84713001",
            mutated_value="84714902",
            expected_detection=True,
            expected_field="tariff_fraction",
            expected_severity="HIGH",
            **syn,
        )
    )

    session.flush()
    return scenario


def main() -> None:
    from sqlalchemy import create_engine

    engine = create_engine(get_settings().sqlalchemy_url)
    with Session(engine) as session:
        scenario = seed(session)
        session.commit()
        print(f"escenario '{scenario.slug}' cargado ({scenario.id})")


if __name__ == "__main__":
    main()
