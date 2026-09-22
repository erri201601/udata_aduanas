"""Proyecta a un grafo lo que ya está en Postgres (§28).

EL GRAFO NO FUNDAMENTA NADA

Ninguna afirmación jurídica puede citar un nodo. La evidencia sale de
Postgres con su `content_hash` y su vigencia; el grafo dice DÓNDE MIRAR, no
QUÉ ES VERDAD. El día que alguien construya un endpoint que devuelva una cita
legal leída del grafo, habremos roto la regla 1 sin darnos cuenta (Persona 1,
21-sep).

ES UNA PROYECCIÓN, NUNCA UNA FUENTE

Todo nodo sale de una fila que ya existe. Se identifica por el `id` de esa
fila, se escribe con `MERGE` y la proyección es idempotente: correrla dos
veces deja el mismo grafo. Nada vuelve de Neo4j a Postgres.

POR QUÉ HAY DOS NODOS CON EL MISMO CÓDIGO DE FRACCIÓN

Porque en SQL también hay dos filas. `tariff_fractions` versiona por vigencia:
`84713001` tiene una versión cerrada y otra vigente, y cada una es una fila con
su propio `id`. Identificar por `id` da un nodo por versión sin pagar nada por
ello. Quien consulte el grafo filtra por fecha, igual que en el resto del
sistema (§14).

LA VIGENCIA VA EN LOS NODOS, NUNCA EN LAS RELACIONES

Ninguna relación tiene vigencia propia distinta de la de sus extremos: que una
decisión cite una norma ocurre en la fecha de la decisión, y eso ya es una
propiedad suya. Dos copias de la misma verdad se desincronizan.

`data_origin` VIAJA EN CADA NODO QUE VIENE DE UNA TABLA QUE LO TIENE

Con el corpus dentro habrá 180 partidas SYNTHETIC junto a lo real, y la
pregunta que justifica el grafo —qué proveedores concentran fracciones con
hallazgos— las mezclaría sin avisar. Quien consulte puede filtrar. Es la
regla 4: lo sintético nunca se presenta como real. `Country` es la excepción y
no lo lleva: no sale de ninguna tabla, es un código.

EL DINERO NO SE PROYECTA

Ni importes ni tasas. El dinero lo calcula el motor con Decimal (§22), y un
número en el grafo invita a sumarlo en Cypher, que es exactamente como se
empieza a calcular dinero fuera del motor.

LO QUE EL §28 LISTA Y AQUÍ NO ESTÁ, Y QUÉ LO DESBLOQUEA

  NOM              falta la correlación fracción → NOM (Anexo 2.2.1 del
                   Acuerdo de la SE); hoy no existe la fuente
  PROSECSector     falta cargar los decretos PROSEC
  Treaty           falta cargar los tratados y sus reglas de origen
  RegulatoryEvent  la tabla existe y está en 0: el DOF Watcher no ha arrancado
  Manufacturer     sólo hay un nombre en texto libre en `suppliers`, no una
                   entidad con identidad propia

Crear esos nodos vacíos daría un grafo que parece completo y no lo está. Se
añaden cuando exista el dato.

DOS DESVÍOS CONSCIENTES DEL §28

1. El §28 dibuja `SKU --APPEARS_IN--> PEDIMENTO`. En nuestro modelo el SKU es
   una columna de `products`, no una entidad, y lo que de verdad aparece en un
   pedimento es la PARTIDA. Por eso va
   `(Pedimento)-[:HAS_ITEM]->(PedimentoItem)-[:DECLARES]->(TariffFraction)`,
   y `(PedimentoItem)-[:OF_PRODUCT]->(Product)` cierra el camino: en qué
   operaciones apareció un producto se pregunta por ahí.

2. El §28 dibuja `PRODUCT --CLASSIFIED_AS--> FRACTION`. Esa arista afirmaría
   un hecho sin decir quién lo decidió ni cuándo. Aquí la clasificación pasa
   por su decisión —`(Decision)-[:CLASSIFIES]->(Product)` y
   `(Decision)-[:CLASSIFIED_AS]->(TariffFraction)`— que es la que tiene fecha,
   estado y evidencia.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import sqlalchemy as sa
from database.models import (
    ClassificationDecision,
    EvidenceRecord,
    Invoice,
    InvoiceItem,
    LegalDocument,
    LegalRule,
    Nico,
    Pedimento,
    PedimentoItem,
    Product,
    Supplier,
    TariffFraction,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from graph.ports import Grafo

#: Cómo `evidence_records` marca que una evidencia sostiene una decisión.
SUJETO_DECISION: Final = "classification_decision"


@dataclass(frozen=True)
class Resumen:
    """Qué se proyectó. Son los números que hay que enseñar, no declarar."""

    nodos: dict[str, int] = field(default_factory=dict)
    relaciones: dict[str, int] = field(default_factory=dict)

    @property
    def total_nodos(self) -> int:
        return sum(self.nodos.values())

    @property
    def total_relaciones(self) -> int:
        return sum(self.relaciones.values())


def _filas(session: Session, consulta: Any) -> list[dict[str, Any]]:
    """Filas como diccionarios, con los UUID en texto.

    Neo4j no tiene tipo UUID: guardarlo como texto conserva el valor y permite
    volver a Postgres con él. Las fechas sí viajan como fechas — el driver las
    mapea— para que se pueda filtrar por vigencia de verdad y no por cadena.
    """
    return [
        {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in fila._mapping.items()}
        for fila in session.execute(consulta).all()
    ]


def _pares(session: Session, consulta: Any) -> list[tuple[str, str]]:
    return [(str(o), str(d)) for o, d in session.execute(consulta).all() if o and d]


# ── Nodos ────────────────────────────────────────────────────────────────────


def _nodos(session: Session) -> list[tuple[str, list[dict[str, Any]], str]]:
    """Cada etiqueta con sus filas y su clave de identidad."""
    paises: sa.CompoundSelect = sa.union(
        sa.select(Supplier.country.label("code")).where(Supplier.country.isnot(None)),
        sa.select(PedimentoItem.country_of_origin.label("code")).where(
            PedimentoItem.country_of_origin.isnot(None)
        ),
    )
    return [
        (
            "TariffFraction",
            _filas(
                session,
                sa.select(
                    TariffFraction.id,
                    TariffFraction.code,
                    TariffFraction.chapter,
                    TariffFraction.heading,
                    TariffFraction.subheading,
                    TariffFraction.description,
                    TariffFraction.valid_from,
                    TariffFraction.valid_to,
                    TariffFraction.data_origin,
                ),
            ),
            "id",
        ),
        (
            "Nico",
            _filas(
                session,
                sa.select(
                    Nico.id,
                    Nico.code,
                    Nico.full_code,
                    Nico.description,
                    Nico.valid_from,
                    Nico.valid_to,
                    Nico.data_origin,
                ),
            ),
            "id",
        ),
        (
            "LegalRule",
            _filas(
                session,
                sa.select(
                    LegalRule.id,
                    LegalRule.rule_number,
                    LegalRule.path,
                    LegalRule.valid_from,
                    LegalRule.valid_to,
                    LegalRule.data_origin,
                ),
            ),
            "id",
        ),
        (
            "LegalDocument",
            _filas(
                session,
                sa.select(
                    LegalDocument.id,
                    LegalDocument.short_name,
                    LegalDocument.title,
                    LegalDocument.kind,
                    LegalDocument.valid_from,
                    LegalDocument.valid_to,
                    LegalDocument.data_origin,
                ),
            ),
            "id",
        ),
        (
            "Product",
            _filas(
                session,
                sa.select(Product.id, Product.sku, Product.commercial_name, Product.data_origin),
            ),
            "id",
        ),
        (
            "Supplier",
            _filas(
                session,
                sa.select(Supplier.id, Supplier.legal_name, Supplier.country, Supplier.data_origin),
            ),
            "id",
        ),
        ("Country", [{"code": c} for (c,) in session.execute(paises).all() if c], "code"),
        (
            "Pedimento",
            _filas(
                session,
                sa.select(
                    Pedimento.id,
                    Pedimento.pedimento_number,
                    Pedimento.operation_date,
                    Pedimento.is_simulation,
                    Pedimento.data_origin,
                ),
            ),
            "id",
        ),
        (
            "PedimentoItem",
            _filas(
                session,
                sa.select(
                    PedimentoItem.id,
                    PedimentoItem.line_number,
                    PedimentoItem.description,
                    PedimentoItem.declared_fraction_code,
                    PedimentoItem.declared_nico_code,
                    PedimentoItem.country_of_origin,
                    PedimentoItem.data_origin,
                ),
            ),
            "id",
        ),
        (
            "Decision",
            _filas(
                session,
                sa.select(
                    ClassificationDecision.id,
                    ClassificationDecision.status,
                    ClassificationDecision.fraction_code,
                    ClassificationDecision.operation_date,
                    ClassificationDecision.requires_human_review,
                    ClassificationDecision.data_origin,
                ),
            ),
            "id",
        ),
        (
            "Evidence",
            _filas(
                session,
                sa.select(
                    EvidenceRecord.id,
                    EvidenceRecord.evidence_kind,
                    EvidenceRecord.summary,
                    EvidenceRecord.data_origin,
                ),
            ),
            "id",
        ),
    ]


# ── Relaciones ───────────────────────────────────────────────────────────────


def _relaciones(session: Session) -> list[tuple[str, str, str, list[tuple[str, str]]]]:
    """Cada relación con sus extremos. Los nombres del §28 donde el §28 los da."""
    cita = sa.select(
        ClassificationDecision.id, sa.func.unnest(ClassificationDecision.legal_rule_ids)
    ).where(sa.func.cardinality(ClassificationDecision.legal_rule_ids) > 0)

    # La fracción declarada es texto: se resuelve a la VERSIÓN vigente el día de
    # la operación (§14). Si ese día no había ninguna vigente, no hay arista —
    # inventar una apuntaría a una versión que no regía.
    declara = (
        sa.select(PedimentoItem.id, TariffFraction.id)
        .join(Pedimento, Pedimento.id == PedimentoItem.pedimento_id)
        .join(
            TariffFraction,
            sa.and_(
                TariffFraction.code == PedimentoItem.declared_fraction_code,
                TariffFraction.valid_from <= Pedimento.operation_date,
                sa.or_(
                    TariffFraction.valid_to.is_(None),
                    TariffFraction.valid_to >= Pedimento.operation_date,
                ),
            ),
        )
    )

    # Un producto se liga a su proveedor por DOS caminos, y hacen falta los dos.
    # El directo —la línea de factura dice qué producto es— está casi vacío en
    # el corpus de hoy: `invoice_items.product_id` sólo trae 1 de 181. El otro
    # pasa por la partida, que sí lo trae en las 181, y es el mismo camino que
    # el Espejo usa para saber de dónde viene la mercancía. Con sólo el
    # primero, el grafo tenía UNA arista SUPPLIED_BY y las dos mitades
    # —pedimentos por un lado, decisiones y productos por el otro— no se
    # tocaban: ninguna pregunta podía cruzarlas.
    suministra = sa.union(
        sa.select(InvoiceItem.product_id, Invoice.supplier_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(InvoiceItem.product_id.isnot(None), Invoice.supplier_id.isnot(None)),
        sa.select(PedimentoItem.product_id, Invoice.supplier_id)
        .join(InvoiceItem, InvoiceItem.id == PedimentoItem.invoice_item_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(PedimentoItem.product_id.isnot(None), Invoice.supplier_id.isnot(None)),
    )

    return [
        (
            "HAS_NICO",
            "TariffFraction",
            "Nico",
            _pares(session, sa.select(Nico.tariff_fraction_id, Nico.id)),
        ),
        (
            "BELONGS_TO",
            "LegalRule",
            "LegalDocument",
            _pares(session, sa.select(LegalRule.id, LegalRule.legal_document_id)),
        ),
        ("CITES", "Decision", "LegalRule", _pares(session, cita)),
        (
            "CLASSIFIES",
            "Decision",
            "Product",
            _pares(
                session,
                sa.select(ClassificationDecision.id, ClassificationDecision.product_id).where(
                    ClassificationDecision.product_id.isnot(None)
                ),
            ),
        ),
        (
            "CLASSIFIED_AS",
            "Decision",
            "TariffFraction",
            _pares(
                session,
                sa.select(
                    ClassificationDecision.id, ClassificationDecision.tariff_fraction_id
                ).where(ClassificationDecision.tariff_fraction_id.isnot(None)),
            ),
        ),
        (
            "SUPPORTED_BY",
            "Decision",
            "Evidence",
            _pares(
                session,
                sa.select(EvidenceRecord.subject_id, EvidenceRecord.id).where(
                    EvidenceRecord.subject_kind == SUJETO_DECISION
                ),
            ),
        ),
        ("SUPPLIED_BY", "Product", "Supplier", _pares(session, suministra)),
        (
            "HAS_ITEM",
            "Pedimento",
            "PedimentoItem",
            _pares(session, sa.select(PedimentoItem.pedimento_id, PedimentoItem.id)),
        ),
        ("DECLARES", "PedimentoItem", "TariffFraction", _pares(session, declara)),
        # Sin esto el grafo son dos grafos: uno de pedimentos y otro de
        # decisiones sobre productos, sin un solo camino entre ellos. Es la
        # arista que permite preguntar en qué operaciones apareció un producto
        # —lo que el §28 quería decir con `SKU --APPEARS_IN--> PEDIMENTO`, con
        # la partida en lugar del SKU, que es lo que de verdad se declara.
        (
            "OF_PRODUCT",
            "PedimentoItem",
            "Product",
            _pares(
                session,
                sa.select(PedimentoItem.id, PedimentoItem.product_id).where(
                    PedimentoItem.product_id.isnot(None)
                ),
            ),
        ),
    ]


def _paises_de_proveedores(session: Session) -> list[tuple[str, str]]:
    """`LOCATED_IN` no va por id: el país se identifica por su código."""
    return [
        (str(sid), pais)
        for sid, pais in session.execute(
            sa.select(Supplier.id, Supplier.country).where(Supplier.country.isnot(None))
        ).all()
    ]


def proyectar(session: Session, grafo: Grafo) -> Resumen:
    """Vuelca Postgres al grafo. Idempotente: dos corridas dejan lo mismo."""
    nodos: dict[str, int] = {}
    for etiqueta, filas, clave in _nodos(session):
        nodos[etiqueta] = grafo.merge_nodos(etiqueta, filas, clave=clave)

    relaciones: dict[str, int] = {}
    for tipo, origen, destino, pares in _relaciones(session):
        relaciones[tipo] = grafo.merge_relaciones(tipo, origen, destino, pares)

    # `LOCATED_IN` aparte: su destino se identifica por código, no por id.
    relaciones["LOCATED_IN"] = grafo.merge_relaciones(
        "LOCATED_IN",
        "Supplier",
        "Country",
        _paises_de_proveedores(session),
        clave_destino="code",
    )
    return Resumen(nodos=nodos, relaciones=relaciones)
