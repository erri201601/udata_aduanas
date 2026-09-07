"""PARSED -> NORMALIZED -> VALIDATED de la hoja `FA` (Fracciones Arancelarias).

Fuente: el XLSX consolidado que publica SNICE, complementario a la LIGIE
publicada en el DOF (decisión de Persona 1, 2026-09-05): SNICE es cómodo de
parsear, pero el instrumento jurídico es la ley. `source_document` distingue
uno del otro; `source_url`/`content_hash` trazan de dónde se leyó en realidad.

Regla de datos (Persona 1): si la fuente no trae una descripción, la fila se
rechaza — nunca se rellena con texto inventado.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import openpyxl

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from datetime import datetime
    from pathlib import Path

# Fila donde empiezan los datos reales: dos renglones de encabezado
# ("Fracción Arancelaria" / "Descripción" / "Unidad de Medida" / "Arancel %"
# seguido de "IMP." / "EXP."), verificado a mano contra el archivo real.
_PRIMERA_FILA_DATOS = 9

SOURCE_DOCUMENT_TARIFA = "LIGIE 2022 (DOF)"


@dataclass(frozen=True)
class ParsedFraction:
    """Una fracción arancelaria ya normalizada, lista para `TariffFraction`."""

    code: str
    chapter: str
    heading: str
    subheading: str
    description: str
    unit: str | None
    igi_rate: Decimal | None
    ige_rate: Decimal | None
    source_document: str
    source_url: str
    content_hash: str
    retrieved_at: datetime


@dataclass(frozen=True)
class Rejection:
    """Una fila que no pasó la validación, con su motivo (nunca se descarta en silencio)."""

    raw_code: object
    reason: str


@dataclass(frozen=True)
class ParseResult:
    accepted: list[ParsedFraction]
    rejected: list[Rejection]
    rate_warnings: list[str]

    def reconciliation(self, *, declared_by_source: int) -> str:
        """El reporte de 3 números que pidió Persona 1: fuente / parseadas / rechazadas."""
        return (
            f"fuente={declared_by_source} "
            f"parseadas={len(self.accepted)} "
            f"rechazadas={len(self.rejected)} "
            f"(cuadra={declared_by_source == len(self.accepted) + len(self.rejected)})"
        )


def iter_fraccion_rows(path: str | Path) -> Iterator[tuple[object, ...]]:
    """Filas crudas de la hoja `FA`, ya sin los dos renglones de encabezado."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["FA"]
    yield from ws.iter_rows(min_row=_PRIMERA_FILA_DATOS, values_only=True)


def _parse_rate(value: object) -> tuple[Decimal | None, str | None]:
    """`15` -> `0.15` (regla: tasa como fracción, nunca como entero). `Ex.` -> `0`.

    Devuelve `(tasa, advertencia)`. Una tasa vacía es legítima (columna sin
    dato) y no genera advertencia; una tasa presente pero irreconocible sí,
    y el campo queda en `None` en vez de inventar un valor.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if isinstance(value, str) and value.strip().lower().startswith("ex"):
        return Decimal("0"), None
    if isinstance(value, int | float):
        return Decimal(str(value)) / Decimal(100), None
    if isinstance(value, str):
        try:
            return Decimal(value.strip()) / Decimal(100), None
        except InvalidOperation:
            pass
    return None, f"tasa no reconocida: {value!r}"


def _split_code(raw_code: str) -> tuple[str, str, str, str] | None:
    """`8401.10.01` -> (code=84011001, chapter=84, heading=8401, subheading=840110)."""
    digits = raw_code.replace(".", "").strip()
    if len(digits) != 8 or not digits.isdigit():
        return None
    return digits, digits[:2], digits[:4], digits[:6]


def parse_fracciones(
    rows: Iterable[tuple[object, ...]],
    chapters: frozenset[str],
    *,
    source_url: str,
    content_hash: str,
    retrieved_at: datetime,
) -> ParseResult:
    """Filtra por capítulo y normaliza. No escribe nada — eso es DATABASE, aparte."""
    accepted: list[ParsedFraction] = []
    rejected: list[Rejection] = []
    rate_warnings: list[str] = []

    for row in rows:
        raw_code, description, unit, igi_raw, ige_raw = row[2], row[3], row[4], row[5], row[6]
        if raw_code is None:
            continue  # fila en blanco entre secciones del archivo, no es un dato.

        split = _split_code(str(raw_code))
        if split is None:
            rejected.append(Rejection(raw_code, "código no tiene forma NNNN.NN.NN"))
            continue
        code, chapter, heading, subheading = split
        if chapter not in chapters:
            continue

        if description is None or not str(description).strip():
            rejected.append(Rejection(raw_code, "sin descripción en la fuente"))
            continue

        if unit is not None and len(str(unit).strip()) > 4:
            # `unit` es VARCHAR(4) en el schema. Un valor más largo (visto en la
            # fuente: "Prohibida", cuando la operación está vedada) no es un
            # error de formato: es información real que no cabe en esa columna.
            # Se rechaza en vez de truncarla o inventar una unidad.
            rejected.append(Rejection(raw_code, f"unidad no cabe en VARCHAR(4): {unit!r}"))
            continue

        igi_rate, igi_warning = _parse_rate(igi_raw)
        ige_rate, ige_warning = _parse_rate(ige_raw)
        if igi_warning:
            rate_warnings.append(f"{raw_code} (IGI): {igi_warning}")
        if ige_warning:
            rate_warnings.append(f"{raw_code} (IGE): {ige_warning}")

        accepted.append(
            ParsedFraction(
                code=code,
                chapter=chapter,
                heading=heading,
                subheading=subheading,
                description=str(description).strip(),
                unit=(str(unit).strip() if unit else None),
                igi_rate=igi_rate,
                ige_rate=ige_rate,
                source_document=SOURCE_DOCUMENT_TARIFA,
                source_url=source_url,
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )

    return ParseResult(accepted=accepted, rejected=rejected, rate_warnings=rate_warnings)
