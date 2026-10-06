"""La máquina de evaluación: encadena las reglas y produce la traza.

DOS ETAPAS, porque así funciona la clasificación de verdad:

    Etapa 1 — determinar la PARTIDA (4 dígitos):  RGI 1 → 2 → 3a → 3b → 3c → 4 → 5
    Etapa 2 — descender a subpartida y FRACCIÓN:  RGI 6

La RGI 6 no compite con las anteriores: se aplica *después*, sobre la partida
ya determinada, y usa las reglas previas *mutatis mutandis* dentro de su nivel.
Modelarlo como una secuencia plana de seis reglas daría el código correcto por
accidente y una traza que no explica nada.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.rgi_engine.results import ClassificationTrace, RGIResult
from core.rgi_engine.rules import RGI1, RGI2, RGI3A, RGI3B, RGI3C, RGI4, RGI5, RGI6
from core.rgi_engine.states import RGIStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.rgi_engine.context import ClassificationContext, TariffCandidate
    from core.rgi_engine.ports import Interpreter, LegalNotes, TariffCatalog
    from core.rgi_engine.rules import RGIRule

ENGINE_VERSION = "0.1.0"

#: Orden de la etapa 1. No es configurable a propósito: la secuencia de las RGI
#: es jurídica, no una preferencia de implementación. Evaluar la 3 antes que la
#: 1 no sería una optimización, sería aplicar mal la norma.
HEADING_RULES: tuple[RGIRule, ...] = (
    RGI1(),
    RGI2(),
    RGI3A(),
    RGI3B(),
    RGI3C(),
    RGI4(),
    RGI5(),
)


def classify(
    context: ClassificationContext,
    *,
    catalog: TariffCatalog,
    notes: LegalNotes,
    interpreter: Interpreter | None = None,
) -> ClassificationTrace:
    """Evalúa la secuencia completa y devuelve la traza.

    Nunca lanza por no poder clasificar: devolver
    `INSUFFICIENT_INFORMATION` o `HUMAN_REVIEW_REQUIRED` con su razón es un
    resultado legítimo, no un error. Los errores se reservan para lo que sí es
    un fallo — un catálogo caído, por ejemplo.
    """
    traza = _clasificar(context, catalog=catalog, notes=notes, interpreter=interpreter)
    return _solo_las_preguntas_que_mueven_algo(
        traza, context, catalog=catalog, notes=notes, interpreter=interpreter
    )


def _solo_las_preguntas_que_mueven_algo(
    traza: ClassificationTrace,
    context: ClassificationContext,
    *,
    catalog: TariffCatalog,
    notes: LegalNotes,
    interpreter: Interpreter | None,
) -> ClassificationTrace:
    """Quita las preguntas cuya respuesta no puede cambiar nada.

    UNA PREGUNTA QUE NO MUEVE NADA ES PEOR QUE NO PREGUNTAR

    Gasta el minuto de la única persona cuyo tiempo no se puede gastar, y
    encima parece trabajo hecho. Simulado el 5-oct sobre la bandeja, de las
    cuatro preguntas vivas dos no cambiaban nada con ninguna respuesta:

        7304  «Tubos y perfiles huecos»                  12 casos (sartén)
        8481  «Artículos de grifería…»                     3 casos (utensilio)

    Contestar «no» descartaba esa partida y quedaban otras tres empatadas. Ni
    el «sí» ni el «no» resolvían. Quince tarjetas pidiendo un minuto a cambio
    de cero.

    SE SIMULA, NO SE ADIVINA

    La forma de saber si una pregunta sirve es la que se usó para encontrar
    las inútiles: hacer la clasificación otra vez como si la persona hubiera
    contestado que no, y mirar si resuelve. Contar candidatas no basta — la
    pregunta de la olla sobre 8481 tenía varias partidas detrás y SÍ servía,
    porque al caer la grifería las demás se resolvían por materia.

    Sólo se simula el «no». El «sí» guarda una equivalencia, que sirve para no
    volver a preguntar pero no hace ganar a ninguna candidata: no tiene camino
    por el que resolver, así que simularlo no diría nada.

    El «no» se simula como la exclusión que guardaría la consola: la ficha no
    es esa cláusula. El término de la ficha que elegiría la persona no se
    conoce de antemano, así que se usa la descripción entera —que la ficha
    dice por definición— y la exclusión se aplica igual que se aplicaría la
    real: a toda posición cuyo texto diga esa frase.

    COSTE

    Una clasificación más por pregunta, y sólo en los casos que se abstienen y
    preguntan. Si algún día se pasa un `interpreter`, cada simulación lo vuelve
    a llamar: hoy ningún camino de producción lo pasa.
    """
    if traza.final_status is RGIStatus.RESOLVED or not traza.steps:
        return traza
    ultimo = traza.steps[-1]
    if not ultimo.preguntas:
        return traza

    sirven = tuple(
        pregunta
        for pregunta in ultimo.preguntas
        if _clasificar(
            context.model_copy(
                update={
                    "exclusiones": (*context.exclusiones, (context.description, pregunta.exige))
                }
            ),
            catalog=catalog,
            notes=notes,
            interpreter=interpreter,
        ).final_status
        is RGIStatus.RESOLVED
    )
    if len(sirven) == len(ultimo.preguntas):
        return traza
    return traza.model_copy(
        update={"steps": (*traza.steps[:-1], ultimo.model_copy(update={"preguntas": sirven}))}
    )


def _clasificar(
    context: ClassificationContext,
    *,
    catalog: TariffCatalog,
    notes: LegalNotes,
    interpreter: Interpreter | None = None,
) -> ClassificationTrace:
    """La secuencia de las RGI, sin filtrar las preguntas.

    Separada de `classify` para que la simulación de una respuesta no vuelva a
    simular sus propias preguntas: sin esto, cada simulación abriría otras
    tantas, en cadena.
    """
    pasos: list[RGIResult] = []
    candidatos: Sequence[TariffCandidate] = ()

    # ── Etapa 1: la partida ──────────────────────────────────────────────────
    partida: RGIResult | None = None
    for regla in HEADING_RULES:
        resultado = regla.evaluate(
            context,
            candidates=candidatos,
            catalog=catalog,
            notes=notes,
            interpreter=interpreter,
        )
        pasos.append(resultado)

        # Una regla que acota los candidatos alimenta a la siguiente: es lo que
        # hace que la RGI 3 opere sobre lo que la RGI 1 dejó en pie.
        if resultado.candidate_codes:
            candidatos = resultado.candidate_codes

        if resultado.is_terminal:
            partida = resultado
            break

    if partida is None:
        # Se agotaron las siete reglas sin resolver ni escalar. No debería
        # ocurrir —RGI 4 siempre escala— pero si el orden cambia, esto lo
        # atrapa en vez de devolver una traza sin conclusión.
        return _cerrar(
            pasos,
            RGIStatus.HUMAN_REVIEW_REQUIRED,
            missing=("ninguna regla de la etapa 1 concluyó",),
        )

    if partida.status is not RGIStatus.RESOLVED:
        return _cerrar(pasos, partida.status, missing=partida.missing_information)

    # ── Etapa 2: la fracción ─────────────────────────────────────────────────
    seis = RGI6().evaluate(
        context,
        candidates=partida.candidate_codes,
        catalog=catalog,
        notes=notes,
        interpreter=interpreter,
    )
    pasos.append(seis)

    if seis.status is not RGIStatus.RESOLVED:
        return _cerrar(pasos, seis.status, missing=seis.missing_information)

    # La confianza del conjunto es la menor de la cadena: el resultado no es
    # más fiable que el paso más débil que lo sostiene.
    confianzas = [p.confidence for p in pasos if p.confidence is not None]
    return ClassificationTrace(
        steps=tuple(pasos),
        final_status=RGIStatus.RESOLVED,
        resolved_code=seis.resolved_code,
        confidence=min(confianzas) if confianzas else None,
        engine_version=ENGINE_VERSION,
    )


def _cerrar(
    pasos: list[RGIResult],
    estado: RGIStatus,
    *,
    missing: tuple[str, ...] = (),
) -> ClassificationTrace:
    """Cierra la traza sin código resuelto, conservando todo lo evaluado.

    Los pasos se conservan aunque no haya conclusión: saber qué se intentó y
    por qué no funcionó es lo que permite arreglar el caso, y es la mitad del
    valor de tener una máquina en vez de un prompt.
    """
    return ClassificationTrace(
        steps=tuple(pasos),
        final_status=estado,
        resolved_code=None,
        confidence=None,
        missing_information=missing,
        engine_version=ENGINE_VERSION,
    )
