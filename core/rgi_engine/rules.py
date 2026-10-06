"""Las seis Reglas Generales de Interpretación, como evaluadores separados.

§18 del maestro: "No implementar clasificación como un prompt gigante.
Construir una máquina de evaluación." Cada regla es una clase con la misma
interfaz, evalúa una precondición concreta y devuelve un estado explícito.

REGLAS NO IMPLEMENTADAS EN v0.1

RGI 2, 4 y 5 no están implementadas, pero NO se saltan en silencio: detectan si
sus precondiciones se cumplen y, en ese caso, devuelven
`HUMAN_REVIEW_REQUIRED`. Una regla no implementada que devolviera `CONTINUE`
dejaría pasar mercancías que necesitaban justo esa regla, y el resultado sería
una clasificación equivocada con apariencia de fundada. Escalar es correcto;
pasar de largo, no.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Protocol

from core.rgi_engine.pregunta import formular
from core.rgi_engine.results import Descarte, PorQueSeDescarto, RGIResult
from core.rgi_engine.states import RGIStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.rgi_engine.context import ClassificationContext, TariffCandidate
    from core.rgi_engine.ports import Interpreter, LegalNotes, TariffCatalog


class RGIRule(Protocol):
    """Interfaz común de §17: `RGIRule.evaluate(context) -> RGIResult`."""

    rule_id: str

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult: ...


# ── RGI 1 ────────────────────────────────────────────────────────────────────


class RGI1:
    """Los textos de las partidas y las notas de sección o capítulo.

    Es la regla que resuelve la mayoría de los casos, y la única que SIEMPRE se
    aplica. Los títulos de sección y capítulo son indicativos: no clasifican.

    Las notas de exclusión pesan más que el texto de la partida. Una nota que
    dice "este capítulo no comprende..." descarta la partida por completo, por
    muy bien que encaje el texto — y por eso se consultan antes de dar por
    buena ninguna coincidencia.
    """

    rule_id = "RGI-1"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()

        terminos = list(context.search_terms)
        if not terminos and interpreter is not None:
            terminos = list(interpreter.suggest_terms(context=context))

        if not terminos:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.INSUFFICIENT_INFORMATION,
                input_facts=hechos,
                reasoning_summary=(
                    "No hay términos de nomenclatura con los que buscar en la tarifa, "
                    "y no se proporcionó intérprete para derivarlos de la descripción."
                ),
                missing_information=("search_terms", *context.missing_facts()),
            )

        encontrados = list(catalog.headings(on_date=context.operation_date, terms=terminos))
        encontrados = _mas_la_que_cumple_una_condicion(encontrados, catalog, context, terminos)

        # Las notas de exclusión se aplican antes que nada: descartan la
        # partida aunque el texto encaje.
        sobreviven: list[TariffCandidate] = []
        excluidas: list[str] = []
        # Lo mismo que `excluidas`, estructurado. El texto de arriba es para
        # personas; esto es lo que una pantalla puede leer sin parsearlo.
        descartes: list[Descarte] = []
        # La materia de la ficha descarta igual que una nota: una mercancía que
        # consta de acero no puede clasificarse en «las demás manufacturas de
        # plástico». Sin esto, la tubería de acero del corpus llegaba a la RGI
        # 3 c) con la 3926 todavía en la lista.
        familia = _familia_de_la_mercancia(context)
        afirmado = _lo_que_la_ficha_afirma(context)
        negado = _lo_que_la_ficha_niega(context)
        for c in encontrados:
            nota = notes.excludes(on_date=context.operation_date, heading=c.heading, terms=terminos)
            if nota:
                excluidas.append(f"{c.code} excluida por nota: {nota}")
                descartes.append(Descarte(code=c.code, motivo=nota, por="NOTA_LEGAL"))
                continue
            materia = _material_contradice(c, familia)
            if materia:
                motivo = f"su texto es de {materia} y la ficha declara {familia}"
                excluidas.append(f"{c.code} descartada: {motivo}")
                descartes.append(Descarte(code=c.code, motivo=motivo, por="MATERIA"))
                continue

            # LA NEGACIÓN DEL TEXTO TAMBIÉN DESCARTA AQUÍ, NO SÓLO EN LA RGI 6
            #
            # Estaba sólo al elegir fracción, y el daño era a nivel de partida:
            # la 7304 dice «Tubos y perfiles huecos, SIN SOLDADURA» y once
            # tubos SOLDADOS del corpus acababan ahí. La contradicción era
            # exacta y nadie la miraba en este paso.
            #
            # Es la misma función y el mismo criterio: si el texto legal niega
            # algo que la ficha afirma, esa posición es imposible. Que valga
            # para una fracción y no para su partida no tenía ninguna razón.
            negacion = _contradice(c, afirmado) or _la_ficha_la_niega(c, negado)
            if negacion:
                excluidas.append(f"{c.code} descartada: {negacion}")
                descartes.append(Descarte(code=c.code, motivo=negacion, por="CONTRADICCION"))
                continue

            # Y EL VOCABULARIO FIRMADO TAMBIÉN DESCARTA AQUÍ (Persona 1, 5-oct)
            #
            # Mismo argumento que la negación de arriba, y el mismo error de
            # haberlo puesto sólo un nivel más abajo: estaba sólo al elegir
            # fracción.
            #
            # Lo destapó probar la cadena de punta a punta. El bucle de captura
            # pregunta «¿una olla de presión es un "artículo de grifería"?» —la
            # pregunta que desatasca 32 productos—, la respuesta se guardaba
            # firmada… y el motor seguía resolviendo 8481 porque nadie leía el
            # vocabulario al elegir partida. La respuesta quedaba INERTE:
            # alguien contestaba y no pasaba nada.
            #
            # Preguntar algo cuya respuesta no se usa es peor que no preguntar:
            # gasta el tiempo de un clasificador y encima no se nota.
            aprendido = _lo_aprendido_la_descarta(c, context)
            if aprendido:
                excluidas.append(f"{c.code} descartada: {aprendido}")
                descartes.append(Descarte(code=c.code, motivo=aprendido, por="RESPUESTA_FIRMADA"))
                continue
            sobreviven.append(c)

        fuentes = tuple(c.source_id for c in sobreviven if c.source_id is not None)
        razon_exclusiones = ("  Exclusiones: " + " · ".join(excluidas)) if excluidas else ""

        if not sobreviven:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.INSUFFICIENT_INFORMATION,
                input_facts=hechos,
                reasoning_summary=(
                    f"Ninguna partida vigente al {context.operation_date.isoformat()} "
                    f"comprende la mercancía con los términos {terminos}." + razon_exclusiones
                ),
                descartadas=tuple(descartes),
                missing_information=context.missing_facts() or ("descripción más precisa",),
            )

        if len(sobreviven) == 1:
            c = sobreviven[0]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(c,),
                reasoning_summary=(
                    f"El texto de la partida {c.code} comprende la mercancía: "
                    f"«{c.text}». Ninguna nota de sección o capítulo la excluye."
                    + razon_exclusiones
                ),
                descartadas=tuple(descartes),
                source_ids=fuentes,
                confidence=_confianza(context),
            )

        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.CONTINUE,
            input_facts=hechos,
            candidate_codes=tuple(sobreviven),
            reasoning_summary=(
                f"{len(sobreviven)} partidas comprenden la mercancía "
                f"({', '.join(c.code for c in sobreviven)}). "
                f"La RGI 1 no la resuelve; se continúa." + razon_exclusiones
            ),
            descartadas=tuple(descartes),
            source_ids=fuentes,
        )


# ── RGI 2 ────────────────────────────────────────────────────────────────────

_INCOMPLETO = re.compile(
    r"\b(incompleto|sin\s+terminar|sin\s+montar|desmontad[oa]|desarmad[oa]|"
    r"kit|para\s+ensamblar|CKD|SKD)\b",
    re.IGNORECASE,
)
_MEZCLA = re.compile(
    r"\b(mezcla|mezclad[oa]|aleaci[oó]n|compuest[oa]\s+de|surtido)\b", re.IGNORECASE
)


class RGI2:
    """Artículos incompletos o sin terminar (a) y materias mezcladas (b).

    NO IMPLEMENTADA en v0.1. Detecta si sus precondiciones se cumplen y escala.

    Aplicarla bien exige juzgar si un artículo incompleto "presenta las
    características esenciales del artículo completo", que es un juicio
    material, no textual. Fingir que se resuelve sería peor que admitir que no.
    """

    rule_id = "RGI-2"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        texto = " ".join([context.description, *(f.value or "" for f in context.known_facts())])
        incompleto = _INCOMPLETO.search(texto)
        mezcla = _MEZCLA.search(texto)

        if not incompleto and not mezcla:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=context.as_input_facts(),
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    "La mercancía no se presenta incompleta, sin terminar ni desmontada, "
                    "y no consta que sea una mezcla o asociación de materias."
                ),
            )

        motivo = (
            f"presenta indicios de artículo incompleto o sin montar («{incompleto.group()}»)"
            if incompleto
            else f"presenta indicios de mezcla o asociación de materias («{mezcla.group()}»)"  # type: ignore[union-attr]
        )
        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.HUMAN_REVIEW_REQUIRED,
            input_facts=context.as_input_facts(),
            candidate_codes=tuple(candidates),
            reasoning_summary=(
                f"La mercancía {motivo}, así que la RGI 2 es aplicable. "
                f"Esta versión del motor no la implementa: determinar si presenta "
                f"las características esenciales del artículo completo requiere un "
                f"juicio material que no se puede derivar del texto. Requiere "
                f"revisión humana."
            ),
            missing_information=("aplicación de la RGI 2 por un clasificador",),
        )


# ── RGI 3 ────────────────────────────────────────────────────────────────────


class RGI3A:
    """La partida con la descripción más específica (RGI 3 a).

    "Más específica" es la que describe la mercancía por su nombre frente a la
    que la describe por su género. `specificity` lo aporta el catálogo, porque
    depende de los textos concretos y no de una heurística del motor.

    Un empate no se rompe aquí: se pasa a la 3 b), que es lo que manda la
    propia regla.
    """

    rule_id = "RGI-3a"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()
        if len(candidates) < 2:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary="No hay concurrencia de partidas que resolver.",
            )

        # Primero, la partida que fija un umbral medible QUE LA MERCANCÍA
        # CUMPLE. Es más específica en el sentido que importa: el texto legal
        # dice algo comprobable y la ficha lo comprueba. Contar calificativos
        # —que es lo que hace `specificity`— no distingue una tubería de acero
        # de un artículo de grifería, y en el corpus elegía grifería.
        cumplen = [c for c in candidates if (lambda t: t[0] and not t[1])(_condiciones(c, context))]
        if len(cumplen) == 1:
            c = cumplen[0]
            otras = [o for o in candidates if o.code != c.code]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(c,),
                reasoning_summary=(
                    f"La partida {c.code} («{c.text}») fija una condición medible que la "
                    f"mercancía cumple, y {', '.join(o.code for o in otras)} no. La RGI 3 a) "
                    f"la prefiere por describirla de forma más específica."
                ),
                source_ids=tuple(x.source_id for x in (c,) if x.source_id is not None),
                confidence=_confianza(context),
            )

        # Después del umbral y antes de contar calificativos: LA QUE NOMBRA LA
        # MATERIA DE LA MERCANCÍA.
        #
        # El peor resultado de todo el corpus salía de aquí (César, 5-oct):
        #
        #     ficha  «CABLE DE ACERO >=25.4 MM»
        #     7312   «Cables, trenzas, eslingas…, DE HIERRO O ACERO, sin aislar
        #             para electricidad.»
        #     8544   «Hilos, cables… y demás conductores aislados para
        #             electricidad…»
        #
        # El motor las declaraba «igual de específicas» y la RGI 3 c) elegía la
        # última por numeración: **8544**, cables eléctricos coaxiales, para un
        # cable de izado de acero. Tres productos del corpus acabaron ahí.
        #
        # Y la 7312 nombra la materia que la ficha declara mientras la 8544 no
        # nombra ninguna. Nombrar la materia de la mercancía ES describirla de
        # forma más específica, que es literalmente lo que pide la RGI 3 a).
        #
        # Sólo resuelve cuando UNA la nombra. Si la nombran varias o ninguna,
        # no hay ventaja y se sigue al recuento de calificativos.
        #
        # Y NO PUEDE GANAR UNA CON UN UMBRAL SIN CONFIRMAR
        #
        # Dos guardas, y las dos las cazaron tests que ya existían:
        #
        #   ⌀200   la 7305 exige diámetro SUPERIOR a 406.4 mm y 200 no lo
        #          cumple. Nombrar la materia no puede ganarle a incumplir una
        #          condición explícita del texto legal.
        #
        #   sin ⌀  la 7305 tampoco puede ganar, porque elegirla AFIRMA que el
        #          tubo supera 406.4 mm y la ficha no lo dice. El silencio de
        #          la ficha no cumple ni incumple — y una posición se gana
        #          cumpliendo, no por no poder comprobarse.
        #
        # Así que sólo compite la que no tiene condición medible, o la que
        # tiene todas las suyas confirmadas.
        nombran = [
            c
            for c in candidates
            if _nombra_la_materia(c, context) and _umbral_confirmado(c, context)
        ]
        if len(nombran) == 1:
            c = nombran[0]
            otras = [o for o in candidates if o.code != c.code]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(c,),
                reasoning_summary=(
                    f"La partida {c.code} («{c.text}») nombra la materia que declara la "
                    f"ficha, y {', '.join(o.code for o in otras)} no nombra ninguna. La "
                    f"RGI 3 a) la prefiere por describirla de forma más específica."
                ),
                source_ids=tuple(x.source_id for x in (c,) if x.source_id is not None),
                confidence=_confianza(context),
            )

        maximo = max(c.specificity for c in candidates)
        mas_especificas = [c for c in candidates if c.specificity == maximo]

        if len(mas_especificas) == 1 and maximo > 0:
            c = mas_especificas[0]
            otras = [o for o in candidates if o.code != c.code]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(c,),
                reasoning_summary=(
                    f"La partida {c.code} («{c.text}») describe la mercancía de forma "
                    f"más específica que {', '.join(o.code for o in otras)}."
                ),
                source_ids=tuple(c.source_id for c in (c,) if c.source_id is not None),
                confidence=_confianza(context),
            )

        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.CONTINUE,
            input_facts=hechos,
            candidate_codes=tuple(candidates),
            reasoning_summary=(
                f"Las partidas {', '.join(c.code for c in mas_especificas)} son igual de "
                f"específicas; la RGI 3 a) no las distingue."
            ),
        )


class RGI3B:
    """La materia o el componente que confiere el carácter esencial (RGI 3 b).

    Es un juicio material, no textual, así que requiere `Interpreter`. Sin él,
    el motor NO adivina: escala a revisión humana.

    Y aunque haya intérprete, el modelo sólo propone: la máquina exige que su
    propuesta esté entre los candidatos reales de la tarifa. Un modelo que
    devuelva un código inventado no puede resolver nada.
    """

    rule_id = "RGI-3b"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()
        if len(candidates) < 2:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary="No hay concurrencia de partidas que resolver.",
            )

        if interpreter is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    "Determinar el carácter esencial exige un juicio material sobre la "
                    "mercancía y no hay intérprete disponible. Se continúa a la RGI 3 c)."
                ),
            )

        propuesta = interpreter.essential_character(context=context, candidates=candidates)
        if propuesta is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    "No se pudo determinar qué componente confiere el carácter esencial."
                ),
            )

        codigo, razonamiento = propuesta
        elegido = next((c for c in candidates if c.code == codigo), None)
        if elegido is None:
            # El modelo devolvió algo que no está en la tarifa. Es exactamente
            # lo que la máquina existe para atrapar (§36).
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    f"El intérprete propuso la partida {codigo}, que no está entre los "
                    f"candidatos vigentes ({', '.join(c.code for c in candidates)}). "
                    f"No se acepta un código que no proviene de la tarifa."
                ),
                missing_information=("verificación del carácter esencial",),
            )

        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.RESOLVED,
            input_facts=hechos,
            candidate_codes=(elegido,),
            reasoning_summary=(
                f"El carácter esencial corresponde a {elegido.code} («{elegido.text}»). "
                f"{razonamiento}"
            ),
            source_ids=tuple(c.source_id for c in (elegido,) if c.source_id is not None),
            confidence=_confianza(context, penalizacion=Decimal("0.15")),
        )


class RGI3C:
    """La última partida por orden de numeración (RGI 3 c).

    Es el desempate de último recurso, y se aplica sólo cuando las anteriores
    no resolvieron. Resuelve, pero con confianza reducida y marcando revisión:
    llegar hasta aquí significa que ninguna razón sustantiva distinguió los
    candidatos, y eso conviene que lo vea un humano.
    """

    rule_id = "RGI-3c"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()
        if len(candidates) < 2:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary="No hay concurrencia de partidas que resolver.",
            )

        ultima = max(candidates, key=lambda c: c.code)
        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.RESOLVED,
            input_facts=hechos,
            candidate_codes=(ultima,),
            reasoning_summary=(
                f"Ninguna regla anterior distinguió entre "
                f"{', '.join(sorted(c.code for c in candidates))}. Se aplica la última "
                f"por orden de numeración: {ultima.code}. Conviene revisión humana, "
                f"porque el desempate no responde a una razón sustantiva."
            ),
            source_ids=tuple(c.source_id for c in (ultima,) if c.source_id is not None),
            confidence=_confianza(context, penalizacion=Decimal("0.30")),
            # Resuelve, y aun así lo tiene que ver alguien. Hasta ahora esto
            # sólo estaba dicho en el `reasoning_summary` de arriba, que nadie
            # lee en tiempo de ejecución: la clasificación salía RESOLVED y sin
            # marcar. La confianza baja no bastaba, porque nada la usa de
            # umbral.
            requires_human_review=True,
        )


# ── RGI 4 y 5 ────────────────────────────────────────────────────────────────


class RGI4:
    """Las mercancías más análogas.

    NO IMPLEMENTADA. Si la secuencia llega aquí, es que ninguna partida
    comprende la mercancía y hay que buscar analogía — un juicio que esta
    versión no hace. Escala.
    """

    rule_id = "RGI-4"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.HUMAN_REVIEW_REQUIRED,
            input_facts=context.as_input_facts(),
            candidate_codes=tuple(candidates),
            reasoning_summary=(
                "Las reglas 1 a 3 no resolvieron la clasificación. La RGI 4 exige "
                "identificar la mercancía más análoga, juicio que esta versión del "
                "motor no realiza."
            ),
            missing_information=("aplicación de la RGI 4 por un clasificador",),
        )


_ESTUCHE = re.compile(
    r"\b(estuche|funda|maletín|caja|envase|recipiente|acondicionad[oa]\s+para\s+la\s+venta)\b",
    re.IGNORECASE,
)


class RGI5:
    """Estuches, envases y continentes similares.

    NO IMPLEMENTADA. Detecta la precondición y escala en vez de ignorarla: si
    la mercancía viene en un estuche que debe seguir la suerte del contenido,
    clasificar sin aplicar esta regla da un resultado equivocado.
    """

    rule_id = "RGI-5"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hallazgo = _ESTUCHE.search(context.description)
        if not hallazgo:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=context.as_input_facts(),
                candidate_codes=tuple(candidates),
                reasoning_summary="No consta estuche, envase ni continente similar.",
            )
        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.HUMAN_REVIEW_REQUIRED,
            input_facts=context.as_input_facts(),
            candidate_codes=tuple(candidates),
            reasoning_summary=(
                f"La descripción menciona «{hallazgo.group()}», así que la RGI 5 puede "
                f"ser aplicable. Esta versión del motor no la implementa."
            ),
            missing_information=("aplicación de la RGI 5 por un clasificador",),
        )


# ── RGI 6 ────────────────────────────────────────────────────────────────────


class RGI6:
    """Clasificación a nivel de subpartida.

    Sólo se comparan subpartidas del mismo nivel, y se aplican las reglas
    anteriores *mutatis mutandis*. Es la regla que lleva de la partida de 4
    dígitos a la subpartida de 6 y, en México, a la fracción de 8.

    Cuando queda más de un candidato, esta versión NO elige: escala. Preferir
    revisión humana a una fracción inventada es lo que exige el §8.2, y una
    fracción equivocada cambia el arancel que paga un importador.
    """

    rule_id = "RGI-6"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()
        if len(candidates) != 1:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    "La RGI 6 requiere una partida determinada para descender a "
                    "subpartida, y no la hay."
                ),
            )

        partida = candidates[0]
        subs = list(catalog.subheadings(on_date=context.operation_date, heading=partida.heading))
        if not subs:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.INSUFFICIENT_INFORMATION,
                input_facts=hechos,
                candidate_codes=(partida,),
                reasoning_summary=(
                    f"No hay subpartidas cargadas para la partida {partida.heading} "
                    f"vigentes al {context.operation_date.isoformat()}."
                ),
                missing_information=(f"subpartidas de {partida.heading}",),
            )

        # Antes de desempatar: quitar las que la MATERIA de la mercancía hace
        # imposibles, cuando es la propia tarifa la que opone dos hermanas por
        # materia. Descartar es mucho más barato de sostener que elegir, y aquí
        # el fundamento no lo pone el motor: lo pone el texto legal de al lado.
        posibles = _la_materia_de_una_hermana_descarta(subs, context)
        descartadas_por_materia = [c for c in subs if c not in posibles]
        declarada = ", ".join(sorted(_materias_declaradas(context)))
        de_subpartida: list[Descarte] = [
            Descarte(
                code=c.code,
                motivo=(
                    f"su texto es de {', '.join(sorted(_materias_literales(c.text)))} "
                    f"y la ficha declara {declarada}"
                ),
                por="MATERIA",
            )
            for c in descartadas_por_materia
        ]
        por_materia = (
            "  Descartadas por materia: "
            + " · ".join(f"{c.code} («{c.text}»)" for c in descartadas_por_materia)
            if descartadas_por_materia
            else ""
        )

        # Y las que hace imposibles una respuesta firmada.
        #
        # ESTO FALTABA Y DEJABA INERTES LAS RESPUESTAS DE SUBPARTIDA
        #
        # `_lo_aprendido_la_descarta` se aplicaba a las fracciones (más abajo) y
        # a las partidas (en la RGI 1), nunca a las subpartidas. Así que una
        # respuesta sobre una cláusula de subpartida se guardaba firmada y no
        # cambiaba nada: tercera vez que aparece el mismo patrón —un dato que se
        # escribe en el dominio y no se vuelve a leer— en esta misma función.
        #
        # Visto con la olla de presión de aluminio (César, 5-oct). Contestó que
        # una olla de cocina NO es «Artículos de higiene o tocador», lo cual
        # hace imposible la 761520 y deja sola a la 761510. El motor siguió
        # diciendo «761510 y 761520 comprenden la mercancía y ninguna es más
        # específica», con su respuesta guardada en la base.
        #
        # MISMA DISCIPLINA QUE EN LA RGI 3: descartar sólo puede RESOLVER
        # cuando queda exactamente una. Con varias supervivientes se vuelve a
        # la lista entera, porque desempatar por `specificity` entre los
        # supervivientes es lo que convertiría una negativa honesta en una
        # fracción equivocada.
        aprendidos = {c.code: m for c in posibles if (m := _lo_aprendido_la_descarta(c, context))}
        # Se registran aunque no resuelvan (más abajo, sólo resuelven si queda
        # una): que el motor no se apoye en ellas para ELEGIR no las hace
        # posibles. Una respuesta firmada dice que la mercancía no es eso.
        de_subpartida += [
            Descarte(code=c, motivo=m, por="RESPUESTA_FIRMADA") for c, m in aprendidos.items()
        ]
        por_respuesta = (
            "  Descartadas por respuesta firmada: "
            + " · ".join(f"{c} ({m})" for c, m in aprendidos.items())
            if aprendidos
            else ""
        )
        sobreviven_a_lo_firmado = [c for c in posibles if c.code not in aprendidos]
        if len(sobreviven_a_lo_firmado) == 1:
            posibles = sobreviven_a_lo_firmado

        elegida = _unica_o_mas_especifica(posibles, mercancia=context.description, context=context)
        if elegida is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                # La lista COMPLETA: quien revise tiene que ver también las que
                # el motor quitó, y por qué. Un descarte que no se enseña es un
                # candidato que desaparece.
                candidate_codes=tuple(subs),
                reasoning_summary=(
                    f"Varias subpartidas de {partida.heading} comprenden la mercancía "
                    f"({', '.join(s.code for s in subs)}) y ninguna es más específica. "
                    f"El motor no elige entre ellas." + por_materia + por_respuesta
                ),
                descartadas=tuple(de_subpartida),
                missing_information=("desempate de subpartida por un clasificador",),
                # La pregunta concreta, si hay una corta que lo resuelva. No
                # sustituye al aviso de arriba: lo acota. Sobre las posibles, no
                # sobre todas: preguntar por una posición que la tarifa ya
                # descartó gasta el tiempo de quien contesta.
                #
                # SI NO SE PUEDE PREGUNTAR POR LAS SUBPARTIDAS, SE PREGUNTA POR
                # LA PARTIDA (Persona 1, 5-oct)
                #
                # `formular` se calla cuando hay más de cuatro candidatas: seis
                # preguntas de sí o no no son una pregunta, son el trabajo
                # entero. Pero callarse ahí dejaba 44 productos del corpus sin
                # ninguna pregunta y sin salida posible —la olla de presión con
                # seis subpartidas de 8481, el sartén con doce de 7318—.
                #
                # Y en esos casos el problema no está en la subpartida: está en
                # la PARTIDA. Una olla de presión no es un «artículo de
                # grifería», y preguntarlo es UNA pregunta en vez de seis, y es
                # la que importa. Si la respuesta es «no», la partida entera se
                # cae y el motor deja de insistir en un sitio equivocado.
                preguntas=tuple(formular(context, posibles) or formular(context, [partida])),
            )

        fracciones = list(
            catalog.fractions(on_date=context.operation_date, subheading=elegida.code)
        )
        if not fracciones:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(elegida,),
                reasoning_summary=(
                    f"Subpartida {elegida.code} («{elegida.text}»). No hay fracciones "
                    f"cargadas por debajo." + por_materia + por_respuesta
                ),
                descartadas=tuple(de_subpartida),
                source_ids=tuple(c.source_id for c in (elegida,) if c.source_id is not None),
                confidence=_confianza(context),
            )

        # ── Descarte por contradicción ──────────────────────────────────────
        #
        # Antes de intentar elegir, se quitan las que la mercancía hace
        # imposibles: una fracción que dice «sin galvanizar» no puede ser la de
        # un cable que consta galvanizado. Descartar es una afirmación mucho
        # más barata de sostener que elegir, y se puede hacer sin saber cuál es
        # la correcta.
        #
        # LA REGLA QUE HACE ESTO SEGURO: descartar sólo puede RESOLVER cuando
        # queda exactamente una. Si quedan varias, se vuelve a la lista
        # COMPLETA y al desempate de siempre, no a los supervivientes.
        #
        # No es una cautela teórica. Con el cable 6x19 de ⌀10 mm, descartar
        # `73121008` («Sin galvanizar») y desempatar entre los supervivientes
        # por `specificity` daría `73121007` —«constituidos por 7 alambres»—
        # para una construcción de 114 alambres. Hoy el motor empata y se
        # niega, que es la respuesta correcta. Una mejora que convierte una
        # negativa honesta en una fracción equivocada no es una mejora.
        afirmado = _lo_que_la_ficha_afirma(context)
        negado = _lo_que_la_ficha_niega(context)
        de_fraccion: list[Descarte] = []
        for c in fracciones:
            if (imposible := _por_que_es_imposible(c, afirmado, negado, context)) is not None:
                motivo, por = imposible
                de_fraccion.append(Descarte(code=c.code, motivo=motivo, por=por))
        descartes = {d.code: d.motivo for d in de_fraccion}
        descartadas = (*de_subpartida, *de_fraccion)
        vivas = [c for c in fracciones if c.code not in descartes]

        # UN RESIDUAL PURO NO SOBREVIVE A COSTA DE LA ESPECÍFICA (5-oct)
        #
        # La regla de arriba dice que descartar sólo resuelve cuando queda
        # exactamente una, y con dos supervivientes se vuelve al empate. Eso
        # dejaba la pregunta del cable 6x36 sin efecto:
        #
        #     73121008  «Sin galvanizar, … constituidos por 7 alambres.»
        #     73121005  «De acero sin recubrimiento, con o sin lubricación, …»
        #     73121099  «Los demás.»
        #
        # El motor preguntaba lo correcto y un «no» descartaba la 73121008…
        # dejando DOS, así que el caso volvía al empate. Simulado sobre el
        # corpus: ni el «sí» ni el «no» cambiaban nada. Seis casos de la
        # bandeja pidiendo un minuto a cambio de cero, y una pregunta cuya
        # respuesta no se usa es peor que no preguntar.
        #
        # Un texto que es sólo «Los demás.» no califica nada, así que no puede
        # mantener vivo un empate contra una hermana que describe la mercancía.
        # Con él fuera queda una sola: 73121005, la que dictaminó César.
        #
        # POR QUÉ ESTO NO ES EL DESEMPATE QUE YA SALIÓ MAL
        #
        # El aviso de arriba es sobre `specificity`: desempatar entre los
        # supervivientes por número de calificativos daba 73121007
        # —«constituidos por 7 alambres»— a un cable de 114 alambres. Esto no
        # cuenta calificativos: quita una candidata que no tiene ninguno, y
        # además exige `_algo_la_sostiene` —que alguna palabra de la fracción
        # conste en la mercancía—, que es el guardarraíl que impidió elegir
        # «De Talavera» para una vajilla que no la menciona.
        #
        # Y SÓLO SI UN DESCARTE ELIMINÓ ALGO
        #
        # Sin descarte no hay información nueva: es el empate de siempre, y lo
        # resuelve —o no— `_unica_o_mas_especifica` con sus propias reglas.
        # Esta existe para que una RESPUESTA pague, así que se activa cuando
        # hay una respuesta (o una negación del texto) que quitó una candidata.
        #
        # Lo cazó `test_varias_fracciones_aplicables_no_se_deciden_al_azar`:
        # sin esta condición el motor resolvía un empate limpio entre una
        # fracción y un «Las demás», que es un empate que debe decidir una
        # persona.
        #
        # Sólo cuando quede EXACTAMENTE una. Con dos que califican, se vuelve
        # al empate como siempre.
        if descartes and len(vivas) > 1:
            califican = [c for c in vivas if not _es_residual_puro(c)]
            if (
                len(califican) == 1
                and _algo_la_sostiene(califican[0], context.description)
                and _sus_ausencias_constan(califican[0], context)
            ):
                vivas = califican

        # El motivo viene ya escrito de donde salga —negación del texto o
        # respuesta firmada— y se cita tal cual. Envolverlo en «el texto dice
        # "sin ..."» producía frases rotas en cuanto el descarte no venía de
        # una negación: «el texto dice "sin la ficha dice ..."».
        motivos = " · ".join(f"{c}: {m}" for c, m in descartes.items())

        if len(vivas) == 1:
            unica = vivas[0]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(unica,),
                reasoning_summary=(
                    f"Partida {partida.heading} → subpartida {elegida.code} → "
                    f"fracción {unica.code} («{unica.text}»)."
                    # «Es la única que la mercancía no contradice; descartadas:
                    # .» salía también cuando la subpartida tenía UNA sola
                    # fracción y no se descartó nada: afirmaba un descarte que
                    # no hubo, con un punto suelto detrás. Sólo se dice cuando
                    # se hizo.
                    + (
                        f" Es la única que la mercancía no contradice; descartadas: {motivos}."
                        if descartes
                        else ""
                    )
                    + por_materia
                    + por_respuesta
                ),
                descartadas=descartadas,
                source_ids=tuple(
                    c.source_id for c in (partida, elegida, unica) if c.source_id is not None
                ),
                confidence=_confianza(context),
            )

        fraccion = _unica_o_mas_especifica(
            fracciones, mercancia=context.description, context=context
        )
        if fraccion is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                candidate_codes=tuple(vivas or fracciones),
                reasoning_summary=(
                    f"Varias fracciones de {elegida.code} son aplicables "
                    f"({', '.join(f.code for f in (vivas or fracciones))}). El motor no "
                    f"elige: una fracción equivocada cambia el arancel que paga el "
                    f"importador."
                    + (
                        f" Sí descartó {len(descartes)} por contradicción — {motivos}."
                        if descartes
                        else ""
                    )
                ),
                descartadas=descartadas,
                missing_information=("desempate de fracción por un clasificador",),
                preguntas=tuple(formular(context, list(vivas or fracciones))),
            )

        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.RESOLVED,
            input_facts=hechos,
            candidate_codes=(fraccion,),
            reasoning_summary=(
                f"Partida {partida.heading} → subpartida {elegida.code} → "
                f"fracción {fraccion.code} («{fraccion.text}»)." + por_materia + por_respuesta
            ),
            descartadas=descartadas,
            source_ids=tuple(
                c.source_id for c in (partida, elegida, fraccion) if c.source_id is not None
            ),
            confidence=_confianza(context),
        )


# ── Auxiliares ───────────────────────────────────────────────────────────────


def _por_que_es_imposible(
    candidata: TariffCandidate,
    afirmado: set[str],
    negado: dict[str, set[str]],
    context: ClassificationContext,
) -> tuple[str, PorQueSeDescarto] | None:
    """El motivo por el que esta fracción no puede ser, y de dónde sale.

    Las mismas tres comprobaciones, en el mismo orden, que antes iban
    encadenadas con `or` dentro del descarte de la RGI 6. Se separan sólo para
    poder decir cuál de las tres lo descartó: las dos primeras se sostienen en
    el texto legal, la tercera en la firma de un clasificador.
    """
    if motivo := _contradice(candidata, afirmado) or _la_ficha_la_niega(candidata, negado):
        return motivo, "CONTRADICCION"
    if motivo := _lo_aprendido_la_descarta(candidata, context):
        return motivo, "RESPUESTA_FIRMADA"
    return None


#: Por debajo de esto una palabra no distingue nada: «de», «los», «para».
_MINIMO_DISTINTIVO = 5


def _plano(texto: str) -> str:
    """El texto sin acentos ni mayúsculas, para poder compararlo."""
    return unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore").decode()


def _palabras(texto: str) -> set[str]:
    """Las palabras del texto que pueden distinguir, sin acentos ni mayúsculas."""
    return {p for p in re.findall(r"[^\W\d_]+", _plano(texto)) if len(p) >= _MINIMO_DISTINTIVO}


def _singulares(palabra: str) -> set[str]:
    """La palabra y su singular, cuando el plural castellano es evidente.

    EL FALLO QUE ESTO ARREGLA, Y SON 41 PRODUCTOS

    La partida 7312 abre dos subpartidas: `731210` dice **«Cables.»** y
    `731290` dice «Los demás.». Cuarenta y un cables de acero del corpus se
    quedaban sin clasificar porque la ficha dice «CABLE» y la tarifa dice
    «Cables», y la comparación era de conjuntos exactos:

        {'cables'} & {'cable', 'acero', 'construccion', ...} = set()

    El motor no podía ver que un CABLE es uno de los «Cables». Lo mismo con
    «ESTROPAJO» contra «estropajos» en la 7323 y «OLEODUCTO» contra
    «oleoductos» en la 7305.

    POR QUÉ NO SE USA `_raices` PARA ESTO

    Porque `_RAIZ = 6` está medido contra los pares que importan y una palabra
    de cinco letras truncada a seis sigue siendo ella misma: `cable` no se
    acerca a `cables` por ahí. Son dos problemas distintos y cada uno tiene su
    herramienta.

    POR QUÉ ES SEGURO

    Se quita una `s` o `es` final sólo si lo que queda sigue siendo
    distintivo —cinco letras—, y se devuelven las dos formas para que la
    comparación case por cualquiera. El umbral hace el trabajo de evitar
    destrozos: «gas» o «mes» nunca llegan aquí porque no son distintivos.

    No convierte dos palabras distintas en la misma: en castellano, que una
    palabra sea otra más `s` o `es` es el plural, no una coincidencia.
    """
    formas = {palabra}
    if palabra.endswith("es") and len(palabra) - 2 >= _MINIMO_DISTINTIVO:
        formas.add(palabra[:-2])
    if palabra.endswith("s") and len(palabra) - 1 >= _MINIMO_DISTINTIVO:
        formas.add(palabra[:-1])
    return formas


def _palabras_con_singular(texto: str) -> set[str]:
    """Las palabras distintivas del texto, cada una con su singular.

    Sólo para comparar un texto legal con la mercancía: ahí «Cables» y «CABLE»
    hablan de lo mismo y el número gramatical no distingue nada.
    """
    return {forma for p in _palabras(texto) for forma in _singulares(p)}


#: Prefijo con el que se comparan dos palabras para decidir que hablan de lo
#: mismo. Seis, medido contra los pares que importan:
#:
#:     soldadura / soldada        6 ✓   7 ✗   ← costó 11 clasificaciones
#:     galvanizar / galvanizado   6 ✓   7 ✓
#:     acero / acerado            6 ✗   7 ✗   ← el que NO debe casar
#:
#: Estaba en siete y por eso la 7304 —«Tubos y perfiles huecos, SIN SOLDADURA»—
#: no se descartaba para una tubería SOLDADA: `soldadu` no es `soldada`. Por
#: una letra, el motor clasificó once tubos soldados como tubos sin costura.
#:
#: Cinco sería demasiado: casaría «recubrimiento» con «recubierto», que a veces
#: son lo mismo y a veces no, y este umbral sólo debe casar lo indudable.
_RAIZ = 6

#: «sin X» niega X. «con o sin X» NO lo niega: lo permite en los dos sentidos,
#: y tratarlo como negación descartaría la fracción correcta de un cable
#: lubricado por decir su texto «con o sin lubricación».
_NIEGA = re.compile(r"(?<!con o )\bsin\s+([^\W\d_]+)")


def _raices(texto: str) -> set[str]:
    """Las raíces de las palabras distintivas de un texto."""
    return {p[:_RAIZ] for p in _palabras(texto)}


#: «no X» y «sin X» en una FICHA niegan X, igual que en la tarifa.
_FICHA_NIEGA = re.compile(r"\b(?:no|sin)\s+([^\W\d_]+)")


def _lo_que_la_ficha_afirma(context: ClassificationContext) -> set[str]:
    """Las raíces que la ficha AFIRMA, sin las que ella misma niega.

    EL MOTOR LEÍA LAS NEGACIONES DE LA TARIFA Y NO LAS DE LA FICHA

    `_contradice` descarta una posición cuando el texto legal niega algo que la
    mercancía afirma. Pero «lo que la mercancía afirma» se construía con todas
    las palabras de la ficha, incluidas las que la propia ficha niega. Así que
    una ficha que dice «NO PORCELANA» quedaba afirmando porcelana, y una que
    dice «SIN RECUBRIMIENTO» quedaba afirmando recubrimiento.

    Los dos casos están en el corpus y los dos salían mal:

        ficha  «CABLE DE ACERO SIN RECUBRIMIENTO»
        73121005 «De acero sin recubrimiento»
        -> el motor DESCARTABA la fracción correcta

        ficha  «VAJILLA DE CERAMICA VIDRIADA, NO PORCELANA»
        6912   «de cerámica, excepto porcelana»
        -> dicen lo MISMO y el motor los enfrentaba

    El primero es anterior a todo esto y llevaba ahí desde que existe
    `_contradice`; lo destapó la regla de «excepto», que hizo visible el mismo
    error en ocho vajillas de golpe. La medición lo cazó: la precisión bajó de
    100 % a 68 % y los ocho fallos eran el mismo.

    Es simétrico y por eso es defendible: «sin» y «no» niegan en los dos
    documentos, y leerlos sólo en uno hacía que el acuerdo pareciera
    contradicción.
    """
    negadas = {r for raices in _lo_que_la_ficha_niega(context).values() for r in raices}
    todo = " ".join([context.description, *(f.value or "" for f in context.known_facts())])
    return _raices(todo) - negadas


def _lo_que_la_ficha_niega(context: ClassificationContext) -> dict[str, set[str]]:
    """Palabra que la ficha niega → sus raíces. «NO PORCELANA» → porcelana.

    Se devuelve la palabra y no sólo la raíz porque el motivo del descarte se
    cita en la traza, y «la ficha dice "no porcel"» no es una frase que alguien
    pueda auditar.
    """
    todo = " ".join([context.description, *(f.value or "" for f in context.known_facts())])
    plano = _plano(todo)
    return {str(palabra): _raices(str(palabra)) for palabra in _FICHA_NIEGA.findall(plano)}


def _lo_que_el_texto_afirma(candidata: TariffCandidate) -> set[str]:
    """Las raíces que el texto legal AFIRMA, sin las que él mismo niega.

    Las dos clases de negación del texto, porque las dos cuentan: «sin» y
    «excepto». La 6912 dice «de cerámica, excepto porcelana» y NOMBRA la
    palabra; sin descontar la excepción, la posición que explícitamente excluye
    la porcelana pasaría por afirmarla.
    """
    plano = _plano(candidata.text)
    negadas = {r for palabra in _NIEGA.findall(plano) for r in _raices(str(palabra))}
    if (excluida := _lo_que_excepciona(candidata.text)) is not None:
        negadas |= _raices(excluida)
    return _raices(candidata.text) - negadas


def _sus_ausencias_constan(candidata: TariffCandidate, context: ClassificationContext) -> bool:
    """¿La ficha dice todo lo que esta posición afirma que NO tiene la mercancía?

    EL SILENCIO NO ES UNA AUSENCIA, Y ESTA REGLA LO TRATABA COMO SI LO FUERA

    El #191 quita un «Los demás.» cuando queda frente a una sola hermana que
    describe la mercancía, y exige `_algo_la_sostiene`: que alguna palabra de
    esa hermana conste en la ficha. Era poco. El 6-oct:

        ficha      «CABLE DE ACERO 12.7-25.4 MM»         ← nada del recubrimiento
        quedaban   73121005  «De acero sin recubrimiento…»
                   73121099  «Los demás.»
        dictamen   73121099 NICO 06  (César, 5-oct)

    «acero» está en las dos, así que `_algo_la_sostiene` pasó, el residual
    cayó y el motor afirmó «sin recubrimiento» de un cable cuya ficha no dice
    nada de su recubrimiento. Contra el dictamen escrito de quien lo revisó.

    Lo que una posición así añade sobre su residual es justamente su negación:
    «sin recubrimiento». Si la ficha no la dice, no se puede elegir — que no
    conste un recubrimiento no significa que no lo tenga. Es el mismo
    principio que `_contradice` ya tiene escrito al revés: tratar el silencio
    como negación descarta la correcta; tratarlo como ausencia elige la que no
    se puede sostener.

    Con la ficha diciendo «SIN RECUBRIMIENTO» —los catorce cables 6x36— sigue
    resolviendo igual: la ausencia consta.
    """
    plano = _plano(candidata.text)
    afirma_que_no = {r for palabra in _NIEGA.findall(plano) for r in _raices(str(palabra))}
    if (excluida := _lo_que_excepciona(candidata.text)) is not None:
        afirma_que_no |= _raices(excluida)
    if not afirma_que_no:
        return True
    la_ficha_niega = {r for raices in _lo_que_la_ficha_niega(context).values() for r in raices}
    return afirma_que_no <= la_ficha_niega


def _la_ficha_la_niega(candidata: TariffCandidate, negado: dict[str, set[str]]) -> str | None:
    """La palabra por la que la FICHA hace imposible esta posición, o `None`.

    EL ESPEJO QUE FALTABA, Y SON 14 VAJILLAS

    `_contradice` mira las negaciones de la TARIFA contra lo que la ficha
    afirma. La dirección contraria —la tarifa EXIGE lo que la ficha NIEGA— no
    se miraba en ninguna parte:

        ficha  «VAJILLA DE CERAMICA VIDRIADA, NO PORCELANA»
        6911   «Vajilla y demás artículos de uso doméstico […] de porcelana.»

    La ficha dice, con esas palabras, que no es de porcelana. La partida 6911
    es de porcelana. No hay nada que interpretar y el motor resolvía ahí.

    Es el mismo argumento de simetría que ya justificó leer las negaciones de
    la ficha: «sin» y «no» niegan en los DOS documentos, y una negación que se
    lee en un sentido y no en el otro deja medio mecanismo muerto.

    Lo destapó la medición al activar los puentes de vocabulario: con «mesa»
    llegando por fin a la consulta, la 6911 pasó a cubrir un término más que la
    6912 y ganó. El puente no creó el defecto —estaba desde que existe
    `_contradice`— sino que dejó de taparlo.
    """
    if not negado:
        return None
    afirma = _lo_que_el_texto_afirma(candidata)
    for palabra, raices in negado.items():
        if raices and raices & afirma:
            return f"la ficha dice «no {palabra}» y el texto exige «{palabra}»"
    return None


def _contradice(candidata: TariffCandidate, afirmado: set[str]) -> str | None:
    """La palabra por la que esta candidata es imposible, o `None`.

    Descartar es más seguro que elegir: una fracción que dice «sin galvanizar»
    no puede ser la de una mercancía que consta galvanizada, y eso se afirma
    sin saber cuál ES la correcta.

    Sólo mira negaciones explícitas del texto legal contra lo que el documento
    AFIRMA de la mercancía. No deduce: que una mercancía no mencione una
    característica no significa que no la tenga, y tratar el silencio como
    negación descartaría la correcta.
    """
    # Sobre el texto NORMALIZADO: la tarifa escribe «Sin galvanizar» con
    # mayúscula inicial y «diámetro» con acento, y un patrón que no lo
    # contemple no encuentra ni una sola negación.
    for negada in _NIEGA.findall(_plano(candidata.text)):
        negada = str(negada)
        raices = _raices(negada)
        if raices and raices & afirmado:
            return f"el texto dice «sin {negada}»"

    excluida = _lo_que_excepciona(candidata.text)
    if excluida:
        raices = _raices(excluida)
        if raices and raices & afirmado:
            return f"el texto dice «excepto {excluida}»"
    return None


#: Lo que puede ir entre «excepto» y la palabra excluida sin cambiar de quién
#: se habla. Sólo artículos y la preposición: cualquier otra cosa en medio
#: significa que la excepción es una frase y no una palabra, y ahí no se niega.
_ARTICULOS: frozenset[str] = frozenset(
    {"la", "el", "los", "las", "lo", "un", "una", "unos", "unas", "de", "del"}
)

#: «excepto» seguido de hasta dos palabras y la primera distintiva.
_EXCEPTUA = re.compile(r"\bexcepto\s+((?:[^\W\d_]+\s+){0,2}?)([^\W\d_]{5,})")


def _lo_que_excepciona(texto: str) -> str | None:
    """La palabra que el texto legal EXCLUYE con «excepto», o `None`.

    «EXCEPTO» NIEGA IGUAL QUE «SIN», Y EN 301 POSICIONES

    La partida 6912 dice «Vajilla […] de cerámica, **excepto porcelana**» y la
    6911 dice «de porcelana». Una vajilla de porcelana va en la 6911, y el
    motor la metía en la 6912 —la que explícitamente la excluye— por dos
    motivos que se sumaban: `_FAMILIAS` mete «porcelana» dentro de la familia
    «cerámica», y encima la 6912 NOMBRA la palabra «porcelana» en su cláusula
    de excepción, lo que la hacía parecer más compatible en vez de menos.

    «sin» aparece en 369 posiciones de la tarifa y «excepto» en 301. La mitad
    del mecanismo estaba sin leer.

    LAS DOS GUARDAS, Y LA SEGUNDA ES LA QUE IMPORTA

    No basta con coger la palabra siguiente, porque la excepción puede repetir
    el sujeto de la propia posición:

        151710  «Margarina, excepto la margarina líquida.»

    Lo excluido ahí es *líquida*, no *margarina*, y negar la segunda
    descartaría la posición para toda la margarina del arancel. Por eso:

    1. Entre «excepto» y la palabra sólo pueden ir artículos. Cualquier otra
       cosa significa que la excepción es una frase, y una frase no se niega
       con una palabra.
    2. La palabra **no puede aparecer en el resto del texto** de esa misma
       posición. Si aparece, la posición habla de ella y la excepción sólo la
       acota.

    Medido sobre las 301: **121 pasan** y 180 se descartan. De las que pasan,
    la muestra son negaciones reales —«excepto los filetes», «excepto el
    rallado», «excepto el apionabo»—; de las que se descartan, los casos son
    los que había que evitar —«excepto la harina de mostaza» en una partida de
    harina, «excepto los de mar» donde «mar» no distingue—.

    Se reporta de menos a propósito: una excepción que no se lee deja al motor
    donde estaba, y una que se lee mal le hace descartar la partida correcta.
    """
    coincidencia = _EXCEPTUA.search(_plano(texto))
    if coincidencia is None:
        return None
    intermedias = coincidencia.group(1).split()
    if any(palabra not in _ARTICULOS for palabra in intermedias):
        return None
    excluida = coincidencia.group(2)
    plano = _plano(texto)
    # Una REFERENCIA CRUZADA no es una característica.
    #
    # «Tubos, excepto los comprendidos en la fracción 7304» excluye por dónde
    # está clasificada otra mercancía, no por cómo es ésta. Negar
    # «comprendidos» sería inerte —ninguna ficha dice esa palabra— pero la
    # regla diría algo que no significa, y la inercia no es una garantía.
    if re.search(r"\b(fraccion|partida|subpartida|capitulo|inciso)", plano[coincidencia.start() :]):
        return None
    resto = plano[: coincidencia.start()] + plano[coincidencia.end() :]
    if re.search(r"\b" + re.escape(excluida), resto):
        return None
    return excluida


#: Familias de materia que se excluyen entre sí. Una mercancía de acero no es
#: de plástico, y eso se puede afirmar sin saber cuál es su partida.
#:
#: Es vocabulario, no criterio jurídico: no decide qué partida corresponde,
#: sólo cuáles son imposibles. Deliberadamente corto — cada entrada de más es
#: una forma nueva de descartar la partida correcta.
_FAMILIAS: dict[str, frozenset[str]] = {
    "ferroso": frozenset({"acero", "aceros", "hierro", "fundicion"}),
    "aluminio": frozenset({"aluminio"}),
    "cobre": frozenset({"cobre", "laton", "bronce"}),
    "plastico": frozenset({"plastico", "plasticos", "polimero", "polimeros"}),
    "caucho": frozenset({"caucho"}),
    "ceramica": frozenset({"ceramica", "ceramicas", "porcelana"}),
    "vidrio": frozenset({"vidrio"}),
    "madera": frozenset({"madera"}),
    "papel": frozenset({"papel", "carton"}),
}


def _familias(texto: str) -> set[str]:
    """Qué familias de materia nombra un texto."""
    palabras = set(re.findall(r"[^\W\d_]+", _plano(texto)))
    return {f for f, terminos in _FAMILIAS.items() if terminos & palabras}


def _familia_de_la_mercancia(context: ClassificationContext) -> str | None:
    """La familia de materia que DECLARA la ficha, o `None`.

    Sólo de un hecho sólido cuyo nombre hable de materia —`material`,
    `chassis_material`—, nunca de la descripción comercial. Un cable de acero
    con alma de fibra menciona dos materias en su descripción, y adivinar cuál
    manda descartaría la partida correcta.

    `None` si no consta o si la ficha nombra dos familias: entonces no hay una
    afirmación contra la que contradecir.
    """
    vistas: set[str] = set()
    for hecho in context.facts:
        if not hecho.is_solid or "material" not in hecho.name.casefold():
            continue
        vistas |= _familias(hecho.value or "")
    return next(iter(vistas)) if len(vistas) == 1 else None


#: Materias por su término LITERAL, y qué términos de la tarifa satisface cada
#: una. Más fino que `_FAMILIAS` a propósito: ahí «acero», «hierro» y
#: «fundicion» son una sola familia ferrosa, que es la granularidad correcta
#: para un texto como «artículos de higiene de fundición, hierro o acero» y
#: demasiado gruesa para distinguir dos hermanas suyas.
#:
#: Se lee en una dirección: si la ficha declara la clave, las posiciones que
#: nombren cualquiera de sus valores son posibles. El acero inoxidable es
#: acero, así que una posición que diga «de acero» le sirve; la fundición no
#: es acero ni al revés, y la LIGIE las separa en el mismo nivel.
_MATERIAS: dict[str, frozenset[str]] = {
    "acero inoxidable": frozenset({"acero inoxidable", "acero"}),
    "fundicion": frozenset({"fundicion"}),
    "acero": frozenset({"acero"}),
    "hierro": frozenset({"hierro"}),
    "aluminio": frozenset({"aluminio"}),
    "laton": frozenset({"laton", "cobre"}),
    "bronce": frozenset({"bronce", "cobre"}),
    "cobre": frozenset({"cobre"}),
    "porcelana": frozenset({"porcelana", "ceramica"}),
    "ceramica": frozenset({"ceramica"}),
    "plastico": frozenset({"plastico"}),
    "caucho": frozenset({"caucho"}),
    "vidrio": frozenset({"vidrio"}),
    "madera": frozenset({"madera"}),
    "carton": frozenset({"carton"}),
    "papel": frozenset({"papel"}),
}

#: De más largo a más corto: «acero inoxidable» tiene que reconocerse ANTES
#: que «acero», o un fregadero inoxidable quedaría declarado sólo como acero y
#: la distinción que hace la tarifa se perdería al leerla.
_MATERIAS_POR_LARGO: tuple[str, ...] = tuple(sorted(_MATERIAS, key=lambda t: (-len(t), t)))


def _materias_literales(texto: str) -> set[str]:
    """Las materias que un texto nombra, por su término literal.

    Se consume cada coincidencia para que la más larga gane: «de acero
    inoxidable» da `{"acero inoxidable"}` y no también `{"acero"}`.
    """
    resto = _plano(texto)
    encontradas: set[str] = set()
    for termino in _MATERIAS_POR_LARGO:
        if termino in resto:
            encontradas.add(termino)
            resto = resto.replace(termino, " ")
    return encontradas


def _materias_declaradas(context: ClassificationContext) -> set[str]:
    """Las materias que DECLARA la ficha, de un hecho sólido de materia.

    Mismo criterio que `_familia_de_la_mercancia` y por la misma razón: nunca
    de la descripción comercial. Un cable de acero con alma de fibra nombra dos
    materias ahí y adivinar cuál manda descartaría la posición correcta.
    """
    vistas: set[str] = set()
    for hecho in context.facts:
        if not hecho.is_solid or "material" not in hecho.name.casefold():
            continue
        vistas |= _materias_literales(hecho.value or "")
    return vistas


def _la_materia_de_una_hermana_descarta(
    hermanas: Sequence[TariffCandidate], context: ClassificationContext
) -> list[TariffCandidate]:
    """Las hermanas que la materia de la mercancía no hace imposibles.

    CUANDO LA TARIFA YA DECIDIÓ, NO HACE FALTA QUE DECIDA NADIE

    La partida 7324 —artículos de higiene de fundición, hierro o acero— abre
    cuatro subpartidas:

        732410  «Fregaderos (piletas de lavar) y lavabos, de acero inoxidable.»
        732421  «Bañeras. De fundición, incluso esmaltadas.»
        732429  «Bañeras. Las demás.»
        732490  «Los demás, incluidas las partes.»

    Un fregadero de acero inoxidable AISI 304 empataba con 732421 en
    especificidad —dos calificativos cada una— y el motor se negaba a elegir,
    con razón: contar calificativos no es una razón que nadie firme.

    Pero no hacía falta elegir, hacía falta descartar. La nomenclatura se tomó
    la molestia de abrir DOS posiciones hermanas por materia, y al hacerlo dijo
    que en este nivel la materia separa. Una pieza de acero inoxidable no puede
    ser la de fundición: no por criterio de nadie, sino porque el texto legal de
    al lado ya dice de qué es la otra.

    LA PUERTA QUE HACE ESTO SEGURO

    No se descarta nada si NINGUNA hermana nombra la materia de la ficha. Sin
    eso, la regla afirmaría que la tarifa distingue por materia en niveles donde
    no lo hace, y descartaría la posición correcta por no repetir una palabra —
    el mismo error que clasificó un cable en «De acero sin recubrimiento» por
    compartir «acero» (véase `_el_grupo_la_describe`).

    Una hermana que no nombra materia —«Las demás»— nunca se descarta: no
    afirma nada que contradecir, y es justo la que recoge lo que no encaja en
    las otras.
    """
    ficha = _materias_declaradas(context)
    if not ficha:
        return list(hermanas)

    acepta = frozenset().union(*(_MATERIAS[m] for m in ficha))
    nombradas = {c.code: _materias_literales(c.text) for c in hermanas}

    # LA PUERTA: alguna hermana tiene que reclamar la materia de la ficha.
    if not any(ms & acepta for ms in nombradas.values()):
        return list(hermanas)

    return [c for c in hermanas if not nombradas[c.code] or (nombradas[c.code] & acepta)]


def _umbral_confirmado(candidata: TariffCandidate, context: ClassificationContext) -> bool:
    """¿O no tiene condición medible, o la ficha confirma todas las que tiene?

    `_condiciones` no distingue «no tiene condición» de «la tiene y no se pudo
    evaluar», y esa diferencia decide. Elegir una posición cuyo umbral no se ha
    comprobado es afirmar que la mercancía lo cumple, y eso no lo dice nadie.
    """
    cuantas = len(_CONDICION.findall(_plano(candidata.text)))
    if cuantas == 0:
        return True
    cumplidas, incumplidas = _condiciones(candidata, context)
    return cumplidas == cuantas and not incumplidas


def _nombra_la_materia(candidata: TariffCandidate, context: ClassificationContext) -> bool:
    """¿El texto de esta posición nombra la materia que declara la ficha?

    `_material_contradice` descarta la que nombra OTRA materia. Esto es la
    mitad que faltaba: preferir la que nombra LA SUYA frente a una que no
    nombra ninguna.

    Se compara por término literal y no por familia: «de hierro o acero» para
    un cable de acero, sin que «ferroso» arrastre a una posición de fundición.
    """
    ficha = _materias_declaradas(context)
    if not ficha:
        return False
    acepta = frozenset().union(*(_MATERIAS[m] for m in ficha))
    return bool(_materias_literales(candidata.text) & acepta)


def _material_contradice(candidata: TariffCandidate, familia: str | None) -> str | None:
    """La materia por la que esta candidata es imposible, o `None`.

    Sólo descarta cuando la candidata nombra materia Y NINGUNA de las que
    nombra es la de la mercancía. Una partida que nombra las dos —«de
    plástico reforzado con acero»— no contradice nada.
    """
    if familia is None:
        return None
    nombradas = _familias(candidata.text)
    if not nombradas or familia in nombradas:
        return None
    return ", ".join(sorted(nombradas))


#: Una condición medible del texto legal: «diámetro exterior superior a 406.4
#: mm». Tres partes — de qué habla, en qué sentido, y contra qué número.
_CONDICION = re.compile(
    r"([^\W\d_][^,;:()]{2,40}?)\s+"
    r"(superior a|mayor de|mayor a|inferior a|menor de|menor o igual a|superior o igual a)\s+"
    r"(\d+(?:[.,]\d+)?)",
)

#: Cómo se compara según el sentido. `True` = la mercancía CUMPLE la condición.
_SENTIDOS: dict[str, Any] = {
    "superior a": lambda v, u: v > u,
    "mayor de": lambda v, u: v > u,
    "mayor a": lambda v, u: v > u,
    "superior o igual a": lambda v, u: v >= u,
    "inferior a": lambda v, u: v < u,
    "menor de": lambda v, u: v < u,
    "menor o igual a": lambda v, u: v <= u,
}


def _numero(valor: str) -> Decimal | None:
    """El valor de un hecho como número, si lo es."""
    try:
        return Decimal(valor.strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


#: Sufijos de unidad en los nombres de atributo. No distinguen de qué habla el
#: atributo, sólo en qué se mide, así que no entran en el emparejamiento.
_UNIDADES = frozenset({"mm", "cm", "kg", "gr", "ml", "pulgadas", "grados", "watts", "volts"})


def _hecho_de(context: ClassificationContext, sujeto: str) -> Decimal | None:
    """El valor numérico del hecho del que habla `sujeto`, o `None`.

    Empareja «diámetro exterior superior a 406.4 mm» con `diametro_exterior_mm`
    pidiendo que las palabras DISTINTIVAS del atributo —su nombre sin la
    unidad— estén todas en el sujeto.

    Y si encajan DOS atributos, no cuenta ninguno: con `diametro_mm` y
    `diametro_exterior_mm` en la misma ficha, un sujeto que dice «diámetro
    exterior» los admite a los dos, y elegir uno compararía el umbral legal
    contra una medida distinta de la que nombra. Misma disciplina que en todo
    lo demás: ante la duda, no se decide.
    """
    palabras = set(re.findall(r"[^\W\d_]+", _plano(sujeto)))
    candidatos: list[Decimal] = []
    for hecho in context.facts:
        if not hecho.is_solid:
            continue
        nombre = set(re.findall(r"[^\W\d_]+", _plano(hecho.name))) - _UNIDADES
        valor = _numero(hecho.value or "")
        if nombre and nombre <= palabras and valor is not None:
            candidatos.append(valor)
    return candidatos[0] if len(candidatos) == 1 else None


#: Cuántos términos tiene que cubrir una partida para que se la mire siquiera
#: al recuperar. Dos: con uno entra media tarifa —«acero» solo engancha 89
#: posiciones— y con tres se quedaría fuera la 7305, que es el caso que esto
#: viene a resolver.
_COBERTURA_PARA_RECUPERAR = 2


def _mas_la_que_cumple_una_condicion(
    encontrados: list[TariffCandidate],
    catalog: TariffCatalog,
    context: ClassificationContext,
    terminos: Sequence[str],
) -> list[TariffCandidate]:
    """Las partidas halladas, más la que el recorte de cobertura se llevó.

    LA PARTIDA CORRECTA PUEDE NO LLEGAR A SER CANDIDATA (César, 5-oct)

    `headings()` devuelve sólo las que cubren MÁS términos, y eso evita que el
    ruido gane por la RGI 3 c) —un estropajo llegaba a tener sesenta candidatas
    y la 9605 se las ganaba—. Pero se lleva por delante a la partida correcta
    cuando el vocabulario de la ficha casa mejor con otra.

    El caso medido: una tubería de ⌀1219 mm con los términos `TUBERIA ACERO
    CARBONO COSTURA HELICOIDAL DIAMETRO`.

        7306, 7304, 8481, 3926   casan más términos        -> entran
        7305                     casa «acero» y «diametro» -> SE CORTA

    Y la 7305 es «tubos de sección circular con diámetro exterior superior a
    406.4 mm», que esta tubería cumple con 1219. Era la correcta y no competía.

    POR QUÉ SE PUEDE READMITIR SIN REABRIR EL RUIDO

    No se readmite por existir: se readmite por CUMPLIR una condición medible
    de su propio texto. Eso es una afirmación sobre la mercancía —el documento
    legal fija un umbral y la ficha lo comprueba— y no una coincidencia de
    vocabulario. Es el mismo criterio que `_unica_o_mas_especifica` ya usa para
    desempatar, aplicado un paso antes para que haya con qué desempatar.

    El estropajo no trae ningún dato numérico que cumpla un umbral, así que
    sigue con su única candidata. Lo comprueba la medición, no este comentario.
    """
    if not encontrados:
        return encontrados

    ya = {c.code for c in encontrados}
    try:
        mas_amplio = catalog.headings(
            on_date=context.operation_date,
            terms=terminos,
            cobertura_minima=_COBERTURA_PARA_RECUPERAR,
        )
    except TypeError:
        # Un catálogo que no admite el parámetro: se sigue con lo que haya. El
        # motor no puede exigirle a cada implementación del puerto que soporte
        # una mejora suya.
        return encontrados

    recuperadas = []
    for c in mas_amplio:
        if c.code in ya:
            continue
        cumplidas, incumplidas = _condiciones(c, context)
        if cumplidas and not incumplidas:
            recuperadas.append(c)
    return encontrados + recuperadas


def _condiciones(candidata: TariffCandidate, context: ClassificationContext) -> tuple[int, int]:
    """(cumplidas, incumplidas) de las condiciones medibles de esta candidata.

    Una condición que no se puede evaluar —porque la ficha no trae ese dato—
    no cuenta como ninguna de las dos. El silencio de la ficha no cumple ni
    incumple nada.
    """
    cumplidas = incumplidas = 0
    for sujeto, sentido, umbral in _CONDICION.findall(_plano(candidata.text)):
        valor = _hecho_de(context, sujeto)
        limite = _numero(umbral)
        if valor is None or limite is None:
            continue
        if _SENTIDOS[sentido](valor, limite):
            cumplidas += 1
        else:
            incumplidas += 1
    return cumplidas, incumplidas


def _lo_aprendido_la_descarta(
    candidata: TariffCandidate, context: ClassificationContext
) -> str | None:
    """¿Alguna exclusión aprendida hace imposible esta posición?

    Devuelve el motivo, para que la traza pueda citarlo: quien audite tiene que
    poder ver que se descartó por una respuesta firmada, no por un algoritmo.

    Es el mismo descarte por contradicción que ya hacía con las negaciones del
    texto («sin galvanizar»), con una diferencia: aquella la deducía del texto
    legal y ésta la sabe porque alguien la contestó. Por eso la traza las
    distingue — una se sostiene sola, la otra se sostiene en quien la firmó.
    """
    # ANTES DE NADA: ¿ESTA ficha dice eso? (Persona 1, 5-oct)
    #
    # Faltaba, y el defecto era de los peores: se comprobaba que el término de
    # la TARIFA casara con la candidata y nunca que el término de la FICHA
    # estuviera en esta ficha. Una respuesta firmada sobre un producto
    # descartaba la posición para TODOS.
    #
    # Con la exclusión real que hay cargada —«cerámica vidriada» no es
    # «talavera», firmada por un clasificador— una vajilla que SÍ es de
    # Talavera perdía su fracción, y la traza lo justificaba diciendo «la ficha
    # dice "ceramica vidriada"» sobre una ficha que no dice eso. Un descarte
    # equivocado que se escuda en el nombre de una persona es peor que no tener
    # vocabulario.
    #
    # No lo cazó ninguna medición porque ningún producto limpio del corpus es
    # de Talavera: la precisión se mantuvo en 100 % por cómo está compuesto el
    # corpus, no porque esto estuviera bien.
    #
    # Y EL LADO DE LA TARIFA SE CASA COMO FRASE, NO COMO BOLSA DE PALABRAS
    #
    # Con una intersección de palabras, una respuesta sobre una cláusula se
    # derramaba por cualquier posición que compartiera una palabra común.
    # Medido: contestar «no» a «¿un estropajo de acero inoxidable cumple "Lana
    # de hierro o acero"?» descartaba las TRES hermanas —732310, 732393 y
    # 732394— porque «acero» está en las tres. Y 732393 es «De acero
    # inoxidable», justo la correcta.
    #
    # Una respuesta es sobre UNA frase de UNA posición. Se exige que la frase
    # aparezca en el texto, normalizada y con límite de palabra, para que
    # «acero» no arrastre a «acero inoxidable» ni al revés.
    texto_candidata = _plano(candidata.text)
    ficha_entera = " ".join([context.description, *(f.value or "" for f in context.known_facts())])
    consta = _palabras_con_singular(ficha_entera)
    ficha_plana = _plano(ficha_entera)
    for de_la_ficha, de_la_tarifa in context.exclusiones:
        afirmadas = _palabras_con_singular(de_la_ficha)
        if afirmadas:
            # TODAS las palabras, no alguna: «cerámica vidriada» es una
            # respuesta sobre esas dos juntas. Con una basta, una ficha que
            # sólo dijera «cerámica» arrastraría un veredicto que nadie dio.
            if not afirmadas <= consta:
                continue
        # Un término SIN palabras distintivas —«6x19», una notación— se busca
        # literal. Antes se descartaba por no tener palabras, así que la
        # respuesta se guardaba y no se aplicaba nunca: alguien contestaba y no
        # pasaba nada.
        elif _plano(de_la_ficha).strip() not in ficha_plana:
            continue
        if _frase_en(de_la_tarifa, texto_candidata):
            return f"la ficha dice «{de_la_ficha}», que no es «{de_la_tarifa}»"
    return None


def _frase_en(frase: str, texto_plano: str) -> bool:
    """¿Aparece esa frase en el texto, como frase y no como palabras sueltas?

    Con límite de palabra a los dos extremos para que «acero» no case dentro
    de «acerado» ni «lana» dentro de «planas».
    """
    aguja = _plano(frase).strip(" .,;:")
    if not aguja:
        return False
    return re.search(r"\b" + re.escape(aguja) + r"\b", texto_plano) is not None


def _el_grupo_la_describe(candidata: TariffCandidate, mercancia: str) -> bool:
    """¿El encabezado de guion de esta posición habla de esta mercancía?

    SÓLO EL GRUPO, NO TODO EL TEXTO, Y HAY UNA RAZÓN CARA DETRÁS

    La primera versión miraba el texto entero y clasificó un cable de acero sin
    recubrimiento declarado en «De acero SIN RECUBRIMIENTO» — porque «acero»
    era la única palabra compartida. Afirmaba una ausencia que la ficha no
    dice, que es exactamente lo que el test del silencio existe para impedir.

    «Acero» lo dice media tarifa; que una posición no lo repita no significa
    que su mercancía no lo sea. El encabezado de guion es distinto: la LIGIE lo
    pone AHÍ PRECISAMENTE para separar hermanas —«Los demás monitores:» frente
    a «Proyectores:»— así que casar con él es casar con el discriminador que la
    propia nomenclatura eligió, no con una coincidencia de vocabulario.
    """
    if not candidata.group_text:
        return False
    return bool(_palabras_con_singular(candidata.group_text) & _palabras_con_singular(mercancia))


#: Lo que dice un residual cuando no dice nada más.
_SOLO_RESIDUAL: frozenset[str] = frozenset({"los demas", "las demas", "otros", "otras"})


def _es_residual_puro(candidata: TariffCandidate) -> bool:
    """¿Su texto propio es SÓLO el residual, sin calificar nada?

    Distinto de `_cuelga_de_un_residual`, que mira el encabezado de guion.
    Aquí el texto entero es «Los demás.»: no añade ni una característica. Son
    1 799 fracciones de la TIGIE.

    «Los demás. De acero inoxidable» NO lo es: empieza igual y sigue
    calificando, y por eso sigue pudiendo desempatar.
    """
    return _plano(candidata.text).strip(" .:") in _SOLO_RESIDUAL


def _cuelga_de_un_residual(candidata: TariffCandidate) -> bool:
    """¿Su encabezado de guion es un residual —«Los demás:»?

    La LIGIE agrupa subpartidas bajo una línea sin código, y cuando esa línea
    dice «Los demás:» todo lo que cuelga de ella es residual: recoge lo que no
    cayó en las hermanas específicas. Compararlas de igual a igual es tratar la
    excepción como si fuera la regla.

    Se mira SÓLO el encabezado y no el texto propio: «Los demás. De acero
    inoxidable» es específica DENTRO de su grupo residual, y eso sigue
    valiendo para desempatar entre las de su mismo grupo.
    """
    if not candidata.group_text:
        return False
    plano = _plano(candidata.group_text).strip(" .:")
    return plano in {"los demas", "las demas", "otros", "otras"}


def _algo_la_sostiene(candidata: TariffCandidate, mercancia: str) -> bool:
    """¿Hay algo en la mercancía que respalde lo que esta candidata añade?

    Una candidata «más específica» lo es porque su TEXTO lleva calificativos,
    no porque la mercancía los cumpla. Si ninguno de ellos aparece en lo que
    consta del producto, elegirla es afirmar una característica que el
    documento no dice.
    """
    return bool(_palabras_con_singular(candidata.text) & _palabras_con_singular(mercancia))


def _unica_o_mas_especifica(
    cands: Sequence[TariffCandidate],
    *,
    mercancia: str = "",
    context: ClassificationContext | None = None,
) -> TariffCandidate | None:
    """El único candidato, o el más específico si algo de la mercancía lo sostiene.

    `None` significa que nadie puede decidir con lo que hay, y alguien tiene
    que hacerlo.

    LA ESPECIFICIDAD NO ES EVIDENCIA

    `specificity` mide cuántos calificativos tiene el TEXTO de la fracción, no
    que la mercancía los cumpla. Elegir por ella a secas hace que el motor
    afirme lo que el documento no dice.

    El caso que lo destapó (Persona 1, 28-sep, a partir de un dictamen
    humano): una vajilla de cerámica vidriada competía entre

        69120003  «De Talavera.»   specificity 2
        69120099  «Los demás.»     specificity 0

    y el motor elegía Talavera **cinco veces**, en una mercancía que no
    menciona Talavera en ninguna parte. El agente aduanal y la declaración
    coincidían en «Los demás».

    Ahora la más específica sólo gana si alguna de sus palabras distintivas
    aparece en la mercancía. Si no, se devuelve `None` y decide una persona:
    una fracción equivocada cambia el arancel que paga el importador.
    """
    if len(cands) == 1:
        return cands[0]

    # ── La única cuyo texto describe la mercancía ────────────────────────────
    #
    # Desde el ADR 0004 el texto de una subpartida llega con su nivel de un
    # guion delante: «Los demás monitores. Aptos para ser conectados
    # directamente…». Ese encabezado es lo que distingue a las nueve
    # subpartidas de 8528 —monitores CRT, los demás monitores, proyectores,
    # televisores— que antes decían casi lo mismo.
    #
    # Si EXACTAMENTE UNA comparte palabras distintivas con la mercancía, ésa
    # es la que la describe, y elegirla es una afirmación que se puede leer:
    # «la mercancía dice X y sólo esta posición dice X».
    #
    # Si la comparten varias, no se elige. Y si no la comparte ninguna,
    # tampoco. La regla de siempre: sólo resuelve cuando queda una.
    if mercancia:
        describen = [c for c in cands if _el_grupo_la_describe(c, mercancia)]
        if len(describen) == 1:
            return describen[0]

        # SI VARIAS COMPARTEN EL GRUPO QUE LA DESCRIBE, SE ELIGE ENTRE ÉSAS
        #
        # Esto faltaba y tiraba la mejor pista que da la nomenclatura. Caso
        # real, 43 partidas del corpus (6-oct):
        #
        #     ficha  «TUBERIA DE ACERO AL CARBONO PARA OLEODUCTO, SOLDADA
        #             LONGITUDINALMENTE POR ARCO SUMERGIDO»
        #
        #     730520  spec 3  grupo: —
        #     730531  spec 3  grupo: «Los demás, soldados:»
        #     730539  spec 3  grupo: «Los demás, soldados:»
        #     730511  spec 2  grupo: «Tubos de los tipos utilizados en
        #                             oleoductos o gasoductos:»
        #     730512  spec 0  grupo: el mismo
        #     730519  spec 0  grupo: el mismo
        #     730590  spec 0  grupo: —
        #
        # La ficha dice OLEODUCTO y el encabezado de guion dice oleoductos:
        # la propia LIGIE ya separó a las tres que pueden ser. El motor lo
        # detectaba —`describen` las encontraba— y como eran tres en vez de
        # una, descartaba el hallazgo y pasaba al desempate por especificidad,
        # que lo ganaban 730520, 730531 y 730539: las que NO están en el grupo
        # que describe la mercancía. Tres líderes, ninguna elegida, y la
        # respuesta era «ninguna es más específica» sobre siete candidatas de
        # las que tres ya estaban señaladas.
        #
        # Acotar no es elegir. Dentro del grupo siguen decidiendo las mismas
        # reglas de siempre —condición cumplida, residual, especificidad y
        # `_algo_la_sostiene`—, sólo que entre las que la nomenclatura ya
        # agrupó. Es el mismo criterio que el descarte por residual: primero
        # se quita lo imposible, después se desempata.
        #
        # Y no puede inventar una candidata: `describen` es un subconjunto de
        # `cands`. A diferencia del puente de búsqueda del ADR 0007, esto no
        # cambia QUÉ candidatas se encontraron —no toca el recorte por
        # cobertura— sólo entre cuáles se decide.
        if describen and len(describen) < len(cands):
            cands = describen

    # ── Antes que la especificidad: la condición que la mercancía CUMPLE ──
    #
    # YA SE USA TAMBIÉN AL BAJAR (1-oct). Antes no se podía, y la razón era
    # otra de la que parecía.
    #
    # El texto de una subpartida NO era suyo: `subheadings()` lo derivaba del
    # `min()` de las descripciones de sus fracciones, así que 730520 —«Tubos de
    # entubación (casing)»— le llegaba al motor como «Con espesor de pared
    # inferior a 50.8 mm», el texto de una hija. Con eso, la tubería del corpus
    # resolvía a 73052001 —tubos para extracción de petróleo— porque cumplía un
    # umbral prestado. Pasó de negarse honestamente a contestar mal.
    #
    # La causa no era este desempate: era aquel `min()`. Arreglado en origen —
    # cada nivel lee su propio texto de `tariff_headings` (ADR 0002)— la
    # condición numérica vuelve a ser una afirmación sobre la posición que la
    # declara, y se puede usar para bajar.
    #
    # Una partida que fija un umbral medible y la mercancía lo cumple es más
    # específica en el sentido que importa: el texto legal dice algo
    # comprobable y la ficha lo comprueba. Eso es una razón que un agente
    # aduanal firma; contar calificativos no lo es.
    #
    # El caso real: una tubería de acero de ⌀ 508 mm competía entre 7305
    # —«diámetro exterior superior a 406.4 mm, de hierro o acero»—, 7306 y 8481
    # —grifería—. Las tres empataban en especificidad y la RGI 3 c) elegía la
    # última por numeración: 8481. Grifería, para un tubo.
    #
    # Sólo gana si es la ÚNICA con condición cumplida. Con dos, decide una
    # persona: misma disciplina que el descarte por contradicción.
    if context is not None:
        con_condicion = [(c, _condiciones(c, context)) for c in cands]
        cumplen = [c for c, (ok, mal) in con_condicion if ok and not mal]
        if len(cumplen) == 1:
            return cumplen[0]

    # ── UN RESIDUAL NO EMPATA CON LA ESPECÍFICA (César, 5-oct) ──────────────
    #
    # La partida 7323 abre cinco subpartidas y el motor les daba la misma
    # especificidad a todas:
    #
    #     732310  spec 2  grupo: —             «Lana de hierro o acero;
    #                                           esponjas, estropajos, guantes…»
    #     732393  spec 2  grupo: «Los demás:»  «Los demás. De acero inoxidable.»
    #     732394  spec 2  grupo: «Los demás:»  «Los demás. De hierro o acero…»
    #
    # La 732310 cuelga DIRECTA de la partida; las otras cuatro cuelgan de un
    # grupo «Los demás:». Y un residual no puede empatar con la específica:
    # por construcción recoge lo que NO cayó en ella. La LIGIE lo dice con la
    # línea de guion, y `group_text` ya la traía.
    #
    # Lo encontró un clasificador revisando un estropajo de acero inoxidable:
    # «el motor llegó correctamente a la partida 7323, pero no identificó que
    # existe una subpartida específica para lana de hierro o acero, esponjas y
    # estropajos: 7323.10. Por ello no debía continuar comparando 7323.94 como
    # si fuera igualmente específica.»
    #
    # Sólo se aplica cuando hay de las dos clases: si todas cuelgan de un
    # residual, ninguna tiene ventaja y el desempate sigue como estaba.
    especificas = [c for c in cands if not _cuelga_de_un_residual(c)]
    if especificas and len(especificas) < len(cands):
        cands = especificas
        if len(cands) == 1:
            return cands[0]

    maximo = max(c.specificity for c in cands)
    lideres = [c for c in cands if c.specificity == maximo]
    if len(lideres) != 1 or maximo <= 0:
        return None
    lider = lideres[0]
    return lider if _algo_la_sostiene(lider, mercancia) else None


def _confianza(context: ClassificationContext, *, penalizacion: Decimal = Decimal("0")) -> Decimal:
    """Confianza a partir de la solidez de los hechos, no de una corazonada.

    Se calcula sobre la proporción de hechos OBSERVED o EXTRACTED: una
    clasificación sostenida en datos inferidos por un modelo vale menos que una
    sostenida en la ficha técnica, y el número tiene que reflejarlo.

    `penalizacion` la aplican las reglas de desempate: llegar a la RGI 3 c)
    significa que ninguna razón sustantiva distinguió los candidatos.
    """
    total = len(context.facts)
    if total == 0:
        return max(Decimal("0.0000"), Decimal("0.5000") - penalizacion)
    solidos = sum(1 for f in context.facts if f.is_solid)
    base = Decimal("0.5000") + (Decimal(solidos) / Decimal(total)) * Decimal("0.5000")
    return max(Decimal("0.0000"), min(Decimal("1.0000"), base - penalizacion)).quantize(
        Decimal("0.0001")
    )
