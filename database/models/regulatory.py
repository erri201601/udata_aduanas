"""Esquema `regulatory` — dato normativo real (§2 TAREA_P2).

`data_origin` aquí sólo puede ser OFFICIAL / PUBLIC / LICENSED. Cada fila lleva
trazabilidad y vigencia (`RegulatoryMixin`). Nada de esto se inventa: si la
fuente no se pudo recuperar, la fila no existe (§8 maestro).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base
from database.models.enums import (
    IDENTIFIER_CONDITION,
    IDENTIFIER_LEVEL,
    LEGAL_DOCUMENT_KIND,
    REGULATORY_EVENT_KIND,
    SOURCE_KIND,
)
from database.models.mixins import (
    DataOriginMixin,
    RegulatoryMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    check_enum,
)

_SCHEMA = "regulatory"


class LegalSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fuente registrada: DOF, SNICE, Cámara de Diputados, CBP, EBTI, WCO…

    Es el ancla de trazabilidad: el `source_id` de todo el modelo apunta aquí
    (§8 Persona 1). No hereda `DataOriginMixin` — sería una autorreferencia.
    """

    __tablename__ = "legal_sources"
    __table_args__ = ({"schema": _SCHEMA},)

    slug: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    authority: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    jurisdiction: Mapped[str] = mapped_column(sa.String(2), nullable=False, server_default="MX")
    kind: Mapped[str] = mapped_column(check_enum(SOURCE_KIND, "source_kind"), nullable=False)
    base_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class LegalDocument(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Documento jurídico normalizado: LIGIE, Ley Aduanera, RGCE, Anexo 22, NOM…"""

    __tablename__ = "legal_documents"
    __table_args__ = (
        sa.Index("ix_legal_documents_vigencia", "short_name", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    short_name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    kind: Mapped[str] = mapped_column(
        check_enum(LEGAL_DOCUMENT_KIND, "legal_document_kind"), nullable=False
    )
    document_number: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    language: Mapped[str] = mapped_column(sa.String(2), nullable=False, server_default="es")
    reform_reference: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    full_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class LegalRule(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Unidad citable de un documento: un artículo, una regla RGCE, una RGI."""

    __tablename__ = "legal_rules"
    __table_args__ = (
        sa.Index("ix_legal_rules_vigencia", "rule_number", "valid_from", "valid_to"),
        sa.UniqueConstraint(
            "legal_document_id",
            "rule_number",
            "valid_from",
            name="uq_legal_rules_document_rule_valid_from",
        ),
        {"schema": _SCHEMA},
    )

    legal_document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.legal_documents.id", ondelete="RESTRICT"), nullable=False
    )
    rule_number: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    heading_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Marca la regla como una de las Reglas Generales de Interpretación (RGI 1..6).
    rgi_reference: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    # Las notas de reforma/adición/derogación que justifican `valid_from` y
    # `valid_to` (p. ej. "Inciso reformado DOF 19-11-2025") no viven en
    # `text`: se extraen para calcular la vigencia y se descartan del cuerpo
    # para no ensuciarlo con anotaciones a media frase. Sin guardarlas en
    # algún lado, la vigencia de la fila no es verificable contra su propio
    # contenido (hallazgo de Persona 3, 2026-09-08: una fila puede decir que
    # rige desde 2025 sin que su texto contenga nada que lo explique). NULL
    # cuando no hubo ninguna nota (el artículo no se ha tocado desde que se
    # promulgó el documento).
    reform_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class TariffFraction(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Fracción arancelaria mexicana (8 dígitos).

    El código va como `VARCHAR`, nunca entero: los ceros a la izquierda importan.
    `chapter`/`heading`/`subheading`/`code` se guardan por separado para poder
    consultar por nivel (§4 TAREA_P2).
    """

    __tablename__ = "tariff_fractions"
    __table_args__ = (
        sa.Index("ix_tariff_fractions_vigencia", "code", "valid_from", "valid_to"),
        sa.Index("ix_tariff_fractions_niveles", "chapter", "heading", "subheading"),
        sa.UniqueConstraint("code", "valid_from", name="uq_tariff_fractions_code_valid_from"),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    chapter: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    heading: Mapped[str] = mapped_column(sa.String(4), nullable=False)
    subheading: Mapped[str] = mapped_column(sa.String(6), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(sa.String(4), nullable=True)
    # Tasas como fracción (0.16, no 16) — §2 TAREA_P2.
    igi_rate: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 6), nullable=True)
    ige_rate: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 6), nullable=True)
    legal_document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.legal_documents.id", ondelete="RESTRICT"), nullable=True
    )
    # Qué tan específico es `description` frente a sus hermanas bajo la misma
    # subpartida/partida (RGI 3 a)). Mayor = más específico. 0 = catch-all
    # ("Los demás"/"Las demás"). Calculado por `ingestion.snice.tariff`, nunca
    # a mano — ver ahí la heurística exacta. Sin esto, TariffCatalog no puede
    # desempatar y todo cae a HUMAN_REVIEW_REQUIRED (Persona 1, 2026-09-07).
    specificity: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")


class TariffHeading(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Partida (4 dígitos) o subpartida (6) de la LIGIE — nodo de la
    nomenclatura POR ENCIMA de la fracción (ADR 0002).

    Tabla separada de `tariff_fractions` a propósito: `code` ahí es
    `VARCHAR(8)` con `subheading NOT NULL`, así que una fila de 4 o 6
    dígitos tendría que falsificar la subpartida — y `TariffCatalogRepository`
    busca por `description ILIKE`, con lo que el motor podría devolver una
    partida como si fuera una fracción real y clasificar contra algo que no
    lo es (inventar fundamento, regla 2). La invariante de esta tabla es
    "nodo de la nomenclatura", nunca "resultado de clasificación":
    `classify_product` sigue devolviendo sólo códigos de `tariff_fractions`.
    """

    __tablename__ = "tariff_headings"
    __table_args__ = (
        sa.CheckConstraint("level IN (4, 6)", name="level_valido"),
        sa.CheckConstraint("length(code) = level", name="code_del_largo_del_nivel"),
        sa.Index("ix_tariff_headings_vigencia", "code", "valid_from", "valid_to"),
        sa.UniqueConstraint("code", "valid_from", name="uq_tariff_headings_code_valid_from"),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(6), nullable=False)
    level: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    chapter: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Grupo de guion (ADR 0004) del que cuelga esta subpartida, si alguno —
    # sólo tiene sentido en filas `level = 6`. NULL para la inmensa mayoría:
    # la mayoría de las subpartidas cuelgan directo de su partida, sin un
    # nivel de un guion de por medio.
    #
    # `use_alter=True`: esta FK y la de `TariffHeadingGroup.parent_heading_id`
    # se referencian mutuamente (un grupo apunta a su partida, una subpartida
    # apunta a su grupo) — un ciclo real a nivel de TABLA, aunque nunca a
    # nivel de FILA (un grupo siempre se crea sobre una partida que ya
    # existe; una subpartida siempre se liga a un grupo que ya existe).
    # Sin `use_alter`, SQLAlchemy no puede ordenar las tablas para
    # operaciones genéricas (`Base.metadata.sorted_tables`, que usa
    # `tests/test_canonical_model.py`) y lo dice con un `SAWarning` que
    # advierte que una versión futura lo convertiría en error. La migración
    # ya crea/destruye esta FK por separado con `create_foreign_key`/
    # `drop_constraint` (ver su archivo) — `use_alter=True` es sólo
    # declararle al ORM la misma secuencia que la migración ya hace a mano.
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.tariff_heading_groups.id", ondelete="RESTRICT", use_alter=True),
        nullable=True,
    )


class TariffHeadingGroup(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base
):
    """Nivel de un guion de la LIGIE, sin código propio (ADR 0004).

    Agrupa subpartidas hermanas bajo un encabezado común que el documento no
    numera — p. ej., bajo la partida 7305, "Tubos de los tipos utilizados en
    oleoductos o gasoductos:" agrupa 730511/12/19, y "Los demás, soldados:"
    agrupa 730531/39. Sin este nivel, 730512 ("Los demás, soldados
    longitudinalmente.") y 730531 ("Soldados longitudinalmente.") son
    indistinguibles para el motor — el caso real que abrió el ADR 0004.

    TABLA SEPARADA DE `tariff_headings`, A PROPÓSITO: un grupo no tiene
    código arancelario real (el documento no lo numera), y `tariff_headings`
    existe desde el ADR 0002 con la garantía de que `code` SIEMPRE es un
    código real — `code NOT NULL`, `CHECK (length(code) = level)`. Meter el
    grupo ahí con un código sintético o con `code` nullable debilitaría esa
    garantía para las filas que sí son código real. Con tabla propia, sin
    columna `code` en absoluto, un grupo no puede llegar nunca a
    `TariffCandidate.code` por accidente — por construcción, no por
    disciplina (mismo criterio que separó `tariff_headings` de
    `tariff_fractions` en el ADR 0002).

    `description_hash`, NO `ordinal`, ES LA IDENTIDAD PARA RECARGAR (decisión
    de Persona 1, ADR 0004): si el DOF reforma la 7305 e inserta un grupo
    nuevo a la mitad, todos los `ordinal` posteriores se desplazan, y un
    grupo ya cargado podría aparecer con un `ordinal` distinto en la
    siguiente carga aunque su texto no haya cambiado. Identificar por
    posición renombraría el mismo grupo como si fuera otro. `ordinal` sólo
    sirve para ordenar y mostrar en el orden real del documento — nunca para
    decidir si dos filas son "la misma fila". Ver
    `ingestion.snice.tariff_headings.add_missing_heading_groups`: si al
    recargar aparece el mismo `description_hash` bajo el mismo padre pero
    con `ordinal` distinto al ya guardado, es `NEEDS_VALIDATION` y no se
    toca — un reordenamiento silencioso es una reforma que nadie leyó.

    `content_hash` (de `RegulatoryMixin`) sigue siendo el hash del PDF de
    origen completo, igual que en `tariff_headings` — NO es la identidad de
    este grupo frente a sus hermanos, todos comparten el mismo valor dentro
    de una misma carga. `description_hash` es el campo nuevo para eso.
    """

    __tablename__ = "tariff_heading_groups"
    __table_args__ = (
        sa.Index("ix_tariff_heading_groups_padre", "parent_heading_id", "valid_from", "valid_to"),
        sa.UniqueConstraint(
            "parent_heading_id",
            "description_hash",
            "valid_from",
            name="uq_tariff_heading_groups_padre_hash_valid_from",
        ),
        {"schema": _SCHEMA},
    )

    parent_heading_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.tariff_headings.id", ondelete="RESTRICT"), nullable=False
    )
    # Posición entre hermanos del mismo padre, en el orden real del
    # documento. Posicional, NO arancelario — nunca se usa como identidad
    # (ver docstring de la clase).
    ordinal: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # sha256 de `description` normalizada (`rag.types.hash_contenido`) — la
    # identidad de ESTE grupo frente a sus hermanos, distinta del
    # `content_hash` del PDF completo que hereda de `RegulatoryMixin`.
    description_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)


class Nico(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Número de Identificación Comercial: 2 dígitos más sobre la fracción."""

    __tablename__ = "nicos"
    __table_args__ = (
        sa.Index("ix_nicos_vigencia", "full_code", "valid_from", "valid_to"),
        sa.UniqueConstraint("full_code", "valid_from", name="uq_nicos_full_code_valid_from"),
        {"schema": _SCHEMA},
    )

    tariff_fraction_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.tariff_fractions.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    # Fracción (8) + NICO (2). VARCHAR, nunca entero.
    full_code: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    correlation: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class CustomsOffice(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Aduana y sección aduanera (Apéndice 1, Anexo 22 RGCE).

    `aduana` no basta como llave: es un catálogo de 2 dígitos que se repite
    entre secciones distintas de la misma aduana (Persona 1, 2026-09-08 —
    mismo problema que resolvió Opción B para las 4 tablas del Anexo 22).
    `seccion` es NULL en las ~12 aduanas del documento real que no traen
    número de sección propio (p. ej. instalaciones satélite de la aduana
    17/Matamoros) — es el dato tal como lo publica el DOF, no un hueco de
    parseo.
    """

    __tablename__ = "customs_offices"
    __table_args__ = (
        sa.Index("ix_customs_offices_vigencia", "aduana", "seccion", "valid_from", "valid_to"),
        sa.UniqueConstraint("aduana", "seccion", name="uq_customs_offices_aduana_seccion"),
        {"schema": _SCHEMA},
    )

    aduana: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    seccion: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)


class UnitOfMeasure(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Unidad de medida del pedimento (Apéndice 7, Anexo 22 RGCE).

    `code` se ve numérico (1 = Kilo, 2 = Gramo…) pero va como `VARCHAR`, igual
    que las fracciones: es un código, no una cantidad (Persona 1, 2026-09-08).
    """

    __tablename__ = "units_of_measure"
    __table_args__ = (
        sa.Index("ix_units_of_measure_vigencia", "code", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(2), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)


class PedimentoClave(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Clave de pedimento (Apéndice 2, Anexo 22 RGCE).

    `code` se extrae de forma mecánica y confiable (66 claves verificadas).
    `label` y `supuestos_de_aplicacion` quedan NULL a propósito: el PDF del
    DOF presenta la etiqueta y la lista de supuestos de aplicación en dos
    columnas visuales lado a lado, y `pdftotext -layout` las intercala en el
    mismo renglón de texto sin ningún separador confiable — se probó folio
    por folio (numeral romano como falso punto final, columnas sin hueco
    detectable) y no hay heurística de texto que las separe sin inventar
    contenido. Requiere extracción por coordenadas (p. ej. `pdfplumber` sobre
    las cajas de palabras) o transcripción manual — deuda documentada, mismo
    criterio que las notas de capítulo de la LIGIE.
    """

    __tablename__ = "pedimento_claves"
    __table_args__ = (
        sa.Index("ix_pedimento_claves_vigencia", "code", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(3), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment=(
            "Pendiente de cargar (deuda técnica): el layout de 2 columnas del "
            "PDF impide separar la etiqueta de los supuestos de forma "
            "confiable. NULL = no cargado, nunca 'sin etiqueta'."
        ),
    )
    supuestos_de_aplicacion: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment=(
            "Pendiente de cargar (deuda técnica). Toda clave tiene supuestos "
            "de aplicación en el documento real: NULL significa inequívocamente "
            "'no cargado', nunca 'no tiene' (Persona 1, 2026-09-08)."
        ),
    )


class NonTariffRegulation(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base
):
    """Identificador de regulación o restricción no arancelaria (Apéndice 9).

    `code` se repite entre dependencias que emiten sus propios identificadores
    con la misma clave de 2 caracteres — confirmado en el documento real:
    "C1" y "C6" existen tanto bajo Secretaría de Economía como bajo Secretaría
    de Energía, con significados distintos. La llave natural es
    `(code, issuing_agency)`, no `code` solo.
    """

    __tablename__ = "non_tariff_regulations"
    __table_args__ = (
        sa.Index(
            "ix_non_tariff_regulations_vigencia", "code", "issuing_agency", "valid_from", "valid_to"
        ),
        sa.UniqueConstraint("code", "issuing_agency", name="uq_non_tariff_regulations_code_agency"),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    issuing_agency: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)


class PedimentoIdentifier(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base
):
    """Identificador de pedimento (Apéndice 8, Anexo 22 RGCE).

    No es lo mismo que `NonTariffRegulation` (Apéndice 9, "identificadores de
    regulaciones y restricciones no arancelarias"): son dos catálogos
    distintos del mismo Anexo 22, con sus propias claves de 2 caracteres.

    `level` es la columna "Nivel" del documento (`G`/`P` en las 164 de 174
    entradas que la traen; 10 no la tienen -- ver el propio texto real,
    p. ej. "A1", "C2", "S1": encadenan directo a "Para <clave> señalar:" sin
    pasar por una columna de nivel). NULL ahí es lo que el documento trae,
    no un hueco de parseo.

    `label` y `supuestos_de_aplicacion` SÍ se cargan (a diferencia de
    `PedimentoClave`, que los deja NULL por la misma ambigüedad de columnas):
    se extraen con `pdftotext -bbox-layout` y reparto por intervalo de Y
    (`ingestion.dof.anexo22._texto_por_ancla`, ancla por código: cada línea
    de una columna de texto se asigna al ancla más reciente cuya Y la
    precede), NO con la programación dinámica de
    `ingestion.snice.tariff_headings` -- ese motor asume anclas centradas
    contra la primera oración (modelo de Anexo 22 propiamente dicho); el
    Apéndice 8 alinea el código al TOPE de su fila, un modelo distinto que
    la DP corrompía (texto truncado y donado a la entrada siguiente).
    `complemento_1..3` quedan fuera de este alcance —
    dicen qué VALOR declarar una vez que el identificador aplica, no de qué
    depende que aplique, que es la pregunta que
    `docs/RECONOCIMIENTO_APENDICE_8.md` contestó. Consumidor: el RAG
    (`regulatory.legal_chunks`), igual que las reglas RGCE — no
    `required_identifiers` todavía (decisión de Persona 1, 6-oct: ninguna
    de las claves con condición estructurable tiene lector en el corpus
    real, que es 100% clave de documento A1).
    """

    __tablename__ = "pedimento_identifiers"
    __table_args__ = (
        sa.Index("ix_pedimento_identifiers_vigencia", "code", "level", "valid_from", "valid_to"),
        sa.UniqueConstraint(
            "code", "level", "valid_from", name="uq_pedimento_identifiers_code_level_valid_from"
        ),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    level: Mapped[str | None] = mapped_column(sa.String(1), nullable=True)
    label: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    supuestos_de_aplicacion: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class PedimentoIdentifierRequirement(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base
):
    """Cuándo una operación EXIGE un identificador del Apéndice 8 (ADR 0012).

    `pedimento_identifiers` es el catálogo: qué claves existen. Esta tabla es
    la regla: qué hecho de la operación obliga a declarar cada una. Mismo
    patrón que `FractionNomRequirement` (ADR 0003): clave natural, vigencia y
    procedencia, sin lógica en la tabla.

    SÓLO LO ESTRUCTURABLE

    El reconocimiento del 6-oct (`docs/RECONOCIMIENTO_APENDICE_8.md`) leyó los
    168 «Supuestos de aplicación»: como mucho 12 dependen de algo que el
    Canonical Model conoce —la clave de pedimento o una fracción/NICO—. El
    resto depende de hechos del despacho (¿hubo candado?, ¿despacho
    anticipado?) que no están en ningún campo. Esos NO van aquí: sin campo que
    los capture, una fila sería una regla que nadie puede evaluar.

    Que ninguna fila aplique a una operación NO dice que no exija ningún
    identificador: dice que no exige ninguno de los estructurables.
    """

    __tablename__ = "pedimento_identifier_requirements"
    __table_args__ = (
        sa.UniqueConstraint(
            "identifier_code",
            "condition_kind",
            "condition_value",
            "valid_from",
            name="uq_pedimento_identifier_requirements_fila",
        ),
        sa.Index(
            "ix_pedimento_identifier_requirements_vigencia",
            "condition_kind",
            "condition_value",
            "valid_from",
            "valid_to",
        ),
        {"schema": _SCHEMA},
    )

    identifier_code: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    """La clave del Apéndice 8, p. ej. «V1»."""

    identifier_level: Mapped[str] = mapped_column(
        check_enum(IDENTIFIER_LEVEL, "identifier_level"), nullable=False
    )
    """Dónde se declara: `G` en el pedimento, `P` en la partida. Obligatorio:
    sin saber dónde se declara no se puede comprobar, y una fila que no se
    puede comprobar no se carga."""

    condition_kind: Mapped[str] = mapped_column(
        check_enum(IDENTIFIER_CONDITION, "identifier_condition"), nullable=False
    )
    condition_value: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    """`PEDIMENTO_KEY`: la clave del Apéndice 2 («V1»). `FRACTION`: ocho
    dígitos. `NICO`: los ocho de la fracción y los dos del NICO, juntos
    («9803000101»)."""

    scope_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """El supuesto de aplicación íntegro, tal como lo escribe el Apéndice 8."""


class NomenclatureSynonym(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base
):
    """Puente entre el lenguaje comercial y el de la nomenclatura.

    QUÉ ES Y QUÉ NO ES

    NO es fundamento jurídico y no puede citarse como tal. Es lo mismo que el
    §18 permite hacer a un modelo —«traduce "laptop gamer" a "máquina
    automática para tratamiento de datos"»— escrito de forma determinista y
    auditable en vez de dejado a una salida de LLM.

    Una ficha dice «para conducción de fluidos» y la tarifa dice «de los tipos
    utilizados en oleoductos o gasoductos». Sin puente, el motor no puede casar
    dos textos que hablan de lo mismo, y se niega — correctamente, pero sin
    necesidad.

    POR QUÉ LLEVA `data_origin` COMO TODO LO DEMÁS

    Un sinónimo que alguien escribió no vale lo mismo que uno sacado de las
    Notas Explicativas. Mientras salgan de nuestra cabeza son `SYNTHETIC` y la
    traza lo dice, igual que cualquier otro dato que generamos nosotros (§10).
    El día que un clasificador los valide pasan a `HUMAN_VALIDATED`, y ese
    cambio de una columna es toda la diferencia entre una conjetura y criterio.

    Lo que un sinónimo NUNCA hace es cambiar el fundamento: la decisión se
    sigue sosteniendo en el texto de la tarifa. El puente sólo ayuda a
    ENCONTRARLO.
    """

    __tablename__ = "nomenclature_synonyms"
    __table_args__ = (
        sa.UniqueConstraint(
            "commercial_term",
            "nomenclature_term",
            "valid_from",
            name="uq_nomenclature_synonyms_par",
        ),
        # El modelo canónico exige índice por (clave natural, vigencia) en toda
        # tabla regulatoria: es lo que hace que la regla 5 —filtrar por fecha—
        # no cueste un escaneo en cada clasificación.
        sa.Index(
            "ix_nomenclature_synonyms_vigencia",
            "commercial_term",
            "valid_from",
            "valid_to",
        ),
        {"schema": _SCHEMA},
    )

    commercial_term: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """Como lo dice una ficha técnica o una factura."""

    nomenclature_term: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """Como lo dice la tarifa. Es lo que se añade a la búsqueda."""

    kind: Mapped[str] = mapped_column(
        check_enum(("EQUIVALE", "EXCLUYE"), "kind"), nullable=False, server_default="EQUIVALE"
    )
    """Qué dice este puente sobre los dos términos.

    `EQUIVALE` — hablan de lo mismo. Sirve para ENCONTRAR: una ficha que dice
    «conducción de fluidos» busca también por «oleoductos».

    `EXCLUYE` — no pueden darse a la vez. Sirve para DESCARTAR: una ficha que
    dice «HFW» hace imposible una posición que exige «arco sumergido».

    Los dos nacen de la misma pregunta a un clasificador —«¿son lo mismo?»— y
    por eso viven en la misma tabla. La respuesta «no» vale tanto como el «sí»,
    y hoy se perdía: nadie guardaba los noes.
    """

    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """Por qué. Lo lee quien audite la decisión."""

    answered_by: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """Quién contestó la pregunta que produjo esta fila.

    Nulo mientras sea conjetura nuestra (`SYNTHETIC`). Con nombre, la fila es
    criterio profesional y `data_origin` pasa a `HUMAN_VALIDATED` — y ese
    cambio de una columna es lo que separa una suposición de algo que un
    agente aduanal puede firmar.
    """


class FractionNomRequirement(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base
):
    """Qué NOM exige una fracción — el Anexo 2.4.1 (ADR 0003).

    Tabla propia y no una columna en `tariff_fractions`, por lo mismo que el
    ADR 0002: una fracción puede tener 0, 1 o varias NOM según el numeral y la
    acotación. No es un escalar, y forzarlo perdería la acotación.

    LA ACOTACIÓN DECIDE SI ESTO PUEDE ACUSAR A ALGUIEN

    `scope_note` guarda el «Únicamente: …» tal cual lo escribe el anexo. De 456
    filas cargadas, 306 lo traen: limitan la NOM a un subconjunto de la
    fracción, a veces por producto —sólo leche descremada, dentro de una
    fracción de leche en polvo— y a veces por punto de la norma.

    Una fila CON acotación no puede alimentar `required_nom_codes` sin más:
    `MISSING_NOM` es una acusación contra el agente aduanal, y afirmar una NOM
    que a su mercancía no le aplica es acusar sin fundamento. Las acotadas se
    reportan aparte, para que las lea una persona.
    """

    __tablename__ = "fraction_nom_requirements"
    __table_args__ = (
        sa.UniqueConstraint(
            "fraction_code",
            "nom_code",
            "numeral",
            "valid_from",
            name="uq_fraction_nom_requirements_fila",
        ),
        sa.Index(
            "ix_fraction_nom_requirements_vigencia",
            "fraction_code",
            "valid_from",
            "valid_to",
        ),
        {"schema": _SCHEMA},
    )

    fraction_code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """Ocho dígitos, sin puntos — como `tariff_fractions.code`."""

    nom_code: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    """«NOM-186-SSA1/SCFI-2013», tal como lo nombra el anexo."""

    numeral: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    """1, 2 o 4 — los tabulares. El 3 (etiquetado) tiene otra estructura y
    queda fuera; el 5 (emergencia) está vacío en la versión vigente."""

    scope_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """El «Únicamente: …» íntegro. `None` = la NOM aplica a toda la fracción."""


class ExchangeRate(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Tipo de cambio FIX publicado en el DOF (serie Banxico `SF43718`,
    "Pesos por Dólar. FIX.") — el que exige el artículo 20 de la Ley del
    Banco de México para solventar obligaciones en moneda extranjera
    pagaderas en México, y el que usa un pedimento para convertir el valor
    de una factura en dólares a pesos.

    Sin esta tabla, `core/taxation/money.Money.convert()` nunca tenía de
    dónde sacar la tasa, y `apps/api/routers/pedimentos.py::_valor_esperado`
    comparaba el valor esperado (de la factura, en USD) contra el
    declarado (en MXN) y SIEMPRE reportaba "divisa distinta" — nunca
    comparaba el monto, para ninguna operación real del corpus (invoices
    100% USD, pedimentos 100% MXN, verificado contra la base compartida).

    VIGENCIA, IGUAL QUE CUALQUIER OTRA TABLA DE `regulatory` — y no una
    fila por día suelta: el FIX publicado un viernes sigue vigente el
    sábado, el domingo y cualquier día inhábil hasta que el DOF publique
    el siguiente (la Ley no publica un valor para los días que la Bolsa no
    opera). `valid_to = NULL` mientras sea el más reciente; se cierra a
    `nueva_fecha - 1 día` al cargar el siguiente — mismo patrón exacto que
    `_close_previous_fraction_versions`/`_close_previous_heading_versions`
    (`ingestion.snice.load`), no una invención nueva.
    """

    __tablename__ = "exchange_rates"
    __table_args__ = (
        sa.UniqueConstraint("currency", "valid_from", name="uq_exchange_rates_currency_valid_from"),
        sa.Index("ix_exchange_rates_vigencia", "currency", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    """La divisa EXTRANJERA, p. ej. `"USD"` — nunca `"MXN"`. El tipo de
    cambio siempre se expresa como pesos por 1 unidad de ésta (convención
    de la propia serie de Banxico, "Pesos por Dólar")."""

    rate: Mapped[Decimal] = mapped_column(sa.Numeric(18, 6), nullable=False)
    """Pesos mexicanos por 1 unidad de `currency`. NUMERIC(18,6) — misma
    precisión que `operational.pedimentos.exchange_rate` (§22 maestro)."""


class CompensatoryDuty(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Cuota compensatoria del DOF — resoluciones definitivas de la Secretaría
    de Economía (ADR 0009), no un catálogo único: cada fila sale de SU PROPIA
    resolución, con su `source_url`/`content_hash` propios.

    Mismo patrón que `FractionNomRequirement` (ADR 0003): clave natural +
    vigencia + procedencia, sin lógica en la tabla. El LLM nunca calcula el
    monto de la cuota; sólo lo cita (regla 6 CLAUDE.md) — quien calcula es
    `core/taxation`, igual que IGI/IVA.

    PRIMERA FILA CARGADA, VERIFICADA CONTRA EL TEXTO PRIMARIO (no contra un
    resumen de prensa — ver `docs/adr/0009-cuota-compensatoria-cable-de-acero.md`
    para el porqué de esa distinción): cable de acero originario de China,
    "RESOLUCIÓN final del procedimiento administrativo de examen de vigencia
    de la cuota compensatoria impuesta a las importaciones de cables de
    acero originarias de la República Popular China, independientemente del
    país de procedencia" (expediente EC 32-24, DOF 2026-04-09). 2.58 USD/kg,
    prorrogada 5 años desde el 17-dic-2024 (vence el 17-dic-2029) — la propia
    resolución fija el término, por eso `valid_to` NO es `NULL` aquí como en
    `ExchangeRate`: no es una vigencia abierta que se cierre con la fila
    siguiente, es la fecha que la norma misma declara.

    LA CUOTA SIGUE A LA MERCANCÍA/ORIGEN, NO SÓLO A LA FRACCIÓN LISTADA

    El punto 213 de esa resolución dice, verbatim: "...que ingresan a través
    de las fracciones arancelarias de la TIGIE 7312.10.01, 7312.10.05,
    7312.10.07 y 7312.10.99, **o por cualquier otra**." `fraction_code` guarda
    cada fracción TAL COMO la lista la resolución (una fila por fracción,
    nunca armonizada contra otro catálogo — ver `scope_note`): si una
    mercancía de origen China entra por una fracción no listada aquí, esta
    tabla NO lo sabe decir, y el consumidor debe marcarlo `NEEDS_VALIDATION`,
    no asumir que no aplica.

    EXPORTADOR: `NULL` CASI SIEMPRE SIGNIFICA DOS COSAS DISTINTAS

    Cuando una resolución SÍ nombra exportadores con tasas propias (caso
    descartado de este primer corte: tubería de acero de India, Welspun
    Corp con 81.61 USD/t), `exporter_name = NULL` es la tasa residual
    ("las demás empresas exportadoras"). Cuando la resolución NO distingue
    por exportador en absoluto (caso del cable de China: una sola tasa para
    todo origen China, verificado en el texto), `exporter_name` es `NULL`
    porque no hay nada que distinguir — las dos NO son lo mismo, y
    `scope_note` dice cuál es cuál para cada fila. Se cruza con
    `operational.suppliers.legal_name` por COINCIDENCIA EXACTA normalizada
    (mayúsculas, espacios, puntuación) — nunca aproximada: una coincidencia
    parecida le daría a alguien la tasa de un exportador nombrado por error,
    que sería inventar una exención (decisión de Persona 1, 6-oct).
    """

    __tablename__ = "compensatory_duties"
    __table_args__ = (
        sa.UniqueConstraint(
            "origin_country",
            "fraction_code",
            "exporter_name",
            "valid_from",
            name="uq_compensatory_duties_origin_fraction_exporter_valid_from",
        ),
        sa.Index(
            "ix_compensatory_duties_vigencia",
            "origin_country",
            "fraction_code",
            "valid_from",
            "valid_to",
        ),
        {"schema": _SCHEMA},
    )

    origin_country: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    """ISO-2. La resolución dice "originarias de China" — el ORIGEN, nunca el
    país de procedencia/transbordo (el punto 213 de la resolución del cable
    lo declara "independientemente del país de procedencia")."""

    fraction_code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """Ocho dígitos, sin puntos — tal como la lista LA RESOLUCIÓN, no
    armonizada contra `tariff_fractions` ni contra ningún otro catálogo
    (ver docstring de la clase: la cuota sigue a la mercancía/origen)."""

    exporter_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """`NULL` = sin distinción por exportador en esta resolución, o la tasa
    residual "las demás" cuando sí la hay — `scope_note` dice cuál. Nunca se
    normaliza aquí: la normalización (mayúsculas/espacios/puntuación) para
    cruzar con `operational.suppliers.legal_name` es del lado que consulta,
    no de esta tabla."""

    rate: Mapped[Decimal] = mapped_column(sa.Numeric(18, 6), nullable=False)
    rate_currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    rate_unit: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """Unidad sobre la que aplica `rate` — p. ej. `"KG"`, tal como la
    resolución ("2.58 dólares... por kilogramo"). Calcular el importe exige
    que la cantidad declarada de la partida esté en esta misma unidad; si no
    coincide, el consumidor no convierte solo — `HUMAN_REVIEW_REQUIRED`."""

    scope_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """Aclaración textual de la fila — por qué `exporter_name` es `NULL` en
    este caso concreto, u otra acotación de la resolución que no cabe en las
    columnas de arriba. Mismo criterio que `FractionNomRequirement.scope_note`."""


class CompensatoryDutyListing(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base
):
    """Una fila del Anexo 2.5.1: dónde hay cuota compensatoria (ADR 0017).

    UN ÍNDICE, NO UNA TARIFA

    El anexo lista, por fracción, origen y exportador, las mercancías sujetas a
    cuota compensatoria, con la cuota escrita en prosa. La regla 2.5.3 del
    mismo Acuerdo dice que, si el anexo y la resolución discrepan, prevalece la
    resolución. Por eso aquí la cuota es TEXTO (`duty_text`) y nunca un número:
    el importe sale de `CompensatoryDuty`, que se carga desde la resolución
    leída y verificada (ADR 0009). Esta tabla dice dónde mirar.

    UNA FOTO DE NOVIEMBRE DE 2022

    La versión vigente del anexo es la del DOF 25-nov-2022, en vigor desde el
    12-dic-2022, y no se ha vuelto a actualizar aunque la regla 2.5.4 lo pida
    cada seis meses. Una cuota eliminada o prorrogada después no se refleja
    aquí (por ejemplo, las vajillas de China, eliminada en 2026).
    `latest_resolution_date` es la fecha de la última resolución que el propio
    anexo cita: quien consulte sabe lo vieja que es la referencia.
    """

    __tablename__ = "compensatory_duty_listings"
    __table_args__ = (
        sa.UniqueConstraint(
            "fraction_code",
            "origin_country",
            "product_description",
            "exporter_text",
            "first_resolution_date",
            "valid_from",
            name="uq_compensatory_duty_listings_fila",
            postgresql_nulls_not_distinct=True,
        ),
        sa.Index(
            "ix_compensatory_duty_listings_consulta",
            "origin_country",
            "fraction_code",
            "valid_from",
            "valid_to",
        ),
        {"schema": _SCHEMA},
    )

    product_description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """La columna PRODUCTO, tal cual. La cuota sigue a la mercancía que
    describe la resolución (regla 2.5.1), no sólo a la fracción."""

    fraction_code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """Ocho dígitos, sin puntos. TIGIE 2022, como encabeza el anexo."""

    origin_country: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    """ISO-2 del ORIGEN. «COREA EUA» en el anexo da dos filas."""

    exporter_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """La columna EMPRESAS, tal cual («TODAS LAS DEMÁS EXPORTADORAS», «STUPP
    BROS., INC Y TODAS LAS DEMÁS EXPORTADORAS»…). No se normaliza aquí."""

    applies_to_all_others: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    """El texto de empresas incluye «todas las (demás) exportadoras/empresas»:
    la fila alcanza a un exportador que no se nombra. Si dice «excepto …», la
    excepción está en `exporter_text`."""

    duty_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """La columna CUOTA COMPENSATORIA, verbatim. Porcentajes, dólares por
    unidad, precios de referencia o «no se aplica»: no se convierte a número."""

    scope_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """El texto que el anexo pone antes de cualquier exportador: el alcance o
    la condición del registro entero."""

    resolution_history: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    """Las resoluciones que el anexo cita, en orden: `{"tipo", "fecha"}`."""

    first_resolution_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    """La que originó la cuota. Distingue dos cuotas sobre la misma fracción y
    origen (la tubería sin costura de China tiene una de 2011 y otra de 2014)."""

    latest_resolution_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    """La más reciente que cita el anexo. Lo que pasó después, no lo sabe."""


class ProsecRate(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Tasa de un sector del Decreto PROSEC para una fracción (ADR 0011).

    Mismo patrón que `FractionNomRequirement` y `CompensatoryDuty`: clave
    natural + vigencia + procedencia, sin lógica en la tabla. Lo lee
    `database/repositories/programas.py` para el Opportunity Finder (§23).

    UNA FRACCIÓN PUEDE ESTAR EN VARIOS SECTORES, CON TASAS DISTINTAS

    Por eso la clave natural es `(sector_code, fraction_code, valid_from)` y no
    la fracción sola. Cuál de los sectores aplica depende del importador —en
    qué sector está inscrito—, y eso no es un dato de esta tabla.

    QUE ESTÉ AQUÍ NO DICE QUE EL IMPORTADOR PUEDA USARLO

    Hace falta que esté inscrito en el programa de ese sector, con registro
    vigente en la fecha de la operación. Por eso lo que sale de esta tabla es
    siempre una oportunidad `POTENTIAL` con condiciones, nunca un ahorro.
    """

    __tablename__ = "prosec_rates"
    __table_args__ = (
        # La acotación forma parte de la clave (20-oct): el decreto lista la
        # misma fracción dos veces en un sector con acotaciones opuestas y
        # tasas distintas («Únicamente: …» al 5 %, «Excepto: …» al 10 %).
        sa.UniqueConstraint(
            "sector_code",
            "fraction_code",
            "scope_note",
            "valid_from",
            name="uq_prosec_rates_fila",
            postgresql_nulls_not_distinct=True,
        ),
        sa.Index("ix_prosec_rates_vigencia", "fraction_code", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    sector_code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """El inciso del artículo 4 del Decreto PROSEC tal como lo escribe el
    decreto («I», «XIX»…). Es el código que usan `regla_8a_fractions` y
    `operational.clients.prosec_sector_codes`."""

    sector_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """«Industria Eléctrica», tal como lo nombra el decreto."""

    fraction_code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """Ocho dígitos, sin puntos — como `tariff_fractions.code`."""

    igi_rate: Mapped[Decimal] = mapped_column(sa.Numeric(9, 6), nullable=False)
    """Arancel ad valorem del sector, como fracción (0.05, no 5) — misma
    convención que `tariff_fractions.igi_rate`. «Ex.» (exento) es 0."""

    is_partial: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    """La fracción aparece acotada: el beneficio cubre sólo parte de ella.
    `scope_note` dice cuál. Una fila parcial no se presenta sin la acotación."""

    scope_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """La acotación íntegra, tal como la escribe el decreto. `None` = toda la
    fracción."""


class Regla8aFraction(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """La fracción del capítulo 98 que corresponde a cada sector para la Regla 8ª (ADR 0011).

    La Regla 8ª de las complementarias de la LIGIE permite importar las
    mercancías de un sector por una fracción 9802.00.xx. La TASA de esa
    fracción ya está en `tariff_fractions` —la LIGIE la publica— y no se copia
    aquí: dos copias de una tasa acaban diciendo cosas distintas. Esta tabla
    sólo dice qué fracción 9802 corresponde a qué sector.
    """

    __tablename__ = "regla_8a_fractions"
    __table_args__ = (
        sa.UniqueConstraint(
            "sector_code", "fraction_code", "valid_from", name="uq_regla_8a_fractions_fila"
        ),
        sa.Index("ix_regla_8a_fractions_vigencia", "sector_code", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    sector_code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """El mismo código de sector que `prosec_rates.sector_code`."""

    sector_name: Mapped[str] = mapped_column(sa.Text, nullable=False)

    fraction_code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    """La fracción 9802.00.xx, ocho dígitos sin puntos."""

    scope_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """Exclusiones o acotaciones que la LIGIE o la autorización fijan para el
    sector, íntegras. `None` = no se conocen, no «no hay»."""


class RegulatoryEvent(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Salida del DOF Regulatory Watcher: una publicación relevante y su alcance."""

    __tablename__ = "regulatory_events"
    __table_args__ = (
        sa.Index("ix_regulatory_events_vigencia", "event_kind", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    authority: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    event_kind: Mapped[str] = mapped_column(
        check_enum(REGULATORY_EVENT_KIND, "regulatory_event_kind"), nullable=False
    )
    effective_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False, server_default="{}")
    affected_fraction_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(8)), nullable=False, server_default="{}"
    )
    affected_rule_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=False, server_default="{}"
    )


#: Dimensión del vector de embeddings. 1536 = OpenAI `text-embedding-3-small`,
#: el único proveedor de embeddings ya implementado (core/llm/providers/openai.py).
#: Persona 3 elige el modelo final del RAG; si es otro con otra dimensión, esto
#: cambia con una migración nueva que recree la columna — no hay forma de que
#: una tabla `vector` acepte dos anchos a la vez. ARCHITECTURE_DECISION_REQUIRED
#: si el modelo final no es de 1536.
EMBEDDING_DIM = 1536


class LegalChunkRecord(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """El `ChunkStore` real sobre pgvector que pide `rag/__init__.py` (§27, PR #45).

    `rag.types.LegalChunk` es el contrato en memoria; esta es su fila. La
    vigencia y el `data_origin` van por CHUNK, no por documento — igual que en
    `LegalRule` y por la misma razón (regla 5 CLAUDE.md): el artículo 36-A se
    reformó en 2018 y el 1 viene de 1995, y preguntar qué regía en una fecha
    histórica no puede devolver el texto de hoy.

    `legal_rule_id` liga el chunk a la fila de `LegalRule` de la que salió —
    decisión de Persona 1, 2026-09-09: sin ella, `classification_decisions`
    (que sí une por `legal_rule_ids`) y lo que cita el RAG no tenían cómo
    cruzarse, y el panel de impacto quedaba `trazable: false` para siempre.
    Se resuelve por la TERNA `(legal_document_id, article, valid_from)`, no
    por el par documento/artículo: hoy el par basta porque sólo hay una
    versión cargada de cada artículo, pero este sistema entero está
    construido sobre vigencia por chunk, y en cuanto entren versiones
    históricas el par se vuelve ambiguo. NULLABLE a propósito: un chunk
    puede existir sin fila de `legal_rules` detrás (p. ej. si algún día se
    trocea directo de RAW) — es un dato que hay que mirar, no un hueco que
    se rellena en silencio; `PostgresChunkStore` lo registra con un warning
    cuando pasa.
    """

    __tablename__ = "legal_chunks"
    __table_args__ = (
        # El filtro temporal va en el WHERE, antes de puntuar por similitud
        # (Persona 3, PR #45): sin este índice, cada búsqueda escanearía la
        # tabla entera para descartar lo no vigente antes de poder rankear.
        sa.Index("ix_legal_chunks_vigencia", "valid_from", "valid_to"),
        sa.UniqueConstraint(
            "legal_document_id",
            "article",
            "valid_from",
            name="uq_legal_chunks_document_article_valid_from",
        ),
        sa.Index(
            "ix_legal_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        sa.Index("ix_legal_chunks_legal_rule_id", "legal_rule_id"),
        {"schema": _SCHEMA},
    )

    legal_document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.legal_documents.id", ondelete="RESTRICT"), nullable=False
    )
    legal_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.legal_rules.id", ondelete="RESTRICT"), nullable=True
    )
    # Identificador citable: "36-A", "36-A fracción I", "Transitorio Segundo".
    article: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    heading: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # NULL hasta que se calcule: un chunk se puede insertar antes de vectorizar.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


class ComparableRuling(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Una resolución de clasificación de otra aduana: un caso comparable (ADR 0019).

    NO ES FUNDAMENTO JURÍDICO EN MÉXICO

    El maestro (§11) la pide como «casos internacionales comparables:
    producto → HS6 → razonamiento». Una resolución de CBP dice cómo clasificó
    EE. UU. una mercancía en SU arancel. Sirve para ver qué se consideró y
    cómo se razonó, pero nunca fundamenta una fracción mexicana. Por eso vive
    aquí y no en `legal_chunks`: el RAG jurídico no la puede citar como ley.

    NO SE CONVIERTE HTS10 A TIGIE

    `tariff_codes` guarda los códigos tal como los escribe la autoridad
    (HTSUS, CN/TARIC). Sólo `hs6_codes` se compara con México: los seis
    primeros dígitos son del Sistema Armonizado, comunes a los dos países.
    Más allá de la subpartida, cada país divide a su manera.
    """

    __tablename__ = "comparable_rulings"
    __table_args__ = (
        sa.UniqueConstraint("authority", "ruling_number", name="uq_comparable_rulings_fila"),
        sa.Index("ix_comparable_rulings_hs6", "hs6_codes", postgresql_using="gin"),
        sa.Index(
            "ix_comparable_rulings_vigencia", "authority", "ruling_number", "valid_from", "valid_to"
        ),
        {"schema": _SCHEMA},
    )

    authority: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    """Quién resolvió: `CBP` (EE. UU.). `EBTI` (Unión Europea) cuando se cargue."""

    ruling_number: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    collection: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    """En CBP, `ny` (New York, resoluciones de importación) o `hq` (Headquarters)."""

    ruling_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    subject: Mapped[str] = mapped_column(sa.Text, nullable=False)
    categories: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    tariff_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(32)), nullable=False, server_default="{}"
    )
    """Tal como los escribe la autoridad: «7323.93.0030», «9903.88.03»…"""

    hs6_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(6)), nullable=False, server_default="{}"
    )
    """Los seis dígitos del Sistema Armonizado de cada código, sin puntos.
    Los capítulos 98 y 99 (disposiciones nacionales de EE. UU.) se excluyen:
    no son Sistema Armonizado."""

    full_text: Mapped[str] = mapped_column(sa.Text, nullable=False)

    is_revoked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    """La autoridad la revocó o la dejó sin efecto. Se conserva: saber que un
    criterio se abandonó también es información."""

    revoked_by: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(32)), nullable=False, server_default="{}"
    )
    modified_by: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(32)), nullable=False, server_default="{}"
    )
    related_rulings: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(32)), nullable=False, server_default="{}"
    )
