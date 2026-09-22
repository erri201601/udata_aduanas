/**
 * Cómo se lee cada tipo de divergencia del §18.
 *
 * Las pantallas mostraban la constante en crudo —`IGI_RATE_MISMATCH`— y quien
 * las va a leer es un agente aduanal, no quien escribió el enum. El nombre
 * técnico no se esconde: viaja en el `title`, porque el que audita necesita
 * poder citar el tipo exacto cuando pregunta por qué salió un hallazgo.
 *
 * Si alguien añade un tipo al §18 y no lo añade aquí, lo caza
 * `test_toda_divergencia_tiene_etiqueta_en_la_interfaz`: la pantalla no puede
 * quedarse callada sobre un hallazgo que el motor sí emite.
 */

export interface Divergencia {
  etiqueta: string
  explica: string
}

export const DIVERGENCIAS: Record<string, Divergencia> = {
  FRACTION_MISMATCH: {
    etiqueta: 'Fracción arancelaria',
    explica: 'La fracción declarada no es la que corresponde a la mercancía.',
  },
  NICO_MISMATCH: {
    etiqueta: 'NICO',
    explica: 'El NICO declarado no corresponde a su fracción.',
  },
  ORIGIN_MISMATCH: {
    etiqueta: 'País de origen',
    explica: 'El origen declarado difiere del esperado. Puede ser legítimo.',
  },
  MISSING_NOM: {
    etiqueta: 'NOM faltante',
    explica: 'La fracción exige una NOM que no se declaró. Detiene la mercancía.',
  },
  IDENTIFIER_MISMATCH: {
    etiqueta: 'Identificador',
    explica: 'Falta un identificador del Anexo 22 o está mal.',
  },
  VALUE_MISMATCH: {
    etiqueta: 'Valor en aduana',
    explica: 'El valor declarado no cuadra con precio pagado más incrementables.',
  },
  IGI_RATE_MISMATCH: {
    etiqueta: 'IGI',
    explica: 'El IGI declarado no corresponde a la tarifa de la fracción declarada.',
  },
  VAT_MISMATCH: {
    etiqueta: 'IVA',
    explica: 'El IVA declarado no cuadra con su base: valor en aduana más IGI más DTA.',
  },
  UNIT_MISMATCH: {
    etiqueta: 'Unidad de medida',
    explica: 'La unidad declarada no existe en el Apéndice 7 del Anexo 22.',
  },
  INCONSISTENT_SKU_CLASSIFICATION: {
    etiqueta: 'SKU clasificado distinto',
    explica: 'El mismo SKU se clasificó de otra forma en operaciones anteriores.',
  },
}

/** La etiqueta, o el tipo en crudo si es uno que esta pantalla no conoce. */
export function etiquetaDe(tipo: string | null | undefined): string {
  if (!tipo) return '—'
  return DIVERGENCIAS[tipo]?.etiqueta ?? tipo
}

/** Qué poner en el `title`: el nombre técnico no se pierde. */
export function detalleDe(tipo: string | null | undefined): string {
  if (!tipo) return ''
  const d = DIVERGENCIAS[tipo]
  return d ? `${tipo} — ${d.explica}` : tipo
}
