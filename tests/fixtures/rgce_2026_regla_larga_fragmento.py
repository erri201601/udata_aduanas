"""Fragmento REAL (verbatim) del `text` de la regla 1.1.6 de las RGCE 2026,
tal como queda en `regulatory.legal_rules.text` tras `parse_rules` -- una
sola línea continua, sin salto de línea real. Recortado justo antes de la
fracción IV para mantener el fixture legible; conserva tres fracciones
completas (I, II, III), incluidos los incisos "a)"/"b)" reales dentro de la
fracción I y las citas de fracciones de ley ("fracciones I a VI, VIII a XII
y XIV") que el parser NO debe confundir con encabezados de fracción propios.
"""

REGLA_1_1_6_FRAGMENTO = (
    "Para los efectos de los artículos 5o., primer párrafo de la Ley y 2 del "
    "Reglamento, las multas y cantidades en moneda nacional establecidas en la "
    "Ley y el Reglamento, que han sido actualizadas, son las que se dan a "
    "conocer en el Anexo 13. Para los efectos de los artículos antes citados, "
    "en relación con los artículos 17-A, sexto párrafo y 70, último párrafo "
    "del CFF, se dan a conocer los procedimientos para la actualización de "
    "las multas y cantidades en moneda nacional establecidas en la Ley y el "
    "Reglamento: I. Conforme a los artículos 70, último párrafo del CFF, "
    'cuarto y sexto transitorios del "Decreto por el que se reforman, '
    "adicionan y derogan diversas disposiciones del Código Fiscal de la "
    'Federación", publicado en el DOF el 12 de diciembre de 2011, respecto a '
    "la actualización de las multas y cantidades establecidas en la Ley, se "
    "tomará en consideración el periodo comprendido desde el último mes cuyo "
    "Índice Nacional de Precios al Consumidor (INPC) se utilizó para el "
    "cálculo de la última actualización y el mes inmediato anterior a la "
    "entrada en vigor de dicho Decreto, la actualización a partir de enero "
    "de 2012 de las cantidades a que se refiere el Anexo 2 de las Reglas de "
    "Carácter General en Materia de Comercio Exterior para 2011, publicado "
    "en el DOF el 27 de diciembre de 2011, que entraron en vigor a partir "
    "del 1o de enero de 2012, se realizó de acuerdo con el procedimiento "
    "siguiente: a) Conforme a las cantidades establecidas en los artículos "
    "16, fracción II; 160, fracción IX y último párrafo; 164, fracción VII; "
    "165, fracciones II, inciso a) y VII, inciso a); 178, fracción II; 183, "
    "fracciones II y V; 185, fracciones I a VI, VIII a XII y XIV; 185-B; "
    "187, fracciones I, II, IV a VI, VIII, X a XII, XIV y XV; 189, "
    "fracciones I y II; 191, fracciones I a IV; 193, fracciones I a III y "
    "200 de la Ley, fueron actualizadas por última vez en el mes de julio "
    "de 2003 en la modificación al Anexo 2, vigentes a partir del 1 de "
    'julio de 2003" de las Reglas de Carácter General en Materia de '
    "Comercio Exterior para 2003, publicado en el DOF el 29 de julio del "
    "mismo año. b) De esta manera, el periodo que se consideró es el "
    "comprendido entre el mes de mayo de 2003 y el mes de diciembre de "
    "2011. En estos términos, el factor de actualización aplicable al "
    "periodo mencionado, se obtuvo dividiendo el INPC del mes inmediato "
    "anterior al más reciente de dicho periodo entre el INPC correspondiente "
    "al último mes que se utilizó en el cálculo de la última actualización, "
    "por lo que se consideró el INPC del mes de noviembre de 2011 que fue de "
    "102.7070 puntos y el INPC del mes de mayo de 2003, que fue de 71.7880 "
    "puntos. Como resultado de esta operación, el factor de actualización "
    "obtenido y aplicado fue de 1.4306. II. Para la actualización del "
    "artículo 16-A, penúltimo párrafo de la Ley y de conformidad con el "
    'artículo quinto transitorio del "Decreto por el que se reforman, '
    "adicionan y derogan diversas disposiciones del Código Fiscal de la "
    'Federación", publicado en el DOF el 12 de diciembre de 2011, se '
    "utilizó el INPC del mes de noviembre de 2001, toda vez que la reforma "
    "de dicho artículo entró en vigor el 15 de febrero de 2002. En este "
    "sentido y de conformidad con el artículo 17-A, séptimo párrafo del "
    "CFF, se dividió el INPC correspondiente al mes de noviembre de 2011 "
    "que fue de 102.7070 puntos, entre el INPC correspondiente al mes de "
    "noviembre de 2001 que fue de 67.0421 puntos. Como resultado de esta "
    "operación, el factor de actualización obtenido y aplicado fue de "
    "1.5319. Tratándose del artículo 16-B, último párrafo de la Ley y del "
    "artículo Segundo, fracción IV de las Disposiciones Transitorias de la "
    'Ley del "Decreto por el que se reforman, adicionan y derogan diversas '
    'disposiciones de la Ley Aduanera", publicado en el DOF el 30 de '
    "diciembre de 2002; y de conformidad con el artículo quinto transitorio "
    'del "Decreto por el que se reforman, adicionan y derogan diversas '
    'disposiciones del Código Fiscal de la Federación", publicado en el DOF '
    "el 12 de diciembre de 2011, se utilizó el INPC del mes de noviembre de "
    "2002, debido a que la adición del último párrafo del artículo 16-B, "
    "así como de la fracción IV antes referida entraron en vigor el 01 de "
    "enero de 2003. En este sentido y de conformidad con el artículo 17-A, "
    "séptimo párrafo del CFF, se dividió el INPC correspondiente al mes de "
    "noviembre de 2011 que fue de 102.7070 puntos, entre el INPC del mes de "
    "noviembre de 2002 que fue de 70.6544 puntos. Como resultado de esta "
    "operación, el factor de actualización obtenido y aplicado fue de "
    "1.4536. III. Para efectos del artículo 2 del Reglamento publicado en "
    "el DOF el 06 de junio de 1996 y en vigor hasta el 19 de junio de 2015 "
    "y de conformidad con el artículo 70 del CFF, las cantidades "
    "establecidas en los artículos 71, fracción III; 129, primer párrafo y "
    "170, fracción III del referido Reglamento, se actualizaron utilizando "
    "el INPC del mes de noviembre de 1996, debido a que el artículo cuarto "
    "transitorio del mencionado Reglamento, establece que la actualización "
    "de las cantidades se efectuará a partir del 01 de enero de 1997. En "
    "este sentido y de conformidad con el artículo 17-A, séptimo párrafo "
    "del CFF, se dividió el INPC correspondiente al mes de noviembre de "
    "2011 que fue de 102.7070 puntos, entre el INPC del mes de noviembre de "
    "1996 que fue de 37.0944 puntos. Como resultado de esta operación, el "
    "factor de actualización obtenido y aplicado fue de 2.7688."
)
