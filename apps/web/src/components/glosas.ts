/**
 * Qué significa cada número y cada palabra técnica de la traza de la RGI.
 *
 * POR QUÉ ESTO VIVE EN LA CONSOLA Y NO EN UN MANUAL
 *
 * Quien enseña esta pantalla no siempre es quien la construyó, y quien la mira
 * casi nunca lo es. Un `0.4500` sin explicación se lee como «45 % de
 * probabilidad de acertar», que es lo contrario de lo que significa — y esa
 * lectura convierte la mejor parte del sistema, que declara cuándo desempató
 * por la letra, en una debilidad aparente.
 *
 * Las glosas dicen QUÉ PREGUNTA cada regla, no cómo está implementada: son de
 * la LIGIE, no nuestras, y no cambian cuando cambie el motor.
 */

/** Qué pregunta cada Regla General de Interpretación. */
export const QUE_PREGUNTA: Record<string, string> = {
  'RGI-1': '¿El texto de alguna partida describe esta mercancía?',
  'RGI-2': '¿Viene incompleta, sin terminar o desmontada?',
  'RGI-3a': 'Si varias encajan, ¿alguna la describe de forma más específica?',
  'RGI-3b': '¿Qué le da el carácter esencial?',
  'RGI-3c': 'Sin desempate: la de número más alto. Por la letra, no por el fondo.',
  'RGI-4': '¿A qué mercancía análoga se parece más?',
  'RGI-5': 'Estuches y envases: ¿siguen a lo que contienen?',
  'RGI-6': 'Lo mismo que arriba, pero ya dentro de la partida elegida.',
}

/** Qué significa el estado de un paso. */
export const QUE_ES_EL_ESTADO: Record<string, string> = {
  CONTINUE: 'Esta regla no resolvió. Se pasa a la siguiente.',
  RESOLVED: 'Esta regla decidió.',
  HUMAN_REVIEW_REQUIRED: 'No pudo, y dice qué le falta. Decide una persona.',
  INSUFFICIENT_INFORMATION: 'Falta un dato de la ficha del producto, no de la tarifa.',
  BLOCKED: 'Lo que salió no se sostenía con la evidencia, y se bloqueó.',
}

/**
 * Cómo leer la confianza de un paso.
 *
 * NO es probabilidad de acertar: es cuánto sostiene lo que el motor usó. La
 * distinción importa porque un 0.45 «probabilidad» invita a ignorarlo, y un
 * 0.45 «desempaté por numeración» invita a revisarlo, que es lo correcto.
 *
 * La RGI 3 c) se nombra aparte porque no es cuestión de grado: esa regla
 * resuelve SIEMPRE por orden de numeración, y eso hay que decirlo con
 * palabras, no dejarlo en un número bajo que cada uno interprete.
 */
export function comoLeerLaConfianza(valor: string | null | undefined, regla?: string): string {
  if (valor == null) return ''
  if (regla === 'RGI-3c') {
    return 'Desempatada por orden de numeración, no por una razón de fondo. Por eso pide revisión.'
  }
  const n = Number(valor)
  if (Number.isNaN(n)) return ''
  if (n >= 0.85) return 'Alta: contrasta el texto legal con un dato que consta en la ficha.'
  if (n >= 0.6) return 'Media: parte de lo que la sostiene es deducido, no leído del documento.'
  return 'Baja: el motor llegó aquí sin apoyo firme. No debería usarse sin revisar.'
}
