"""Tests del Canonical Data Model v0.1.

`unit`  — trabajan sobre `Base.metadata` y los schemas Pydantic; no tocan
          infraestructura y corren siempre.
`integration` — exigen un PostgreSQL local (docker compose up -d postgres) con
          `alembic upgrade head` aplicado. Se saltan si no hay conexión.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
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


def test_hay_29_entidades() -> None:
    assert len(_tables()) == 29


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
    ("regulatory", "LegalChunkRecord"),
    ("regulatory", "TariffFraction"),
    ("regulatory", "Nico"),
    ("regulatory", "CustomsOffice"),
    ("regulatory", "UnitOfMeasure"),
    ("regulatory", "PedimentoClave"),
    ("regulatory", "NonTariffRegulation"),
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
    ("intelligence", "ShadowReview"),
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
            # Acotado a la fila de este test. Sin esto, la consulta pregunta por
            # CUALQUIER documento vigente y sólo acierta si la base está vacía:
            # en cuanto se cargó el seed, empezó a devolver el suyo. Un test de
            # integración no puede suponer que es el único habitante de la base.
            LegalDocument.id == doc.id,
            LegalDocument.valid_from <= date(2024, 3, 15),
            (LegalDocument.valid_to.is_(None)) | (LegalDocument.valid_to >= date(2024, 3, 15)),
        )
    )
    assert encontrado is not None and encontrado.id == doc.id


@pytest.mark.integration
def test_legal_rule_rechaza_mismo_documento_numero_y_vigencia_duplicados(
    pg_session: Session,
) -> None:
    """`(legal_document_id, rule_number, valid_from)` es la llave natural: sin
    esto, cargar el mismo documento dos veces duplica en silencio en vez de
    fallar (Task 4, ingesta de la Ley Aduanera — regulatory.legal_rules
    estaba vacía y sin esta guardia)."""
    from database.models import LegalDocument, LegalRule

    doc = LegalDocument(
        title="Ley de prueba",
        short_name="LEY_PRUEBA_UQ",
        kind="LAW",
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pg_session.add(doc)
    pg_session.flush()

    pg_session.add(
        LegalRule(
            legal_document_id=doc.id,
            rule_number="1",
            text="Texto.",
            data_origin="OFFICIAL",
            valid_from=date(2020, 1, 1),
            source_url="https://x",
            content_hash="h",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    pg_session.flush()

    pg_session.add(
        LegalRule(
            legal_document_id=doc.id,
            rule_number="1",
            text="Texto duplicado.",
            data_origin="OFFICIAL",
            valid_from=date(2020, 1, 1),
            source_url="https://x",
            content_hash="h",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    with pytest.raises(sa.exc.IntegrityError, match="uq_legal_rules_document_rule_valid_from"):
        pg_session.flush()


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


@pytest.mark.integration
def test_evidence_kind_acepta_los_cinco_valores_de_core_evidence(pg_session: Session) -> None:
    """`to_record_fields()` (core/evidence) ya produce `evidence_kind`; la fila lo acepta."""
    from core.evidence import builder
    from database.models import EvidenceRecord

    ev = builder.deterministic(
        summary="Regla RGI 1 aplicada.",
        rule_id="RGI1",
        engine_version="rgi-engine-0.1",
    )
    campos = ev.to_record_fields()
    assert campos["evidence_kind"] == "DETERMINISTIC"

    fila = EvidenceRecord(data_origin="OFFICIAL", **campos)
    pg_session.add(fila)
    pg_session.flush()
    pg_session.expire(fila)
    assert fila.evidence_kind == "DETERMINISTIC"


@pytest.mark.integration
def test_check_rechaza_evidence_kind_invalido(pg_session: Session) -> None:
    """El `CHECK` de la base rechaza un valor fuera del vocabulario de `EVIDENCE_KIND`."""
    with pytest.raises(sa.exc.IntegrityError, match="ck_evidence_records_evidence_kind"):
        pg_session.execute(
            sa.text(
                "INSERT INTO intelligence.evidence_records "
                "(data_origin, evidence_kind) VALUES (:data_origin, :evidence_kind)"
            ),
            {"data_origin": "OFFICIAL", "evidence_kind": "INVENTADO"},
        )


# ── Vigencia sin solapar (§14 maestro) — ingestion.snice.load ────────────────


def _fraccion_abierta(pg_session: Session, *, code: str, valid_from: date, data_origin: str):
    from database.models import TariffFraction

    fila = TariffFraction(
        code=code,
        chapter=code[:2],
        heading=code[:4],
        subheading=code[:6],
        description="x",
        data_origin=data_origin,
        valid_from=valid_from,
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pg_session.add(fila)
    pg_session.flush()
    return fila


@pytest.mark.integration
def test_close_previous_fraction_versions_cierra_la_anterior(pg_session: Session) -> None:
    """Dos fuentes que cargan el mismo código no deben dejar dos filas "vigentes hoy"."""
    from ingestion.snice.load import _close_previous_fraction_versions

    vieja = _fraccion_abierta(
        pg_session, code="99999901", valid_from=date(2022, 1, 1), data_origin="SYNTHETIC"
    )

    _close_previous_fraction_versions(pg_session, code="99999901", new_valid_from=date(2022, 6, 7))
    pg_session.expire(vieja)

    assert vieja.valid_to == date(2022, 6, 7) - timedelta(days=1)


@pytest.mark.integration
def test_close_previous_fraction_versions_no_toca_si_no_hay_version_mas_nueva(
    pg_session: Session,
) -> None:
    """Si la fecha nueva no es posterior, no se toca nada — lo demás lo revienta el UNIQUE."""
    from ingestion.snice.load import _close_previous_fraction_versions

    vieja = _fraccion_abierta(
        pg_session, code="99999902", valid_from=date(2022, 6, 7), data_origin="OFFICIAL"
    )

    _close_previous_fraction_versions(pg_session, code="99999902", new_valid_from=date(2022, 6, 7))
    pg_session.expire(vieja)

    assert vieja.valid_to is None


def _nico_abierto(pg_session: Session, *, full_code: str, valid_from: date, data_origin: str):
    from database.models import Nico

    fraccion = _fraccion_abierta(
        pg_session, code=full_code[:8], valid_from=valid_from, data_origin=data_origin
    )
    fila = Nico(
        tariff_fraction_id=fraccion.id,
        code=full_code[8:],
        full_code=full_code,
        description="x",
        data_origin=data_origin,
        valid_from=valid_from,
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pg_session.add(fila)
    pg_session.flush()
    return fila


@pytest.mark.integration
def test_close_previous_nico_versions_cierra_la_anterior(pg_session: Session) -> None:
    from ingestion.snice.load import _close_previous_nico_versions

    vieja = _nico_abierto(
        pg_session, full_code="9999990100", valid_from=date(2022, 1, 1), data_origin="SYNTHETIC"
    )

    _close_previous_nico_versions(
        pg_session, full_code="9999990100", new_valid_from=date(2022, 6, 7)
    )
    pg_session.expire(vieja)

    assert vieja.valid_to == date(2022, 6, 7) - timedelta(days=1)


def _sin_solapes(pg_session: Session, *, tabla: str, columna_codigo: str) -> list:
    """Dos filas del mismo código NO deben cubrir la misma fecha (§14 maestro):

        A.valid_from <= COALESCE(B.valid_to, 'infinity')
        AND B.valid_from <= COALESCE(A.valid_to, 'infinity')

    Sin esto el sistema no puede afirmar qué versión regía una operación.
    `valid_to IS NULL` sólo no basta: dos filas pueden solaparse aunque una
    ya tenga fecha de cierre (Persona 1, 2026-09-08).
    """
    return pg_session.execute(
        sa.text(f"""
            SELECT a.{columna_codigo}, a.valid_from, a.valid_to, b.valid_from, b.valid_to
            FROM {tabla} a
            JOIN {tabla} b
              ON a.{columna_codigo} = b.{columna_codigo} AND a.id < b.id
            WHERE a.valid_from <= COALESCE(b.valid_to, 'infinity'::date)
              AND b.valid_from <= COALESCE(a.valid_to, 'infinity'::date)
        """)
    ).fetchall()


@pytest.mark.integration
def test_ninguna_fraccion_tiene_vigencias_solapadas(pg_session: Session) -> None:
    """Regresión (Persona 1, 2026-09-08): `84713001` tenía dos versiones que se
    solapaban (seed SYNTHETIC vs ingesta OFFICIAL). Guardia general, no solo del
    cargador: sea cual sea el camino por el que entren los datos, esto no debe pasar."""
    assert (
        _sin_solapes(pg_session, tabla="regulatory.tariff_fractions", columna_codigo="code") == []
    )


@pytest.mark.integration
def test_ningun_nico_tiene_vigencias_solapadas(pg_session: Session) -> None:
    """Por `full_code`, NUNCA por `code`: `code` es solo el sufijo de 2 dígitos —
    1129 fracciones comparten el NICO "00" legítimamente, y agrupar por ahí
    produce falsos positivos (el error que cometió Persona 1 al reportar "19
    duplicados" que no existían)."""
    assert _sin_solapes(pg_session, tabla="regulatory.nicos", columna_codigo="full_code") == []


# ── Catálogos de referencia del Anexo 22 ────────────────────────────────────

_ANEXO22_ROW_META = {
    "data_origin": "OFFICIAL",
    "valid_from": date(2026, 1, 15),
    "source_url": "https://dof.gob.mx/abrirPDF.php?anio=2026&archivo=15012026-MAT.pdf",
    "content_hash": "deadbeef",
    "retrieved_at": datetime(2026, 1, 15, tzinfo=UTC),
}


@pytest.mark.integration
def test_customs_office_permite_dos_secciones_null_bajo_la_misma_aduana(
    pg_session: Session,
) -> None:
    """Regresión de dato real: la aduana 17/Matamoros tiene 2 instalaciones sin
    número de sección propio en el DOF. `UNIQUE(aduana, seccion)` no debe
    tratarlas como duplicado — Postgres nunca iguala NULL con NULL."""
    from database.models import CustomsOffice

    pg_session.add_all(
        [
            CustomsOffice(
                aduana="17", seccion=None, name="Puerto el Mezquital.", **_ANEXO22_ROW_META
            ),
            CustomsOffice(
                aduana="17",
                seccion=None,
                name="Aeropuerto Internacional General Servando Canales.",
                **_ANEXO22_ROW_META,
            ),
        ]
    )
    pg_session.flush()  # no debe lanzar IntegrityError


@pytest.mark.integration
def test_customs_office_rechaza_aduana_seccion_duplicada(pg_session: Session) -> None:
    from database.models import CustomsOffice

    # "99"/"9" no es una aduana real: evita chocar con datos reales ya cargados.
    pg_session.add(CustomsOffice(aduana="99", seccion="9", name="Prueba.", **_ANEXO22_ROW_META))
    pg_session.flush()

    pg_session.add(
        CustomsOffice(aduana="99", seccion="9", name="Prueba (duplicado).", **_ANEXO22_ROW_META)
    )
    with pytest.raises(sa.exc.IntegrityError, match="uq_customs_offices_aduana_seccion"):
        pg_session.flush()


@pytest.mark.integration
def test_non_tariff_regulation_permite_mismo_code_en_dos_dependencias(
    pg_session: Session,
) -> None:
    """Dato real confirmado en el Anexo 22: "C1" existe bajo Secretaría de
    Economía y bajo Secretaría de Energía, con significados distintos. La
    llave natural es `(code, issuing_agency)`, no `code` solo. Se prueba con
    un código ficticio ("ZZ") para no depender de si el catálogo real ya
    está cargado en esta base."""
    from database.models import NonTariffRegulation

    pg_session.add_all(
        [
            NonTariffRegulation(
                code="ZZ",
                issuing_agency="Secretaría de Economía",
                description="Permiso previo o automático de importación definitiva/temporal.",
                **_ANEXO22_ROW_META,
            ),
            NonTariffRegulation(
                code="ZZ",
                issuing_agency="Secretaría de Energía",
                description="Permiso previo de importación y exportación de hidrocarburos.",
                **_ANEXO22_ROW_META,
            ),
        ]
    )
    pg_session.flush()  # no debe lanzar IntegrityError


@pytest.mark.integration
def test_non_tariff_regulation_rechaza_code_y_dependencia_duplicados(
    pg_session: Session,
) -> None:
    from database.models import NonTariffRegulation

    pg_session.add(
        NonTariffRegulation(
            code="ZZ",
            issuing_agency="Secretaría de Economía",
            description="Certificado de cupo adicional.",
            **_ANEXO22_ROW_META,
        )
    )
    pg_session.flush()

    pg_session.add(
        NonTariffRegulation(
            code="ZZ",
            issuing_agency="Secretaría de Economía",
            description="Duplicado.",
            **_ANEXO22_ROW_META,
        )
    )
    with pytest.raises(sa.exc.IntegrityError, match="uq_non_tariff_regulations_code_agency"):
        pg_session.flush()


@pytest.mark.integration
def test_pedimento_clave_label_y_supuestos_null_por_omision(pg_session: Session) -> None:
    """`label`/`supuestos_de_aplicacion` en NULL es la deuda documentada, no un
    bug: el layout de 2 columnas del PDF no se puede separar de forma
    confiable (ver docstring de `PedimentoClave`)."""
    from database.models import PedimentoClave

    pg_session.add(PedimentoClave(code="ZZ", **_ANEXO22_ROW_META))
    pg_session.flush()
    pg_session.expire_all()

    fila = pg_session.query(PedimentoClave).filter_by(code="ZZ").one()
    assert fila.label is None
    assert fila.supuestos_de_aplicacion is None


# ── §25 ampliado: los tres tipos del corpus espejo ───────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("tipo", ["WRONG_UNIT", "INCONSISTENT_QUANTITY", "MISSING_TECHNICAL_FIELD"])
def test_la_base_acepta_los_tipos_de_error_del_corpus_espejo(
    pg_session: Session,
    tipo: str,
) -> None:
    """Ampliación aprobada por Persona 1 el 21-sep (migración 79d42f2e1bf2).

    Va contra PostgreSQL y no contra el enum de Python a propósito: el CHECK
    vive en la base. Una lista ampliada en el código con la migración sin
    aplicar da exactamente el mismo verde en los tests y un INSERT que
    revienta el día de la carga.
    """
    pg_session.execute(
        sa.text(
            "insert into intelligence.ground_truth_records (error_type, data_origin) "
            "values (:tipo, 'SYNTHETIC')"
        ),
        {"tipo": tipo},
    )
    pg_session.flush()


@pytest.mark.integration
def test_la_base_rechaza_un_tipo_de_error_fuera_del_catalogo(
    pg_session: Session,
) -> None:
    """Ampliar la lista no es abrirla: el vocabulario sigue siendo cerrado."""
    with pytest.raises(sa.exc.IntegrityError, match="ck_ground_truth_records_error_type"):
        pg_session.execute(
            sa.text(
                "insert into intelligence.ground_truth_records (error_type, data_origin) "
                "values ('CANTIDAD_UMC_INCONSISTENTE', 'SYNTHETIC')"
            )
        )
        pg_session.flush()


# ── El valor en aduana se puede comprobar porque hay dos sumandos ────────────


@pytest.mark.integration
def test_la_partida_guarda_precio_pagado_e_incrementables(pg_session: Session) -> None:
    """Migración 9f5c85042bf1, levantada por Persona 3 el 21-sep.

    Con sólo `customs_value` el Pedimento Espejo no tenía contra qué
    contrastarlo y acababa copiando el declarado como esperado, así que
    `VALUE_MISMATCH` no podía dispararse nunca. Con los dos sumandos, la
    comprobación es la resta del artículo 65 de la Ley Aduanera y no necesita
    ninguna fuente externa.

    Se afirma el tipo además del valor: el dinero es `Decimal` (regla 6), y un
    `float` aquí reaparecería como un centavo de diferencia en una
    comprobación que se compara contra cero.
    """
    from database.models import Client, Pedimento, PedimentoItem

    cliente = Client(legal_name="Importadora de prueba", data_origin="SYNTHETIC")
    pg_session.add(cliente)
    pg_session.flush()

    pedimento = Pedimento(
        client_id=cliente.id,
        pedimento_number="26 47 9999 9999999",
        trade_flow="IMPORT",
        operation_date=date(2026, 9, 21),
        data_origin="SYNTHETIC",
    )
    pg_session.add(pedimento)
    pg_session.flush()

    pg_session.add(
        PedimentoItem(
            pedimento_id=pedimento.id,
            line_number=1,
            description="Tubería de acero al carbono",
            quantity=Decimal("20"),
            data_origin="SYNTHETIC",
            price_paid=Decimal("62265.32"),
            price_paid_currency="MXN",
            incrementables=Decimal("3560.24"),
            incrementables_currency="MXN",
            customs_value=Decimal("65825.56"),
            customs_value_currency="MXN",
        )
    )
    pg_session.flush()
    pg_session.expire_all()

    fila = pg_session.query(PedimentoItem).filter_by(pedimento_id=pedimento.id).one()
    assert isinstance(fila.price_paid, Decimal)
    assert isinstance(fila.incrementables, Decimal)
    assert fila.price_paid + fila.incrementables == fila.customs_value
