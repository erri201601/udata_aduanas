"""Tests del Canonical Data Model v0.1.

`unit`  — trabajan sobre `Base.metadata` y los schemas Pydantic; no tocan
          infraestructura y corren siempre.
`integration` — exigen un PostgreSQL local (docker compose up -d postgres) con
          `alembic upgrade head` aplicado. Se saltan si no hay conexión.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from database.models import Base
from database.models.enums import DATA_ORIGIN
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

_REGULATORY = "regulatory"
_SCHEMAS = {"regulatory", "operational", "intelligence"}
# Única tabla sin dato de negocio propio: es el ancla de trazabilidad.
_SIN_DATA_ORIGIN = {"regulatory.legal_sources"}


def _tables() -> list[sa.Table]:
    return list(Base.metadata.sorted_tables)


def _business_tables() -> list[sa.Table]:
    return [t for t in _tables() if t.fullname not in _SIN_DATA_ORIGIN]


# ── Estructura ──────────────────────────────────────────────────────────────


def test_hay_23_entidades() -> None:
    assert len(_tables()) == 23


def test_todas_las_tablas_en_los_tres_esquemas() -> None:
    fuera = [t.fullname for t in _tables() if t.schema not in _SCHEMAS]
    assert not fuera, f"tablas fuera de los esquemas canónicos: {fuera}"


def test_toda_tabla_tiene_id_uuid_autogenerado() -> None:
    for t in _tables():
        pk = list(t.primary_key.columns)
        assert [c.name for c in pk] == ["id"], t.fullname
        assert isinstance(pk[0].type, sa.Uuid), t.fullname
        assert pk[0].server_default is not None, t.fullname


def test_toda_tabla_tiene_timestamps_tz_aware() -> None:
    for t in _tables():
        for col in ("created_at", "updated_at"):
            c = t.columns[col]
            assert isinstance(c.type, sa.DateTime) and c.type.timezone, f"{t.fullname}.{col}"
            assert not c.nullable, f"{t.fullname}.{col}"


# ── data_origin (§9 maestro) ────────────────────────────────────────────────


def test_toda_tabla_de_negocio_tiene_data_origin() -> None:
    for t in _business_tables():
        assert "data_origin" in t.columns, t.fullname
        assert not t.columns["data_origin"].nullable, t.fullname


def test_data_origin_es_check_con_los_cinco_valores() -> None:
    for t in _business_tables():
        col = t.columns["data_origin"]
        assert isinstance(col.type, sa.Enum), f"{t.fullname}.data_origin no es un Enum"
        assert col.type.native_enum is False, f"{t.fullname}: data_origin usa ENUM nativo"
        assert tuple(col.type.enums) == DATA_ORIGIN, f"{t.fullname}: {col.type.enums}"


def test_ningun_enum_es_nativo_de_postgres() -> None:
    for t in _tables():
        for col in t.columns:
            if isinstance(col.type, sa.Enum):
                assert col.type.native_enum is False, f"{t.fullname}.{col.name}"


# ── Trazabilidad y vigencia regulatoria (§13-14 maestro) ────────────────────


def test_tablas_regulatory_tienen_trazabilidad_y_vigencia() -> None:
    obligatorias = {
        "valid_from",
        "valid_to",
        "source_url",
        "content_hash",
        "retrieved_at",
    }
    for t in _tables():
        if t.schema != _REGULATORY or t.fullname in _SIN_DATA_ORIGIN:
            continue
        faltan = obligatorias - set(t.columns.keys())
        assert not faltan, f"{t.fullname}: faltan {faltan}"
        assert not t.columns["valid_from"].nullable, t.fullname
        # NULL = sigue vigente. Nunca se inventa una fecha de fin.
        assert t.columns["valid_to"].nullable, t.fullname


def test_indice_de_vigencia_por_clave_natural() -> None:
    for t in _tables():
        if t.schema != _REGULATORY or t.fullname in _SIN_DATA_ORIGIN:
            continue
        cubre = any(
            {"valid_from", "valid_to"}.issubset({c.name for c in idx.columns}) for idx in t.indexes
        )
        assert cubre, f"{t.fullname} sin índice (clave, valid_from, valid_to)"


# ── Tipos: dinero, tasas, fracciones (§22 maestro / §2 TAREA_P2) ────────────


def test_ninguna_columna_usa_float() -> None:
    malas = [
        f"{t.fullname}.{c.name}"
        for t in _tables()
        for c in t.columns
        if isinstance(c.type, sa.Float)
    ]
    assert not malas, f"columnas con FLOAT: {malas}"


def test_los_importes_son_numeric_18_6_con_moneda_hermana() -> None:
    for t in _tables():
        for c in t.columns:
            if c.name.endswith(("_amount", "customs_value", "line_total")) and isinstance(
                c.type, sa.Numeric
            ):
                assert (c.type.precision, c.type.scale) == (18, 6), f"{t.fullname}.{c.name}"
                hermana = f"{c.name}_currency"
                assert hermana in t.columns, f"{t.fullname}: falta {hermana}"


def test_las_tasas_arancelarias_son_numeric_9_6() -> None:
    # `exchange_rate` es un factor de conversión, no una tasa: queda fuera.
    for t in _tables():
        for c in t.columns:
            if c.name in {"igi_rate", "ige_rate"}:
                assert isinstance(c.type, sa.Numeric), f"{t.fullname}.{c.name}"
                assert (c.type.precision, c.type.scale) == (9, 6), f"{t.fullname}.{c.name}"


def _string_type(t: sa.types.TypeEngine) -> bool:
    inner = t.item_type if isinstance(t, sa.ARRAY) else t
    return isinstance(inner, sa.String)


def test_las_fracciones_arancelarias_son_texto() -> None:
    objetivo = {"code", "full_code", "chapter", "heading", "subheading"}
    for t in _tables():
        for c in t.columns:
            if "fraction_code" in c.name or c.name in objetivo:
                assert _string_type(c.type), f"{t.fullname}.{c.name} debe ser VARCHAR, no entero"


# ── Schemas Pydantic ────────────────────────────────────────────────────────

_ENTIDADES = [
    ("regulatory", "LegalSource"),
    ("regulatory", "LegalDocument"),
    ("regulatory", "LegalRule"),
    ("regulatory", "TariffFraction"),
    ("regulatory", "Nico"),
    ("regulatory", "RegulatoryEvent"),
    ("operational", "SyntheticScenario"),
    ("operational", "Client"),
    ("operational", "Supplier"),
    ("operational", "Product"),
    ("operational", "Invoice"),
    ("operational", "InvoiceItem"),
    ("operational", "Cove"),
    ("operational", "Pedimento"),
    ("operational", "PedimentoItem"),
    ("intelligence", "EvidenceRecord"),
    ("intelligence", "ProductDna"),
    ("intelligence", "ProductAttribute"),
    ("intelligence", "ClassificationDecision"),
    ("intelligence", "ClassificationCandidate"),
    ("intelligence", "RiskFinding"),
    ("intelligence", "OpportunityFinding"),
    ("intelligence", "GroundTruthRecord"),
]


@pytest.mark.parametrize(("modulo", "nombre"), _ENTIDADES)
def test_cada_entidad_tiene_create_read_update(modulo: str, nombre: str) -> None:
    mod = __import__(f"schemas.{modulo}", fromlist=["x"])
    for sufijo in ("Create", "Read", "Update"):
        assert hasattr(mod, f"{nombre}{sufijo}"), f"falta schemas.{modulo}.{nombre}{sufijo}"


def test_vocabularios_coinciden_entre_modelos_y_schemas() -> None:
    from database.models import enums as me
    from schemas import enums as se

    pares = [
        ("DATA_ORIGIN", "DataOrigin"),
        ("ATTRIBUTE_STATUS", "AttributeStatus"),
        ("CLASSIFICATION_STATUS", "ClassificationStatus"),
        ("FINDING_SEVERITY", "FindingSeverity"),
        ("OPPORTUNITY_STATUS", "OpportunityStatus"),
        ("ERROR_TYPE", "ErrorType"),
        ("TRADE_FLOW", "TradeFlow"),
        ("SOURCE_KIND", "SourceKind"),
        ("LEGAL_DOCUMENT_KIND", "LegalDocumentKind"),
        ("REGULATORY_EVENT_KIND", "RegulatoryEventKind"),
    ]
    for m, s in pares:
        assert tuple(getattr(me, m)) == tuple(x.value for x in getattr(se, s)), m


def test_tarifa_rechaza_igi_rate_float_como_texto_no_decimal() -> None:
    from schemas.regulatory import TariffFractionCreate

    tf = TariffFractionCreate(
        data_origin="OFFICIAL",
        valid_from=date(2022, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        code="84713001",
        chapter="84",
        heading="8471",
        subheading="847130",
        description="x",
        igi_rate=Decimal("0.16"),
    )
    assert isinstance(tf.igi_rate, Decimal)


# ── Seeds ───────────────────────────────────────────────────────────────────


def test_el_seed_solo_produce_filas_sinteticas() -> None:
    from database.seeds.canonical_v0_1 import seed

    session = MagicMock()
    session.scalar.return_value = None

    seed(session)

    agregados: list[object] = []
    for call in session.add.call_args_list:
        agregados.append(call.args[0])
    for call in session.add_all.call_args_list:
        agregados.extend(call.args[0])

    con_origen = [o for o in agregados if hasattr(o, "data_origin")]
    assert con_origen, "el seed no agregó ninguna fila con data_origin"
    for obj in con_origen:
        assert obj.data_origin == "SYNTHETIC", f"{type(obj).__name__} no es SYNTHETIC"


# ── Alembic ─────────────────────────────────────────────────────────────────


def test_una_sola_cabeza_de_migracion() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert len(script.get_heads()) == 1


# ── Integración (requieren PostgreSQL local) ────────────────────────────────


@pytest.fixture
def pg_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Sesión contra el Postgres local. Salta el test si no hay conexión.

    `tests/conftest.py::_isolated_env` (autouse) vacía `POSTGRES_PASSWORD` y
    `ADUANERO_ENV_FILE` para que los tests unit no toquen infraestructura real
    por accidente. Los tests integration sí la necesitan: aquí se deshace ese
    aislamiento sólo para esta sesión, leyendo el `.env` real.

    Cada test corre dentro de una transacción que se revierte al final: no deja
    rastro en la base local.
    """
    from apps.api.config import get_settings

    monkeypatch.setenv("ADUANERO_ENV_FILE", ".env")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    engine = sa.create_engine(get_settings().sqlalchemy_url)
    try:
        conn = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"sin PostgreSQL local: {exc}")
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.integration
def test_check_rechaza_data_origin_invalido(pg_session: Session) -> None:
    """El `CHECK` de la base rechaza un valor inválido.

    Inserta con SQL crudo, sin pasar por el `sa.Enum` del ORM (que ya valida
    en Python): así se prueba de verdad el `CHECK` de PostgreSQL, la última
    línea de defensa si algo escribe sin pasar por los modelos.
    """
    with pytest.raises(sa.exc.IntegrityError, match="ck_legal_documents_data_origin"):
        pg_session.execute(
            sa.text(
                "INSERT INTO regulatory.legal_documents "
                "(title, short_name, kind, data_origin, valid_from, "
                " source_url, content_hash, retrieved_at) "
                "VALUES (:title, :short_name, :kind, :data_origin, :valid_from, "
                " :source_url, :content_hash, :retrieved_at)"
            ),
            {
                "title": "x",
                "short_name": "x",
                "kind": "LAW",
                "data_origin": "INVENTADO",
                "valid_from": date(2022, 1, 1),
                "source_url": "https://x",
                "content_hash": "h",
                "retrieved_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
        )


@pytest.mark.integration
def test_valid_to_null_significa_vigente(pg_session: Session) -> None:
    from database.models import LegalDocument

    doc = LegalDocument(
        title="Ley vigente",
        short_name="LV",
        kind="LAW",
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        valid_to=None,
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pg_session.add(doc)
    pg_session.flush()
    encontrado = pg_session.scalar(
        sa.select(LegalDocument).where(
            LegalDocument.short_name == "LV",
            LegalDocument.valid_from <= date(2024, 3, 15),
            (LegalDocument.valid_to.is_(None)) | (LegalDocument.valid_to >= date(2024, 3, 15)),
        )
    )
    assert encontrado is not None and encontrado.id == doc.id


@pytest.mark.integration
def test_decimal_de_dinero_sobrevive_ida_y_vuelta(pg_session: Session) -> None:
    from database.models import Client, Invoice, Supplier, SyntheticScenario

    scenario = SyntheticScenario(slug="t", name="t", seed=1, data_origin="SYNTHETIC")
    client = Client(legal_name="c", data_origin="SYNTHETIC")
    supplier = Supplier(legal_name="s", country="CN", data_origin="SYNTHETIC")
    pg_session.add_all([scenario, client, supplier])
    pg_session.flush()

    exacto = Decimal("1234567.891234")
    inv = Invoice(
        client_id=client.id,
        supplier_id=supplier.id,
        invoice_number="X-1",
        invoice_date=date(2026, 2, 1),
        currency="USD",
        total_amount=exacto,
        total_amount_currency="USD",
        data_origin="SYNTHETIC",
    )
    pg_session.add(inv)
    pg_session.flush()
    pg_session.expire(inv)
    assert inv.total_amount == exacto
    assert isinstance(inv.total_amount, Decimal)
