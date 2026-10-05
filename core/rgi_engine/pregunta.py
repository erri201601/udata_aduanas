"""La pregunta exacta que le falta al motor para desempatar.

EL PROBLEMA QUE RESUELVE

Cuando el motor se atasca dice «desempate de subpartida por un clasificador».
Es honesto y es inútil: obliga a la persona a reconstruir desde cero todo el
razonamiento que la máquina ya hizo, y su respuesta resuelve UN caso.

Medido sobre el corpus el 2-oct: 52 decisiones atascadas, concentradas en ocho
familias —8528 con 12, 7305 con 11, 7312 con 8—. La misma duda, una y otra vez.

LO QUE CAMBIA

El motor sabe qué AFIRMA la ficha y qué EXIGE cada candidata. Con eso puede
formular una pregunta de sí o no:

    La ficha dice  proceso_soldadura = «HFW longitudinal»
    La 730511 exige                    «arco sumergido»
    ¿Son lo mismo?

Eso se contesta en cinco segundos, se guarda firmado, y no se vuelve a
preguntar. Un minuto de un clasificador deja de resolver un caso y pasa a
resolver una familia entera.

LO QUE NO HACE

No elige. No propone una respuesta ni la insinúa. Sólo pone delante los dos
textos que no supo reconciliar — porque el puente entre «HFW» y «arco
sumergido» no está en ninguno de los dos documentos, y ningún algoritmo que
lea ambos puede inventarlo.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from core.rgi_engine.context import ClassificationContext, TariffCandidate

#: Más de esto y no es una pregunta: es pedirle a alguien que clasifique.
MAX_CANDIDATAS_PREGUNTABLES: Final[int] = 4

#: Por debajo de esta longitud una palabra no distingue nada.
_MINIMO: Final[int] = 5

#: Tope de la ficha en la pregunta. Más que esto y deja de ser una pregunta
#: para convertirse en el expediente.
_MAXIMO_FICHA: Final[int] = 180


class Pregunta(BaseModel):
    """Lo que el motor necesita saber, en forma de sí o no."""

    model_config = ConfigDict(frozen=True)

    mercancia: str
    """Lo que la ficha dice, compacto: «material = acero galvanizado · …».

    NO SE ELIGE UN ATRIBUTO, Y HAY UNA RAZÓN MEDIDA

    Antes la pregunta emparejaba la cláusula legal con UN atributo de la ficha,
    elegido por heurística. Medido sobre el corpus, la heurística producía
    basura: «¿es "caja 12 unidades" lo mismo que "Lana de hierro o acero"?»
    —embalaje contra materia— y «¿es "10" lo mismo que "constituidos por 7
    alambres"?», donde el 10 era el diámetro y no la construcción.

    Dos heurísticas distintas y las dos fallaron: «el atributo que el texto no
    menciona» y «el que aporta más palabras nuevas». Ninguna mide relevancia;
    miden lo contrario.

    Así que no se empareja. Se pone delante lo que dice la ficha y lo que exige
    la posición, y quien contesta hace el emparejado — que lo hace bien y en un
    segundo, y de ahí sale el término comercial que se guarda firmado.
    """

    codigo: str
    """La posición que no se pudo descartar: `730511`."""

    exige: str
    """Lo que esa posición exige y la ficha no dice con esas palabras."""

    texto: str
    """La pregunta, escrita para una persona."""


def _plano(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore").decode()


def _palabras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[^\W\d_]+", _plano(texto)) if len(p) >= _MINIMO}


def _raices(texto: str) -> set[str]:
    """Las palabras recortadas a su raíz, para que el plural no despiste.

    «cable» y «cables» son la misma palabra, y una pregunta que no lo viera
    preguntaría por algo que la ficha ya dice. Se usa SÓLO para callar
    preguntas, nunca para decidir: un recorte de más hace que preguntemos
    menos, que es el lado seguro del error.
    """
    return {p[:_MINIMO] for p in _palabras(texto)}


def _con_singular(texto: str) -> set[str]:
    """Las palabras del texto y sus singulares, comparadas ENTERAS.

    POR QUÉ NO SIRVE LA RAÍZ DE CINCO AQUÍ

    Recortar a cinco letras hace que «constituidos» y «construcción» sean la
    misma palabra. Y eso callaba justamente la pregunta que hacía falta: la
    ficha del cable dice «CONSTRUCCIÓN 6X19», la fracción exige «constituidos
    por 7 alambres», y el motor daba por resuelto lo que no lo estaba.

    Para callar una pregunta hace falta certeza de que la ficha ya lo dice, y
    una coincidencia de prefijo no es certeza. El plural sí: «cable» y «cables»
    son la misma palabra sin ninguna duda.
    """
    salida: set[str] = set()
    for palabra in _palabras(texto):
        salida.add(palabra)
        if palabra.endswith("es") and len(palabra) - 2 >= _MINIMO:
            salida.add(palabra[:-2])
        if palabra.endswith("s") and len(palabra) - 1 >= _MINIMO:
            salida.add(palabra[:-1])
    return salida


def _la_ficha_cubre(frase: str, consta: set[str]) -> bool:
    """¿La ficha dice todo lo que esta frase exige?

    Palabra a palabra, y cada una vale por sí o por su singular. Comparar los
    conjuntos enteros con `<=` no sirve y costó un test: `_con_singular`
    genera las dos formas, así que «estropajos» produce `{estropajo,
    estropajos}` y una ficha que dice «estropajo» no contiene el plural. El
    conjunto nunca era subconjunto y la frase parecía sin resolver.

    Lo que hace falta es que CADA palabra de la frase esté cubierta por alguna
    forma de la ficha, no que coincidan los dos conjuntos.
    """
    palabras = _palabras(frase)
    if not palabras:
        return False
    return all(_singulares_de(p) & consta for p in palabras)


def _ya_esta_contestada(
    frase: str, context: ClassificationContext, consta: set[str]
) -> tuple[str, str] | None:
    """La respuesta firmada que ya resuelve esta cláusula para ESTA ficha.

    LAS MISMAS PREGUNTAS, UNA Y OTRA VEZ

    Medido el 5-oct sobre la bandeja, al día siguiente de cargar las respuestas
    de César: de las 35 preguntas de la primera pantalla, **26 eran parejas que
    él ya había contestado esa misma tarde**. Veinte tuberías de acero al
    carbono volvían a preguntar si cumplen «de hierro o acero», y él ya había
    firmado que sí.

    El mensaje de conflicto del endpoint de vocabulario promete exactamente
    esto —«el motor ya no debería preguntarla»— y la promesa no se cumplía: el
    generador de preguntas no consultaba la mesa, ni una vez.

    SE MIRAN LOS DOS LADOS, Y ÉSA ES LA PARTE QUE SE OLVIDA

    La cláusula de la tarifa Y que esta ficha diga el término comercial. Con
    sólo el lado de la tarifa, la respuesta de un producto callaría la pregunta
    de todos los demás — que es el mismo defecto que el #177 arregló en el
    descarte, y que volví a cometer en el script con el que medí esto: contó
    tres sartenes como «ya contestados» por una respuesta sobre tuberías de
    acero al carbono.

    CALLARSE NO ES RESOLVER, Y AQUÍ ESO BASTA

    Esta función no elige ninguna fracción ni descarta ninguna: sólo evita la
    pregunta. Así que no puede convertir una negativa honesta en una fracción
    equivocada — el caso sigue en la bandeja, con sus tres botones, para que una
    persona lo dictamine. Lo único que se deja de gastar es su tiempo.
    """
    clausula = _plano(frase)
    for de_la_ficha, de_la_tarifa in (*context.equivalencias, *context.exclusiones):
        de_la_tarifa_plano = _plano(de_la_tarifa)
        if not de_la_tarifa_plano or de_la_tarifa_plano not in clausula:
            continue
        afirmadas = _palabras(de_la_ficha)
        if not afirmadas or not all(_singulares_de(p) & consta for p in afirmadas):
            continue
        return de_la_ficha, de_la_tarifa
    return None


def _singulares_de(palabra: str) -> set[str]:
    """La palabra y su singular, para comparar una sola."""
    formas = {palabra}
    if palabra.endswith("es") and len(palabra) - 2 >= _MINIMO:
        formas.add(palabra[:-2])
    if palabra.endswith("s") and len(palabra) - 1 >= _MINIMO:
        formas.add(palabra[:-1])
    return formas


#: Los separadores con los que la tarifa encadena condiciones, capturados para
#: saber CUÁL cerró cada frase. El punto sólo separa si no está entre dígitos:
#: partir «406.4 mm» daba «superior a 406» y «4 mm», dos frases que no dicen
#: nada y una de ellas con un umbral falso.
_SEPARA = re.compile(r"([,;:]|(?<!\d)\.(?!\d))")


def _frases(texto: str, *, nivel: str = "") -> list[str]:
    """El texto legal partido en las frases con las que la tarifa califica.

    La nomenclatura encadena condiciones con comas y punto y coma —«Galvanizados,
    con un diámetro mayor a 4 mm, constituidos por 7 alambres, lubricados»— y
    cada trozo es una exigencia distinta. Preguntar por el texto entero obliga
    a quien contesta a leer cuatro condiciones para responder a una.

    LOS DOS PUNTOS NO CIERRAN UNA EXIGENCIA: ABREN UN GRUPO

    En una PARTIDA, una frase terminada en «:» es un encabezado de guion — el
    título de las subpartidas que vienen debajo (ADR 0004)— y no una condición
    de la partida. 344 descripciones de partida llevan dos puntos y la muestra
    es inequívoca: «Bovinos domésticos:», «Fresca o refrigerada:», «Mamíferos:».

    Preguntarlo a nivel de partida es destructivo, y lo comprobé simulando la
    respuesta sobre el corpus. La partida 7305 guarda pegado su primer
    encabezado —«Tubos de los tipos utilizados en oleoductos o gasoductos:»— y
    el motor lo preguntaba a 20 tuberías de la bandeja. Un «no» honesto —una
    tubería de conducción de agua industrial NO es de las de oleoducto— borraba
    la partida 7305 entera y el motor caía a `73063004`. César dictaminó
    `73051999`. La pregunta más repetida de la bandeja producía una fracción
    equivocada.

    En una SUBPARTIDA el mismo encabezado va DELANTE y sí la califica: es el
    nivel de guion inmediatamente superior, que es lo que distingue la 730511
    de la 730520. Ahí preguntarlo es correcto y un «no» descarta sólo su grupo.
    Por eso la diferencia es de nivel, no de puntuación.
    """
    piezas = _SEPARA.split(texto)
    frases: list[str] = []
    # `split` con grupo capturador devuelve [cuerpo, sep, cuerpo, sep, …, cuerpo].
    for i in range(0, len(piezas), 2):
        cuerpo = piezas[i].strip()
        cierre = piezas[i + 1] if i + 1 < len(piezas) else ""
        if cierre == ":" and nivel == "HEADING":
            continue
        if len(cuerpo) >= _MINIMO:
            frases.append(cuerpo)
    return frases


def formular(context: ClassificationContext, candidatas: list[TariffCandidate]) -> list[Pregunta]:
    """Las preguntas que desatascarían este caso, o lista vacía.

    SE PREGUNTA POR LO QUE DIFIERE, NO POR LO QUE NO COINCIDE

    La primera versión descartaba una candidata si CUALQUIER palabra suya
    aparecía en la ficha. Con eso, el cable del corpus no generaba ninguna
    pregunta: la ficha dice «GALVANIZADO» y tres de las cuatro fracciones
    dicen «Galvanizados», así que todas parecían ya tocadas. Pero lo que no
    estaba resuelto era otra cosa — el número de alambres — y eso no se
    preguntaba nunca.

    Ahora se mira frase por frase y sólo las que **distinguen** a esa candidata
    de sus hermanas. De las cuatro fracciones de 731210, «Galvanizados» la
    comparten tres: no distingue nada y no se pregunta por ella. «constituidos
    por 7 alambres» es sólo de una, y es exactamente la duda:

        La ficha dice construccion = «6X19».
        La posición 73121007 exige «constituidos por 7 alambres».
        ¿Son lo mismo?

    Con muchas candidatas no se pregunta nada: cuatro preguntas de sí o no no
    son una pregunta, son el trabajo entero. Ahí la respuesta honesta sigue
    siendo mandarlo a un clasificador.

    Y NO SE PREGUNTA LO QUE YA ESTÁ CONTESTADO (5-oct)

    `_ya_esta_contestada` consulta la mesa de vocabulario. Sin eso, el motor
    repetía 26 de las 35 preguntas de la primera pantalla de la bandeja al día
    siguiente de que un clasificador las contestara.
    """
    if not candidatas or len(candidatas) > MAX_CANDIDATAS_PREGUNTABLES:
        return []

    hechos = [h for h in context.facts if h.is_solid and h.value]
    if not hechos:
        return []

    # Todo lo que la ficha dice de la mercancía, incluida su descripción.
    consta = _con_singular(" ".join([context.description, *(h.value or "" for h in hechos)]))

    # La ficha compacta, para que quien conteste tenga delante lo que hace
    # falta sin leerse el expediente.
    mercancia = _la_ficha_en_una_linea(hechos)

    # Cuántas candidatas comparten cada frase: una frase que está en todas no
    # distingue nada, y preguntar por ella no desatasca nada.
    veces: dict[str, int] = {}
    por_candidata: dict[str, list[str]] = {}
    for candidata in candidatas:
        propias = _frases(candidata.text, nivel=candidata.level)
        por_candidata[candidata.code] = propias
        for normalizada in {_plano(f) for f in propias}:
            veces[normalizada] = veces.get(normalizada, 0) + 1

    preguntas: list[Pregunta] = []
    for candidata in candidatas:
        if _la_ficha_ya_cae_en_una_alternativa(candidata.text, consta, candidata.level):
            continue
        frase = _la_frase_que_la_distingue(
            por_candidata[candidata.code], veces=veces, consta=consta, context=context
        )
        if frase is None:
            continue
        preguntas.append(
            Pregunta(
                mercancia=mercancia,
                codigo=candidata.code,
                exige=frase[:120],
                texto=(
                    f"La ficha dice: {mercancia}. "
                    f"La posición {candidata.code} exige «{frase[:120]}». "
                    f"¿La cumple?"
                ),
            )
        )
    return preguntas


def _la_ficha_ya_cae_en_una_alternativa(texto: str, consta: set[str], nivel: str = "") -> bool:
    """¿El texto ofrece ALTERNATIVAS y la ficha cumple una?

    EL PUNTO Y COMA SEPARA ALTERNATIVAS; LA COMA ACUMULA CONDICIONES

        732310  «Lana de hierro o acero; esponjas, estropajos, guantes…»
        73121007 «Galvanizados, con un diámetro…, constituidos por 7 alambres»

    La primera cubre lana O esponjas O estropajos: cumplir una basta. La
    segunda exige todas a la vez. Y eso cambia qué pasa con un «no».

    Un estropajo de acero inoxidable cae en la 732310 por «estropajos», pero
    la frase que la distingue es «Lana de hierro o acero» — y preguntar por ella
    tiene una respuesta natural que es «no». Contestado así, se descarta la
    posición correcta: la respuesta sería cierta sobre la frase y falsa sobre
    la posición.

    Así que cuando el texto ofrece alternativas y la ficha cumple una, no se
    pregunta: ya está respondido por el propio documento.

    El riesgo que queda es apostar a que el punto y coma significa eso en la
    LIGIE. Es su convención y se cumple en los casos medidos, pero es una
    convención tipográfica y no una regla escrita. Se apuesta hacia callar, que
    es el lado seguro: una pregunta de menos deja al motor donde estaba.
    """
    if ";" not in texto:
        return False
    return any(_la_ficha_cubre(frase, consta) for frase in _frases(texto, nivel=nivel))


def _la_frase_que_la_distingue(
    frases: list[str],
    *,
    veces: dict[str, int],
    consta: set[str],
    context: ClassificationContext,
) -> str | None:
    """La primera frase que separa a esta candidata y la ficha no resuelve.

    Cinco condiciones, y las cinco hacen falta:

    1. **Que distinga.** Una frase que comparten varias hermanas no desatasca
       nada: contestarla deja el empate igual.
    2. **Que exija algo.** Un residual —«Los demás»— no exige: recoge lo que no
       cayó en sus hermanas, y no hay respuesta posible a «¿es tu mercancía
       "los demás"?».
    3. **Que no sea algo que el motor pueda MEDIR.** «con un diámetro mayor a
       4 mm pero inferior a 19 mm» lo evalúa `_condiciones` contra la ficha sin
       molestar a nadie. Preguntarlo es pedirle a una persona que haga una
       comparación numérica.
    4. **Que la ficha no la resuelva ya.** Si todas sus palabras constan en la
       ficha, el motor tenía con qué y preguntarlo gasta el tiempo de la única
       persona cuyo tiempo no se puede gastar.
    5. **Que se pueda contestar MIRANDO LA MERCANCÍA.** Una referencia cruzada
       —«excepto los comprendidos en la fracción arancelaria 7312.10.08»— no
       habla de cómo es la mercancía: habla de dónde está clasificada otra. La
       respuesta está en la tarifa, no en la ficha, y quien contesta no la
       tiene.
    6. **Que nadie la haya contestado ya.** Una pareja firmada para esta ficha
       no se vuelve a preguntar. Es lo que el endpoint de vocabulario promete
       por escrito al devolver un 409.
    """
    for frase in frases:
        if veces.get(_plano(frase), 0) > 1:
            continue
        if _es_residual(frase):
            continue
        if _es_umbral_medible(frase):
            continue
        if _permite_las_dos(frase):
            continue
        if _es_referencia_cruzada(frase):
            continue
        if not _palabras(frase) or _la_ficha_cubre(frase, consta):
            continue
        if _ya_esta_contestada(frase, context, consta):
            continue
        return frase
    return None


#: Con qué palabra la tarifa se refiere a otra posición en vez de a la
#: mercancía. Es el mismo criterio que ya usa `_lo_que_excepciona` para no
#: negar por una referencia cruzada, y al generador de preguntas le faltaba.
_SEÑALA_OTRA_POSICION = re.compile(r"\b(fraccion|partida|subpartida|capitulo|inciso)")


def _es_referencia_cruzada(frase: str) -> bool:
    """¿La frase habla de otra posición de la tarifa y no de la mercancía?

    LA PREGUNTA MÁS RENTABLE DEL MOTOR ERA IMPOSIBLE DE CONTESTAR

    Medido el 5-oct sobre el corpus, la primera de la lista por rendimiento
    —14 casos, más que las otras dos juntas— era ésta, sobre la 73121005:

        La tarifa exige: «excepto los comprendidos en la fracción
                          arancelaria 7312.10.08»
        La ficha dice:   material = «acero» · construccion = «6x36» · …
        ¿La cumple?      [sí / no]

    Eso no tiene respuesta. No es una característica del cable: es dónde está
    clasificado otro cable. Quien contesta tendría que resolver primero la
    7312.10.08 —que es justo el empate que la pregunta venía a romper— y nada
    de lo que mire en la ficha se lo va a decir.

    `_lo_que_excepciona` ya se niega a NEGAR por una referencia cruzada, con
    este mismo criterio y por la misma razón. Aquí faltaba, y el precio es
    peor: una exclusión inerte no molesta a nadie, y una pregunta imposible
    gasta el tiempo del clasificador y encima parece trabajo hecho.

    Al descartarla, el motor baja a la siguiente frase que sí distingue y sí se
    puede mirar en la ficha.
    """
    return _SEÑALA_OTRA_POSICION.search(_plano(frase)) is not None


#: Palabras con las que la tarifa fija un umbral. Si además hay un número, es
#: una condición medible y la mide `_condiciones`, no una persona.
_COMPARADORES: Final[tuple[str, ...]] = (
    "mayor",
    "menor",
    "inferior",
    "superior",
    "hasta",
    "desde",
    "excede",
    "exceda",
)


def _es_umbral_medible(frase: str) -> bool:
    """¿Es una condición numérica que el motor puede comprobar solo?"""
    plano = _plano(frase)
    return bool(re.search(r"\d", plano)) and any(c in plano for c in _COMPARADORES)


def _permite_las_dos(frase: str) -> bool:
    """¿La frase admite expresamente las dos cosas? Entonces no exige nada.

    «con o sin lubricación» lo cumple un cable lubricado y uno seco: preguntar
    «¿la cumple?» tiene una sola respuesta posible y no desatasca nada. El
    descarte por contradicción ya tiene esta misma guarda —por eso `_NIEGA`
    lleva un `(?<!con o )`— y al generador de preguntas le faltaba.
    """
    return "con o sin" in _plano(frase)


def _la_ficha_en_una_linea(hechos: list[Any]) -> str:
    """Los hechos sólidos de la ficha, compactos y en su orden.

    Reemplaza a dos heurísticas de emparejado que fallaron las dos. Poner la
    ficha entera cuesta una línea más de lectura y no produce ninguna pregunta
    sin sentido, que es el único error que esta pantalla no puede permitirse:
    gasta el tiempo de la única persona cuyo tiempo no se puede gastar.
    """
    partes = [f"{h.name} = «{h.value}»" for h in hechos if h.value]
    linea = " · ".join(partes)
    return linea[:_MAXIMO_FICHA] if len(linea) > _MAXIMO_FICHA else linea


#: Una posición residual no EXIGE nada: recoge lo que no cayó en sus hermanas.
#: Preguntar «¿es cerámica vidriada lo mismo que "Los demás"?» no tiene
#: respuesta, y una pregunta sin respuesta posible gasta el tiempo de la única
#: persona cuyo tiempo no se puede gastar.
_RESIDUALES: Final[tuple[str, ...]] = (
    "los demas",
    "las demas",
    "los demas,",
    "las demas,",
    "otros",
    "otras",
)


def _es_residual(texto: str) -> bool:
    """¿Es una posición de recogida y no una exigencia?"""
    plano = _plano(texto).strip(" .:")
    return any(plano == r or plano.startswith(r + " ") for r in _RESIDUALES)


def _lo_que_exige(texto: str) -> str:
    """El trozo del texto legal sobre el que se pregunta.

    El texto entero de una posición no es una pregunta —«Los demás, soldados
    longitudinalmente» incluye su encabezado de grupo y su residual—, así que
    se recorta a la primera frase, que es donde la nomenclatura pone el
    calificativo que distingue.
    """
    limpio = texto.split(". ")[-1].strip(" .")
    return limpio[:120]
