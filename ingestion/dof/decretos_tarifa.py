"""Aplica un decreto que modifica la Tarifa: versiones nuevas desde su entrada en vigor (ADR 0023).

LO QUE HACE

Lee la tabla del decreto (fracción · descripción · unidad · IGI · IGE) del HTML
del DOF y, **sólo donde la tasa cambia**, cierra la versión vigente de la
fracción el día anterior a la entrada en vigor y abre una nueva con las tasas
del decreto. La fecha sale del transitorio (`afectacion.vigencia_de`); si no es
inequívoca, no se aplica nada.

LO QUE NO HACE

- No cambia descripciones ni crea fracciones: un decreto que crea o suprime
  fracciones necesita otro tratamiento, y aquí se reporta como «no existe».
- Si el decreto tiene vigencia limitada («cinco años»), la versión nueva acaba
  ese día. Lo que rija después no lo dice el decreto, y no se inventa: queda
  sin versión hasta que se cargue.

LOS NICO VAN CON SU FRACCIÓN

`nicos.tariff_fraction_id` apunta a una versión concreta de la fracción. Una
versión nueva sin NICO dejaría al Espejo y al clasificador sin NICO desde esa
fecha. Se copian los vigentes y los originales se cierran el mismo día.

Uso:
    python -m ingestion.dof.decretos_tarifa --target local --codigo 5800977 --fecha 13/10/2026
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Final

import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from apps.api.logging import con_corrida, registrar
from database.models import Nico, TariffFraction
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.dof.afectacion import vigencia_de
from ingestion.se.tablas_html import cuadricula, tablas
from ingestion.snice import raw

log = structlog.stdlib.get_logger("ingestion.dof.decretos_tarifa")

_FRACCION: Final = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})$")
_CIEN: Final = Decimal(100)


@dataclass(frozen=True)
class TasaDecretada:
    codigo: str
    igi: Decimal | None
    ige: Decimal | None


def _tasa(celda: str) -> Decimal | None:
    """«35» → 0.35; «Ex.» → 0; cualquier otra cosa (AMX, un arancel mixto)
    → `None`: no se aplica lo que no se entiende."""
    texto = celda.strip().rstrip(".").strip()
    if texto.lower() in ("ex", "exento", "exenta"):
        return Decimal(0)
    try:
        return Decimal(texto) / _CIEN
    except InvalidOperation:
        return None


def tasas_del_decreto(html: str) -> list[TasaDecretada]:
    """Las filas de tarifa del decreto: cinco columnas, la primera una fracción.

    Las tablas de cuatro columnas son de otro instrumento (el artículo 5 del
    PROSEC en el decreto del 23-abr-2026) y no se mezclan aquí.
    """
    salida: dict[str, TasaDecretada] = {}
    for tabla in tablas(html):
        for fila in cuadricula(tabla.filas):
            if len(fila) != 5:
                continue
            m = _FRACCION.match(fila[0].strip())
            if not m:
                continue
            codigo = "".join(m.groups())
            salida[codigo] = TasaDecretada(codigo, _tasa(fila[3]), _tasa(fila[4]))
    return list(salida.values())


@dataclass
class Resultado:
    cambiadas: list[str]
    iguales: int
    no_existen: list[str]
    ilegibles: list[str]


def aplicar(
    session: Session,
    tasas: list[TasaDecretada],
    *,
    desde: date,
    hasta: date | None,
    source_url: str,
    source_document: str,
    content_hash: str,
    publicado: date,
    retrieved_at: datetime | None = None,
) -> Resultado:
    """Versiona las fracciones cuya tasa cambia. Idempotente: si ya hay una
    versión que empieza en `desde` con esas tasas, no hace nada."""
    retrieved_at = retrieved_at or datetime.now(UTC)
    r = Resultado(cambiadas=[], iguales=0, no_existen=[], ilegibles=[])
    for t in tasas:
        if t.igi is None:
            r.ilegibles.append(t.codigo)
            continue
        vigente = session.scalars(
            sa.select(TariffFraction).where(
                TariffFraction.code == t.codigo,
                TariffFraction.valid_from <= desde,
                sa.or_(TariffFraction.valid_to.is_(None), TariffFraction.valid_to >= desde),
            )
        ).one_or_none()
        if vigente is None:
            r.no_existen.append(t.codigo)
            continue
        ige = t.ige if t.ige is not None else vigente.ige_rate
        if vigente.igi_rate == t.igi and vigente.ige_rate == ige:
            r.iguales += 1
            continue
        if vigente.valid_from == desde:
            # Otra versión del mismo día con otras tasas: no se pisa.
            r.ilegibles.append(t.codigo)
            continue
        nicos = session.scalars(
            sa.select(Nico).where(
                Nico.tariff_fraction_id == vigente.id,
                Nico.valid_from <= desde,
                sa.or_(Nico.valid_to.is_(None), Nico.valid_to >= desde),
            )
        ).all()
        anterior_hasta = vigente.valid_to
        vigente.valid_to = desde - timedelta(days=1)
        nueva = TariffFraction(
            code=vigente.code,
            chapter=vigente.chapter,
            heading=vigente.heading,
            subheading=vigente.subheading,
            description=vigente.description,
            unit=vigente.unit,
            igi_rate=t.igi,
            ige_rate=ige,
            legal_document_id=vigente.legal_document_id,
            specificity=vigente.specificity,
            data_origin="OFFICIAL",
            published_at=publicado,
            valid_from=desde,
            valid_to=hasta if hasta is not None else anterior_hasta,
            source_url=source_url,
            source_document=source_document,
            content_hash=content_hash,
            retrieved_at=retrieved_at,
        )
        session.add(nueva)
        session.flush()
        for n in nicos:
            n.valid_to = desde - timedelta(days=1)
            session.add(
                Nico(
                    tariff_fraction_id=nueva.id,
                    code=n.code,
                    full_code=n.full_code,
                    description=n.description,
                    correlation=n.correlation,
                    data_origin=n.data_origin,
                    published_at=n.published_at,
                    valid_from=desde,
                    valid_to=nueva.valid_to,
                    source_url=n.source_url,
                    source_document=n.source_document,
                    content_hash=n.content_hash,
                    retrieved_at=n.retrieved_at,
                )
            )
        r.cambiadas.append(t.codigo)
    session.flush()
    log.info(
        "dof.decreto_tarifa.aplicado",
        cambiadas=len(r.cambiadas),
        iguales=r.iguales,
        no_existen=len(r.no_existen),
        ilegibles=len(r.ilegibles),
    )
    return r


@dataclass
class Acotado:
    partidas: list[str]
    sin_tasa_previa: int
    conflictos: list[str]


def acotar_hacia_atras(
    session: Session,
    tasas: list[TasaDecretada],
    *,
    desde: date,
    source_url: str,
    source_document: str,
    content_hash: str,
    publicado: date,
    retrieved_at: datetime | None = None,
) -> Acotado:
    """La tasa que el decreto confirma vale DESDE el decreto, no desde 2022.

    La foto de SNICE (20-abr-2026) trae las tasas acumuladas de todos los
    decretos. Si un decreto fija la misma tasa que la versión vigente, esa tasa
    rige desde su entrada en vigor; antes regía otra que no está cargada. La
    versión se parte: el tramo anterior queda con la tasa en `NULL` («no se
    sabe», que el Money Finder ya trata como «sin monto») y el tramo desde el
    decreto lleva sus tasas y sus NICO.

    Lo que NO hace, a propósito: llenar el tramo anterior con un decreto más
    viejo. El índice de SNICE no está completo (falta el de agosto de 2023) y
    hay decretos temporales que expiran: una tasa vieja podría extenderse a
    un periodo en que regía otra. Un tramo ya desconocido se deja así. Una
    tasa conocida distinta de la del decreto es un conflicto y no se toca.

    Se aplica del decreto más reciente al más antiguo: así sólo el último que
    toca cada fracción la parte, y los anteriores encuentran un tramo
    desconocido y no hacen nada.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    r = Acotado(partidas=[], sin_tasa_previa=0, conflictos=[])
    for t in tasas:
        if t.igi is None:
            continue
        vigente = session.scalars(
            sa.select(TariffFraction).where(
                TariffFraction.code == t.codigo,
                TariffFraction.valid_from <= desde,
                sa.or_(TariffFraction.valid_to.is_(None), TariffFraction.valid_to >= desde),
            )
        ).one_or_none()
        if vigente is None or vigente.valid_from == desde:
            continue
        if vigente.igi_rate is None:
            r.sin_tasa_previa += 1
            continue
        ige = t.ige if t.ige is not None else vigente.ige_rate
        if vigente.igi_rate != t.igi or vigente.ige_rate != ige:
            r.conflictos.append(t.codigo)
            continue
        nicos = session.scalars(
            sa.select(Nico).where(
                Nico.tariff_fraction_id == vigente.id,
                Nico.valid_from <= desde,
                sa.or_(Nico.valid_to.is_(None), Nico.valid_to >= desde),
            )
        ).all()
        hasta_original = vigente.valid_to
        nueva = TariffFraction(
            code=vigente.code,
            chapter=vigente.chapter,
            heading=vigente.heading,
            subheading=vigente.subheading,
            description=vigente.description,
            unit=vigente.unit,
            igi_rate=vigente.igi_rate,
            ige_rate=vigente.ige_rate,
            legal_document_id=vigente.legal_document_id,
            specificity=vigente.specificity,
            data_origin="OFFICIAL",
            published_at=publicado,
            valid_from=desde,
            valid_to=hasta_original,
            source_url=source_url,
            source_document=source_document,
            content_hash=content_hash,
            retrieved_at=retrieved_at,
        )
        vigente.valid_to = desde - timedelta(days=1)
        vigente.igi_rate = None
        vigente.ige_rate = None
        session.add(nueva)
        session.flush()
        for n in nicos:
            n.valid_to = desde - timedelta(days=1)
            session.add(
                Nico(
                    tariff_fraction_id=nueva.id,
                    code=n.code,
                    full_code=n.full_code,
                    description=n.description,
                    correlation=n.correlation,
                    data_origin=n.data_origin,
                    published_at=n.published_at,
                    valid_from=desde,
                    valid_to=hasta_original,
                    source_url=n.source_url,
                    source_document=n.source_document,
                    content_hash=n.content_hash,
                    retrieved_at=n.retrieved_at,
                )
            )
        r.partidas.append(t.codigo)
    session.flush()
    log.info(
        "dof.decreto_tarifa.acotado",
        partidas=len(r.partidas),
        sin_tasa_previa=r.sin_tasa_previa,
        conflictos=len(r.conflictos),
    )
    return r


@con_corrida("ingestion.dof.decretos_tarifa")
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["local"])
    parser.add_argument("--codigo", required=True, help="El `codigo` de la nota del DOF.")
    parser.add_argument("--fecha", required=True, help="Fecha de publicación, DD/MM/AAAA.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--hacia-atras",
        action="store_true",
        help="Acota hacia atrás las tasas que el decreto confirma (ADR 0023, parte 2).",
    )
    args = parser.parse_args(argv)

    publicado = datetime.strptime(args.fecha, "%d/%m/%Y").date()
    url = f"https://dof.gob.mx/nota_detalle.php?codigo={args.codigo}&fecha={args.fecha}"
    datos = raw.fetch(url)
    clave = f"dof/decretos_tarifa/{args.codigo}_{raw.content_hash(datos)[:16]}.html"
    minio = raw.local_target()
    captura = raw.store_raw_bytes(datos, source_url=url, minio_key=clave, target=minio)
    raw.verify_stored(target=minio, minio_key=clave)

    html = datos.decode("utf-8", errors="replace")
    desde, hasta = vigencia_de(html, publicado)
    if desde is None:
        raise SystemExit(
            "El transitorio no fija una entrada en vigor inequívoca: no se aplica nada."
        )
    tasas = tasas_del_decreto(html)
    print(
        f"Decreto {args.codigo}: {len(tasas)} fracciones, en vigor {desde}, hasta {hasta or '—'}."
    )

    if args.hacia_atras:
        with Session(create_engine(get_settings().sqlalchemy_url)) as session:
            a = acotar_hacia_atras(
                session,
                tasas,
                desde=desde,
                source_url=url,
                source_document=f"Decreto que modifica la Tarifa, DOF {args.fecha} ({clave})",
                content_hash=captura.content_hash,
                publicado=publicado,
                retrieved_at=captura.retrieved_at,
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        registrar(records=len(a.partidas), errors=len(a.conflictos))
        print(
            f"{'--dry-run: ' if args.dry_run else 'OK (local): '}{len(a.partidas)} acotadas "
            f"desde {desde}, {a.sin_tasa_previa} ya sin tasa previa, "
            f"{len(a.conflictos)} en conflicto {a.conflictos[:10]}."
        )
        return 0

    with Session(create_engine(get_settings().sqlalchemy_url)) as session:
        r = aplicar(
            session,
            tasas,
            desde=desde,
            hasta=hasta,
            source_url=url,
            source_document=f"Decreto que modifica la Tarifa, DOF {args.fecha} ({clave})",
            content_hash=captura.content_hash,
            publicado=publicado,
            retrieved_at=captura.retrieved_at,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    registrar(records=len(r.cambiadas), errors=len(r.no_existen) + len(r.ilegibles))
    print(
        f"{'--dry-run: ' if args.dry_run else 'OK (local): '}{len(r.cambiadas)} versiones nuevas "
        f"({', '.join(r.cambiadas[:10])}), {r.iguales} sin cambio, "
        f"{len(r.no_existen)} no existen, {len(r.ilegibles)} sin tasa legible."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
