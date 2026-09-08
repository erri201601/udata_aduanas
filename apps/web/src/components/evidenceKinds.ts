/**
 * Qué significa cada tipo de evidencia, y cuál fundamenta (§8.1).
 *
 * Vive aparte del componente a propósito: es una regla del dominio, no una
 * pieza de interfaz, y cualquier pantalla que muestre evidencia la necesita.
 */

import type { EvidenceKind } from '../api/client'

export interface DescripcionTipo {
  etiqueta: string
  /** ¿Puede sostener una afirmación jurídica? Sólo LEGAL_SOURCE. */
  fundamenta: boolean
  ayuda: string
}

export const TIPOS_EVIDENCIA: Record<EvidenceKind, DescripcionTipo> = {
  LEGAL_SOURCE: {
    etiqueta: 'Fuente jurídica',
    fundamenta: true,
    ayuda: 'Una norma recuperada. Es el único fundamento jurídico.',
  },
  MODEL_OUTPUT: {
    etiqueta: 'Salida de modelo',
    fundamenta: false,
    ayuda: 'Lo produjo un modelo. Interpreta; no fundamenta.',
  },
  DETERMINISTIC: {
    etiqueta: 'Regla de código',
    fundamenta: false,
    ayuda: 'Lo calculó una regla determinista, no una norma.',
  },
  HUMAN: {
    etiqueta: 'Validación humana',
    fundamenta: false,
    ayuda: 'Una persona lo validó. Respalda, pero no sustituye a la norma.',
  },
  COMPARABLE: {
    etiqueta: 'Precedente extranjero',
    fundamenta: false,
    ayuda: 'CBP CROSS, EBTI o WCO. Apoyo interpretativo, nunca base legal en México.',
  },
}

/** ¿Este tipo de evidencia puede sostener una afirmación jurídica? */
export function fundamenta(kind: EvidenceKind | null | undefined): boolean {
  return kind ? TIPOS_EVIDENCIA[kind].fundamenta : false
}
