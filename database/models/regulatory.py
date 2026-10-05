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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base
from database.models.enums import (
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

    `description`/`supuestos_de_aplicacion`/`complemento_1..3` NO se cargan:
    mismo motivo que dejó a `PedimentoClave.label` sin cargar (ver su
    docstring) -- el layout de columnas múltiples se intercala en el mismo
    renglón de texto sin separador confiable, y aquí es peor: la descripción
    corta de cada clave también se envuelve a la línea siguiente, mezclada
    con fragmentos de "Supuestos de Aplicación" de esa misma fila. `code` y
    `level` sí se extraen con garantía, porque los dos viven siempre en la
    PRIMERA línea de la entrada, antes de que empiece esa mezcla.
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
