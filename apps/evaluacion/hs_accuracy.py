"""Conecta el harness de `hs_accuracy` con el motor de producción, sin escribir.

`core.evaluation` no conoce la base; esto sí, y por eso aquí viven las
garantías que dependen de ella.

NO PERSISTE, Y NO SE CONFÍA EN LA BUENA FE DEL CÓDIGO

La sesión se envuelve en `SesionSoloLectura`, que lanza ante cualquier `add`,
`flush`, `commit` o sentencia DML, y la transacción se declara
`SET TRANSACTION READ ONLY`: aunque alguien añadiera mañana un
`save_classification` en la tubería, Postgres lo rechazaría. Al final, rollback.
El 9 de septiembre una prueba dejó una decisión en la métrica de producción;
esto existe para que no vuelva a pasar.

SIN FUGAS POR EL RAG

Antes de correr se comprueba que el corpus jurídico no contiene rulings. Si
algún día alguien carga CBP CROSS en `legal_documents`, el RAG podría devolver
el propio ruling como fundamento y el número mediría la memoria del índice, no
al motor. Se aborta.

MIDE EL CAMINO DE PRODUCCIÓN

El clasificador es `apps.api.clasificacion.clasificar_borrador`, la misma
función que usa `POST /products/{id}/classify`. El extractor es el
`LlmExtractor` de producción con el proveedor de Anthropic.

CUESTA DINERO

`ejecutar` sin `confirmar=True` sólo devuelve el presupuesto y no llama a
ningún modelo. El lote por defecto es chico a propósito.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, cast

import sqlalchemy as sa
import structlog
from core.evaluation import (
    Clasificacion,
    ExtraccionConUso,
    Reporte,
    Tarifas,
    UsoDeCaso,
    estimar_costo,
    evaluar,
)
from core.llm.registry import build_provider
from core.product_dna.engine import extract
from core.product_dna.llm_extractor import LlmExtractor
from database.models import LegalDocument, TariffFraction
from pydantic import BaseModel

from apps.api.clasificacion import clasificar_borrador

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from core.evaluation import FuenteDeCasos
    from core.llm.base import ModelProvider
    from core.product_dna.types import ProductDnaDraft, SourceDocument
    from sqlalchemy.orm import Session

log = structlog.stdlib.get_logger("apps.evaluacion.hs_accuracy")

#: Precios verificados en la documentación oficial el 2026-09-14.
TARIFAS_VIGENTES: Final = Tarifas(
    entrada_por_mtok=Decimal("2"),
    salida_por_mtok=Decimal("10"),
    embedding_por_mtok=Decimal("0.02"),
    fuente=(
        "Claude Sonnet 5 $2/$10 por MTok (platform.claude.com/docs/en/about-claude/"
        "pricing) · text-embedding-3-small $0.02 por MTok (developers.openai.com/"
        "api/docs/pricing) · consultadas el 2026-09-14"
    ),
)

#: Consumo de referencia por caso. Entrada y salida MEDIDAS: la única extracción
#: real con `claude-sonnet-5` en `intelligence.product_dnas` (1 842 / 316). El
#: embedding es estimado —el proveedor no devuelve su consumo— y pesa menos de
#: una milésima del total. No incluye reintentos: `generate_structured` puede
#: hacer hasta dos intentos, así que el techo es el doble.
USO_DE_REFERENCIA: Final = UsoDeCaso(entrada=1842, salida=316, embedding=100)

#: Lote por defecto: lo bastante chico para que un error de conexión o de
#: formato cueste centavos, no el conjunto entero.
LOTE_INICIAL: Final = 10

#: Marcas de que un documento del corpus jurídico es un ruling.
_MARCAS_DE_RULING: Final = ("%CROSS%", "%RULING%", "%CBP%")

#: Orígenes que cuentan como tarifa vigente real para la fecha mínima.
_ORIGENES_REALES: Final = ("OFFICIAL", "PUBLIC", "LICENSED")

_METODOS_DE_ESCRITURA: Final = frozenset(
    {
        "add",
        "add_all",
        "delete",
        "merge",
        "flush",
        "commit",
        "bulk_save_objects",
        "bulk_insert_mappings",
        "bulk_update_mappings",
    }
)


class EscrituraProhibidaError(RuntimeError):
    """Una evaluación intentó escribir en la base."""


class FugaEnCorpusError(RuntimeError):
    """El corpus jurídico contiene rulings: el número no mediría nada."""


class SesionSoloLectura:
    """Sesión que deja leer y lanza ante cualquier escritura.

    Delegación explícita en vez de herencia: lo que no se conoce pasa tal cual,
    pero los métodos que escriben no llegan nunca a la sesión real.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def __getattr__(self, nombre: str) -> Any:
        if nombre in _METODOS_DE_ESCRITURA:
            raise EscrituraProhibidaError(
                f"una evaluación no escribe: se intentó session.{nombre}()"
            )
        return getattr(self._session, nombre)

    def execute(self, sentencia: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(sentencia, "is_dml", False):
            raise EscrituraProhibidaError("una evaluación no ejecuta INSERT/UPDATE/DELETE")
        return self._session.execute(sentencia, *args, **kwargs)


class Presupuesto(BaseModel):
    """Lo que costaría la corrida. Se devuelve SIN haber llamado a ningún modelo."""

    casos: int
    costo_estimado_usd: Decimal
    techo_con_reintentos_usd: Decimal
    tarifas_fuente: str
    uso_por_caso: UsoDeCaso


def verificar_corpus_sin_rulings(session: Session) -> None:
    """Aborta si algún documento del corpus parece un ruling."""
    sospechosos = session.scalars(
        sa.select(LegalDocument.short_name).where(
            sa.or_(
                *(
                    campo.ilike(marca)
                    for marca in _MARCAS_DE_RULING
                    for campo in (LegalDocument.short_name, LegalDocument.title)
                )
            )
        )
    ).all()
    if sospechosos:
        raise FugaEnCorpusError(
            f"el corpus jurídico contiene lo que parecen rulings: {sorted(set(sospechosos))}. "
            "El RAG podría devolver la respuesta como fundamento."
        )


def fecha_minima_del_catalogo(session: Session) -> date | None:
    """Desde cuándo hay tarifa real vigente. Antes, un fallo mide la carga."""
    return session.scalar(
        sa.select(sa.func.min(TariffFraction.valid_from)).where(
            TariffFraction.data_origin.in_(_ORIGENES_REALES)
        )
    )


def presupuesto(casos: int, *, tarifas: Tarifas = TARIFAS_VIGENTES) -> Presupuesto:
    estimado = estimar_costo(casos, uso_por_caso=USO_DE_REFERENCIA, tarifas=tarifas)
    return Presupuesto(
        casos=casos,
        costo_estimado_usd=estimado,
        techo_con_reintentos_usd=(estimado * 2).quantize(Decimal("0.01")),
        tarifas_fuente=tarifas.fuente,
        uso_por_caso=USO_DE_REFERENCIA,
    )


def extractor_de_produccion() -> Callable[[SourceDocument], ExtraccionConUso]:
    """El extractor real, con Anthropic. El SDK sigue en `core/llm/providers/`."""
    # `cast`: HTTPModelProvider declara `name` como ClassVar y el protocolo lo
    # espera como atributo de instancia. Es la misma instancia en runtime.
    extractor = LlmExtractor(cast("ModelProvider", build_provider(name="anthropic")))

    def extraer(documento: SourceDocument) -> ExtraccionConUso:
        dna = extract(documento, extractor=extractor)
        meta = extractor.last_metadata
        uso = (
            UsoDeCaso(entrada=meta.usage.input_tokens, salida=meta.usage.output_tokens)
            if meta
            else UsoDeCaso()
        )
        return ExtraccionConUso(dna=dna, uso=uso)

    return extraer


def _tokens_estimados(texto: str) -> int:
    """Aproximación de 4 caracteres por token. Declarada como estimación."""
    return len(texto) // 4 + 1


def clasificador_de_produccion(
    session: Session,
) -> Callable[[ProductDnaDraft, date], Clasificacion]:
    """La tubería de `POST /classify`, sobre una sesión que no puede escribir."""

    def clasificar(dna: ProductDnaDraft, fecha: date) -> Clasificacion:
        c = clasificar_borrador(session, dna, operation_date=fecha, trade_flow="IMPORT")
        return Clasificacion(
            codigo=c.outcome.code,
            estado=c.outcome.status.value,
            rgi_path=tuple(p.rule_id for p in c.outcome.trace.steps),
            uso_vectores=c.uso_vectores,
            embedding_tokens=_tokens_estimados(c.consulta_juridica) if c.uso_vectores else 0,
        )

    return clasificar


def ejecutar(
    fuente: FuenteDeCasos,
    session: Session,
    *,
    lote: int = LOTE_INICIAL,
    confirmar: bool = False,
    tarifas: Tarifas = TARIFAS_VIGENTES,
    extraer: Callable[[SourceDocument], ExtraccionConUso] | None = None,
) -> Presupuesto | Reporte:
    """Presupuesto sin `confirmar`; corrida de sólo lectura con él."""
    verificar_corpus_sin_rulings(session)
    if not confirmar:
        return presupuesto(lote, tarifas=tarifas)

    solo_lectura = SesionSoloLectura(session)
    session.execute(sa.text("SET TRANSACTION READ ONLY"))
    try:
        reporte = evaluar(
            fuente.casos(),
            fuente=fuente.nombre,
            extraer=extraer or extractor_de_produccion(),
            clasificar=clasificador_de_produccion(solo_lectura),  # type: ignore[arg-type]
            tarifas=tarifas,
            fecha_minima=fecha_minima_del_catalogo(session),
            limite=lote,
        )
    finally:
        session.rollback()

    log.info(
        "evaluacion.hs_accuracy",
        fuente=fuente.nombre,
        casos=reporte.casos,
        evaluados=reporte.evaluados,
        porcentaje=str(reporte.hs_accuracy.porcentaje),
        costo_usd=str(reporte.costo_usd),
        simulacion=reporte.es_simulacion,
    )
    return reporte


# ─────────────────────────────── LÍNEA DE COMANDOS ───────────────────────────


def _limites(r: Reporte) -> list[str]:
    """Lo que este número NO dice. Va arriba, no en una nota al pie.

    Un número de precisión que se presenta sin sus límites es peor que no
    medir: convence.
    """
    lineas = ["LÍMITES DE ESTE NÚMERO"]
    if r.verdad_de_modelo:
        lineas += [
            "  1. LA VERDAD LA DECIDIÓ UN MODELO. Esto NO es precisión: es",
            "     coincidencia con otro modelo. Lo contrastable del corpus sí está",
            "     verificado contra la LIGIE —fracción, NICO, tasa, UMC: las ocho",
            "     comprobaciones del #84 sobre 180 partidas, cero defectos—. Lo que",
            "     nadie comprobó es el JUICIO de clasificación.",
        ]
    if r.es_simulacion:
        lineas.append("  2. Datos SYNTHETIC: no es una medición de producción (§33).")
    lineas.append("  3. INSUFFICIENT_INFORMATION cuenta como NO acierto en `hs_accuracy`.")
    if r.excluidos:
        lineas.append(f"  4. {sum(r.excluidos.values())} casos no midieron nada:")
        lineas += [f"       {motivo:<34} {n}" for motivo, n in sorted(r.excluidos.items())]
    else:
        lineas.append("  4. Ningún caso quedó excluido.")
    return lineas


def _desacuerdos(r: Reporte) -> list[str]:
    """Donde el motor y el corpus no coinciden. Lo más valioso de la corrida.

    Cada uno que una persona resuelva se vuelve verdad de campo —`HUMAN_VALIDATED`
    compartiendo `product_dna_id`— y ése es el único camino a medir precisión de
    verdad (Persona 1, 23-sep). Por eso salen con su identificador: hay que poder
    ir a mirar la partida.
    """
    fallos = [x for x in r.resultados if x.resultado == "EVALUADO" and x.acierto is False]
    if not fallos:
        return ["DESACUERDOS  ninguno"]
    lineas = [f"DESACUERDOS  {len(fallos)} — aquí es donde hay que mirar"]
    lineas += [
        f"  {x.identificador:<26} esperado {x.hs6_esperado} · motor "
        f"{x.hs6_obtenido or '—':<8} {x.estado_motor or ''}"
        for x in fallos
    ]
    return lineas


def informe(r: Reporte) -> str:
    """El reporte completo: primero lo que no dice, después lo que dice."""
    a, cuando = r.hs_accuracy, r.acierto_cuando_responde
    lineas = [
        f"FUENTE  {r.fuente}",
        f"CASOS   {r.casos} mirados · {r.evaluados} evaluados · {r.errores} con error",
        "",
        *_limites(r),
        "",
        "AGREGADO",
        f"  hs_accuracy            {a.porcentaje if a.porcentaje is not None else '—'} "
        f"({a.aciertos}/{a.comparados})",
        f"  acierto cuando responde {cuando.porcentaje if cuando.porcentaje is not None else '—'} "
        f"({cuando.aciertos}/{cuando.comparados})",
        f"  información insuficiente {r.tasa_insuficiente if r.tasa_insuficiente is not None else '—'} %",
        f"  llegó a RGI 3c           {r.tasa_rgi_3c if r.tasa_rgi_3c is not None else '—'} %",
        f"  búsqueda degradada       {r.tasa_degradacion if r.tasa_degradacion is not None else '—'} %",
        "",
        f"COSTO   ${r.costo_usd} · {r.tarifas_fuente}",
        "",
        *_desacuerdos(r),
    ]
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target",
        default="local",
        choices=["local", "shared"],
        help="Qué Postgres se lee. 'shared' es la base del equipo (ADUANERO_SHARED_URL).",
    )
    parser.add_argument("--escenario", default="corpus_espejo_v1", help="Slug del corpus.")
    parser.add_argument("--lote", type=int, default=LOTE_INICIAL, help="Cuántos casos.")
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="SIN ESTO NO GASTA NADA: devuelve el presupuesto y no llama a ningún modelo.",
    )
    parser.add_argument(
        "--incluir-fichas-recortadas",
        action="store_true",
        help=(
            "Incluye las partidas cuya ficha el corpus recortó. Ahí la respuesta "
            "correcta es pedir revisión humana, así que cuentan como fallo: sirve "
            "para MIRAR qué hace el motor, no para publicar un número."
        ),
    )
    args = parser.parse_args(argv)

    from sqlalchemy.orm import Session as SesionSql

    from apps.api.config import UrlCompartidaAusenteError, url_de_postgres
    from apps.evaluacion.corpus_como_fuente import CorpusEspejo
    from apps.evaluacion.procedencia import linea_de_procedencia, procedencia

    try:
        url = url_de_postgres(args.target)
    except UrlCompartidaAusenteError as error:
        raise SystemExit(str(error)) from error

    with SesionSql(sa.create_engine(url)) as sesion:
        fuente = CorpusEspejo(
            sesion,
            escenario=args.escenario,
            solo_evaluables=not args.incluir_fichas_recortadas,
        )
        try:
            resultado = ejecutar(fuente, sesion, lote=args.lote, confirmar=args.confirmar)
        finally:
            sesion.rollback()

    print(linea_de_procedencia(procedencia()))
    print(f"ÁMBITO  {args.escenario} · base: {args.target}")
    print()
    if isinstance(resultado, Presupuesto):
        print(
            f"PRESUPUESTO  {resultado.casos} casos · ${resultado.costo_estimado_usd} "
            f"(techo con reintentos ${resultado.techo_con_reintentos_usd})"
        )
        print(f"  {resultado.tarifas_fuente}")
        print("\nNo se llamó a ningún modelo. Para correr de verdad: --confirmar")
        return 0
    print(informe(resultado))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
