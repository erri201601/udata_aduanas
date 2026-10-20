"""Orquestación de todo `synthetic/` (§24 maestro): 5 pedimentos nuevos que
cubren las 3 anomalías nuevas implementadas (`WRONG_IDENTIFIER`,
`INCONSISTENT_SKU_CLASSIFICATION`, `MISSING_INCREMENTABLE`), una
rectificación (§10) y peso neto por partida en cable de acero (ADR 0014,
para que la cuota compensatoria del ADR 0009 pueda llevar importe).

Se generan ENCIMA del corpus de 15 pedimentos ya cargado -- mismos 12
productos de catálogo (`synthetic/catalog.py`), mismos 3 proveedores,
importadores NUEVOS que continúan la secuencia `SIM260101A<letra>` sin
colisionar con los 15 ya cargados (§24, "mismos productos y fichas").

Este módulo NO escribe en ninguna base de datos. Produce el mismo `dict`
que ya consume `ingestion.sintetico.corpus_espejo.parse_corpus` -- cargarlo
es responsabilidad de `ingestion.sintetico.load`, por el plan que Persona 1
tiene que revisar antes (`synthetic/README.md`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from synthetic.catalog import PRODUCT_CATALOG
from synthetic.company_generator import generar_importador
from synthetic.errors import (
    fraccion_alternativa_misma_mercancia,
    identificador_incorrecto,
    incrementable_faltante,
    sku_clasificado_inconsistente,
)
from synthetic.pedimento_generator import PartidaPlan, construir_pedimento
from synthetic.product_generator import generar_partida
from synthetic.supplier_generator import elegir_proveedor

#: `tasa_vigente(session, on_date=..., currency="USD")` real, inyectada por
#: quien llame -- este módulo no abre sesión de base (lo mismo que impide
#: `Money.convert()` buscar su propia tasa, §22 maestro: quien necesita el
#: dato lo pide explícito, nunca lo adivina).
ResolverFX = Callable[[date], Decimal]

#: Cable 12.7-25.4 mm, construcción 6x36 -- 1.15 kg/m es una estimación de
#: ingeniería genérica para ese calibre, NO una ficha técnica verificada de
#: ESTE producto: es dato SYNTHETIC, igual que el resto de esta carga,
#: nunca un hallazgo que pueda citarse como medición real.
_KG_POR_METRO_CABLE_18MM = Decimal("1.15")

_PEDIMENTO_NUMBER_PREFIJO = "26 47 9999 60"


def _numero_pedimento(indice: int) -> str:
    # Los 15 reales usan 0001..0015; se continúa desde 0016.
    return f"{_PEDIMENTO_NUMBER_PREFIJO}{indice:04d}"


@dataclass(frozen=True)
class PlanPedimento:
    document_id: str
    pedimento_number: str
    date_entry: date
    date_payment: date


def construir_corpus_nuevo(*, tasa_de_cambio: ResolverFX) -> dict[str, object]:
    """Los 5 pedimentos nuevos, listos para `parse_corpus`.

    `tasa_de_cambio(fecha)` tiene que devolver el FIX real publicado para
    `fecha` -- sin él no se puede seguir: inventar un tipo de cambio es
    exactamente el bug que esta tarea vino a cerrar (18.33 fijo en el
    corpus original).
    """
    indices = range(16, 21)
    fechas_entrada = [date(2026, 9, 3), date(2026, 9, 5), date(2026, 9, 7), date(2026, 9, 9)]
    # PED_SIM_020 es la rectificación de PED_SIM_016 -- misma fecha de
    # entrada no tendría sentido (se rectifica después), una semana más.
    fechas_entrada.append(date(2026, 9, 16))

    pedimentos: dict[str, dict[str, object]] = {}

    # ── PED_SIM_016: WRONG_IDENTIFIER ──────────────────────────────────
    ped16 = _pedimento_identificador_incorrecto(indices[0], fechas_entrada[0], tasa_de_cambio)
    pedimentos[ped16["document_id"]] = ped16  # type: ignore[index]

    # ── PED_SIM_017/018: INCONSISTENT_SKU_CLASSIFICATION (el par) ──────
    sku_compartido = "SKU-CABLE-18MM-001"
    ped17 = _pedimento_sku(
        indices[1], fechas_entrada[1], tasa_de_cambio, sku=sku_compartido, con_anomalia=False
    )
    ped18 = _pedimento_sku(
        indices[2], fechas_entrada[2], tasa_de_cambio, sku=sku_compartido, con_anomalia=True
    )
    pedimentos[ped17["document_id"]] = ped17  # type: ignore[index]
    pedimentos[ped18["document_id"]] = ped18  # type: ignore[index]

    # ── PED_SIM_019: MISSING_INCREMENTABLE ─────────────────────────────
    ped19 = _pedimento_incrementable_faltante(indices[3], fechas_entrada[3], tasa_de_cambio)
    pedimentos[ped19["document_id"]] = ped19  # type: ignore[index]

    # ── PED_SIM_020: rectificación de PED_SIM_016 (§10) ────────────────
    ped20 = _pedimento_rectificacion(indices[4], fechas_entrada[4], tasa_de_cambio, original=ped16)
    pedimentos[ped20["document_id"]] = ped20  # type: ignore[index]

    return {
        "ground_truth": pedimentos,
        # Los 12 de siempre -- este generador no agrega fichas nuevas.
        "product_specs": {
            pid: {"id": f.id, "name": f.name, "description": f.description, "spec": f.spec}
            for pid, f in PRODUCT_CATALOG.items()
        },
    }


def _pedimento_identificador_incorrecto(
    indice: int, fecha_entrada: date, tasa_de_cambio: ResolverFX
) -> dict[str, object]:
    importador = generar_importador(indice - 16, numero_laboratorio=indice)
    proveedor = elegir_proveedor(0)
    partida_producto = generar_partida(PRODUCT_CATALOG["P006"])
    plan = PartidaPlan(
        partida=partida_producto,
        cantidad_umc=40,
        igi_rate=Decimal("0.35"),
        pais_origen=proveedor.country,
        net_weight_kg=Decimal(40) * _KG_POR_METRO_CABLE_18MM,
        anomalies=(identificador_incorrecto(pedimento_key="V1", identifier_code="V1"),),
    )
    return construir_pedimento(
        document_id=f"PED_SIM_{indice:03d}",
        pedimento_number=_numero_pedimento(indice),
        importador=importador,
        proveedor=proveedor,
        date_entry=fecha_entrada.isoformat(),
        date_payment=fecha_entrada.isoformat(),
        exchange_rate=tasa_de_cambio(fecha_entrada),
        partidas=[plan],
        pedimento_key="V1",
        # La clave V1 exige el identificador V1, de nivel G, y no se declara.
        identifiers={},
    )


def _pedimento_sku(
    indice: int,
    fecha_entrada: date,
    tasa_de_cambio: ResolverFX,
    *,
    sku: str,
    con_anomalia: bool,
) -> dict[str, object]:
    importador = generar_importador(indice - 16, numero_laboratorio=indice)
    proveedor = elegir_proveedor(1)
    partida_producto = generar_partida(PRODUCT_CATALOG["P006"], sku_override=sku)
    fraccion_override = fraccion_alternativa_misma_mercancia("P006") if con_anomalia else None
    anomalies = (
        (
            sku_clasificado_inconsistente(
                sku=sku, fraccion_anterior=PRODUCT_CATALOG["P006"].fraction_code
            ),
        )
        if con_anomalia
        else ()
    )
    plan = PartidaPlan(
        partida=partida_producto,
        cantidad_umc=30,
        igi_rate=Decimal("0.35"),
        pais_origen=proveedor.country,
        net_weight_kg=Decimal(30) * _KG_POR_METRO_CABLE_18MM,
        fraccion_override=fraccion_override,
        anomalies=anomalies,
    )
    return construir_pedimento(
        document_id=f"PED_SIM_{indice:03d}",
        pedimento_number=_numero_pedimento(indice),
        importador=importador,
        proveedor=proveedor,
        date_entry=fecha_entrada.isoformat(),
        date_payment=fecha_entrada.isoformat(),
        exchange_rate=tasa_de_cambio(fecha_entrada),
        partidas=[plan],
    )


def _pedimento_incrementable_faltante(
    indice: int, fecha_entrada: date, tasa_de_cambio: ResolverFX
) -> dict[str, object]:
    importador = generar_importador(indice - 16, numero_laboratorio=indice)
    proveedor = elegir_proveedor(2)
    partida_producto = generar_partida(PRODUCT_CATALOG["P005"])
    # El flete real de esta operación (correcto) es mayor que lo declarado
    # -- la diferencia es, literalmente, el concepto que falta.
    declarado = Decimal("1200.00")
    correcto = Decimal("4800.00")
    plan = PartidaPlan(
        partida=partida_producto,
        cantidad_umc=20,
        igi_rate=Decimal("0.35"),
        pais_origen=proveedor.country,
        net_weight_kg=Decimal(20) * _KG_POR_METRO_CABLE_18MM,
        incrementables_mxn=declarado,
        incrementables_correcto_mxn=correcto,
        anomalies=(incrementable_faltante(correcto=correcto, declarado=declarado),),
    )
    return construir_pedimento(
        document_id=f"PED_SIM_{indice:03d}",
        pedimento_number=_numero_pedimento(indice),
        importador=importador,
        proveedor=proveedor,
        date_entry=fecha_entrada.isoformat(),
        date_payment=fecha_entrada.isoformat(),
        exchange_rate=tasa_de_cambio(fecha_entrada),
        partidas=[plan],
    )


def _pedimento_rectificacion(
    indice: int,
    fecha_entrada: date,
    tasa_de_cambio: ResolverFX,
    *,
    original: dict[str, object],
) -> dict[str, object]:
    importador = generar_importador(indice - 16, numero_laboratorio=indice)
    proveedor = elegir_proveedor(0)
    partida_producto = generar_partida(PRODUCT_CATALOG["P006"])
    plan = PartidaPlan(
        partida=partida_producto,
        cantidad_umc=40,
        igi_rate=Decimal("0.35"),
        pais_origen=proveedor.country,
        net_weight_kg=Decimal(40) * _KG_POR_METRO_CABLE_18MM,
        anomalies=(),
    )
    return construir_pedimento(
        document_id=f"PED_SIM_{indice:03d}",
        pedimento_number=_numero_pedimento(indice),
        importador=importador,
        proveedor=proveedor,
        date_entry=fecha_entrada.isoformat(),
        date_payment=fecha_entrada.isoformat(),
        exchange_rate=tasa_de_cambio(fecha_entrada),
        partidas=[plan],
        pedimento_key="V1",
        rectifies_pedimento_number=original["pedimento_number"],  # type: ignore[arg-type]
        rectification_number=1,
        identifiers={"V1": "corrige la rectificación"},
    )
