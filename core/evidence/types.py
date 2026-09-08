"""Tipos del Evidence Contract.

`core/` no importa la capa de persistencia (§29 del maestro). Estos tipos son
propios del dominio; `to_record_fields()` produce un mapeo plano y quien escriba
la fila hace el ensamblado. Es el mismo criterio que siguió Persona 3 en
`core/llm/canonical.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.evidence.kinds import LEGAL_BASIS_KINDS, LEGAL_BASIS_ORIGINS, EvidenceKind


class DocumentRef(BaseModel):
    """Referencia a un documento concreto y verificable.

    `content_hash` es lo que convierte la cita en comprobable: permite
    demostrar que el documento no ha cambiado desde que se leyó. Sin él sólo
    tenemos una URL, y las URLs de gobierno cambian de contenido sin avisar.
    """

    model_config = ConfigDict(frozen=True)

    document: str
    """Nombre del instrumento: 'LIGIE 2022 (DOF)', 'Ley Aduanera', 'RGCE 2026'."""

    article: str | None = None
    """Artículo, regla o fracción específica dentro del documento."""

    url: str | None = None
    """Dónde se obtuvo. Puede ser un render operativo (SNICE) de un
    instrumento cuya autoridad está en otro lado (DOF); por eso `document` y
    `url` son campos distintos."""

    published_at: date | None = None
    content_hash: str | None = None


class LegalRef(BaseModel):
    """Una norma recuperada, lista para convertirse en evidencia.

    Sustituye a la tupla `(DocumentRef, date, str)` que usaba el orquestador.
    Al añadir `data_origin` habrían quedado dos cadenas adyacentes
    —`content_hash` y `data_origin`— que se pueden intercambiar sin que nada
    falle: el resultado sería una norma con el hash en el origen y el origen en
    el hash, y `data_origin` acabaría siendo un sha256 que nunca es
    `SYNTHETIC`, así que la comprobación que estamos añadiendo no dispararía
    jamás. Con campos nombrados eso no puede pasar.
    """

    model_config = ConfigDict(frozen=True)

    document_ref: DocumentRef
    valid_from: date
    content_hash: str
    data_origin: str
    valid_to: date | None = None


class Evidence(BaseModel):
    """Una pieza de respaldo de una afirmación del sistema.

    No se construye directamente: usa `core.evidence.builder`, que impone los
    campos obligatorios de cada tipo. Instanciar esta clase a mano permite
    crear evidencia incompleta, que es justo lo que el contrato evita.
    """

    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind
    summary: str
    """Qué sostiene esta evidencia, en una frase legible por un humano."""

    # ── Fuente jurídica (LEGAL_SOURCE) ───────────────────────────────────────
    source_id: uuid.UUID | None = None
    document_ref: DocumentRef | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    """`None` significa vigente. NUNCA se inventa una fecha de fin (§14)."""
    content_hash: str | None = None
    legal_rule_ids: tuple[uuid.UUID, ...] = ()

    data_origin: str | None = None
    """De dónde salió el contenido: uno de los cinco valores cerrados.

    Obligatorio en `LEGAL_SOURCE` y determinante: `SYNTHETIC` no fundamenta.
    Ver `LEGAL_BASIS_ORIGINS`.
    """

    # ── Salida de modelo (MODEL_OUTPUT) ──────────────────────────────────────
    model_provider: str | None = None
    model_name: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None

    # ── Regla determinista (DETERMINISTIC) ───────────────────────────────────
    rule_id: str | None = None
    engine_version: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)

    # ── Validación humana (HUMAN) ────────────────────────────────────────────
    reviewer: str | None = None
    reviewed_at: datetime | None = None

    # ── Caso comparable (COMPARABLE) ─────────────────────────────────────────
    jurisdiction: str | None = None
    """'US' para CBP CROSS, 'EU' para EBTI, 'WCO' para opiniones."""
    case_ref: str | None = None

    # ── Transversales ────────────────────────────────────────────────────────
    confidence: Decimal | None = None
    excerpt: str | None = None
    """Fragmento literal del que salió la afirmación. Es lo que permite a un
    humano verificar sin volver a la fuente completa."""

    @property
    def is_legal_basis(self) -> bool:
        """¿Puede esta evidencia sostener una afirmación jurídica por sí sola?

        Dos condiciones, no una: el TIPO correcto y un ORIGEN real. Una norma
        sintética cumple todos los campos que exige `LEGAL_SOURCE` —tiene
        `source_id`, `document_ref`, `valid_from` y un `content_hash`
        perfectamente calculable— y aun así no es ley.
        """
        if self.kind not in LEGAL_BASIS_KINDS:
            return False
        return self.data_origin in LEGAL_BASIS_ORIGINS

    @property
    def is_synthetic(self) -> bool:
        """¿El contenido es generado? Se presenta siempre marcado (§10, §33)."""
        return self.data_origin == "SYNTHETIC"

    def covers(self, operation_date: date) -> bool:
        """¿Estaba vigente esta norma en la fecha de la operación? (§14)

        Una evidencia sin `valid_from` no es temporal (una salida de modelo, un
        caso comparable) y no restringe la fecha.
        """
        if self.valid_from is None:
            return True
        if operation_date < self.valid_from:
            return False
        return self.valid_to is None or operation_date <= self.valid_to

    def to_record_fields(self) -> dict[str, Any]:
        """Mapeo plano hacia las columnas de `intelligence.evidence_records`.

        Devuelve un dict y no un modelo de `schemas` a propósito: `core/` no
        debe importar la capa de persistencia (§29). Quien escriba la fila
        ensambla.

        `evidence_kind` no existe todavía como columna — ver la nota en
        `core/evidence/__init__.py`. Se emite igualmente para que el día que
        Persona 2 la añada, el ensamblado ya la traiga.
        """
        refs: list[dict[str, Any]] = []
        if self.document_ref is not None:
            refs.append(self.document_ref.model_dump(mode="json", exclude_none=True))

        hashes: list[str] = []
        if self.content_hash:
            hashes.append(self.content_hash)
        ref_hash = self.document_ref.content_hash if self.document_ref else None
        if ref_hash and ref_hash not in hashes:
            hashes.append(ref_hash)

        campos: dict[str, Any] = {
            "evidence_kind": self.kind.value,
            "summary": self.summary,
            "source_ids": [self.source_id] if self.source_id else [],
            "legal_rule_ids": list(self.legal_rule_ids),
            "document_refs": refs,
            "content_hashes": hashes,
            "engine_version": self.engine_version,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "created_by": _CREATED_BY[self.kind],
        }
        # Sólo cuando consta. La columna es NOT NULL, así que emitir `None`
        # obligaría a todo llamante a sobrescribirlo, y emitir la clave siempre
        # choca con los que ya lo pasan por su cuenta. Quien no lo tenga aquí
        # sigue poniéndolo al ensamblar, como hasta ahora.
        if self.data_origin is not None:
            campos["data_origin"] = self.data_origin
        return campos


#: `created_by` en la tabla admite 16 caracteres y hoy es lo único que
#: distingue el origen. Hasta que exista la columna `evidence_kind`, esta es la
#: proyección; no sustituye al tipo, sólo lo aproxima.
_CREATED_BY: dict[EvidenceKind, str] = {
    EvidenceKind.LEGAL_SOURCE: "engine",
    EvidenceKind.MODEL_OUTPUT: "model",
    EvidenceKind.DETERMINISTIC: "engine",
    EvidenceKind.HUMAN: "human",
    EvidenceKind.COMPARABLE: "engine",
}


def utc_now() -> datetime:
    """Instante actual en UTC. Aislado para poder fijarlo en tests."""
    return datetime.now(UTC)
