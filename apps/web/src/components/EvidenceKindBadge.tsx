/**
 * Tipo de evidencia (§8.1 y regla 3 del prompt de Persona 3).
 *
 * La distinción no es cosmética: `LEGAL_SOURCE` es fundamento jurídico y
 * ninguno de los otros lo es. Dar el mismo peso visual a «lo dice la LIGIE» y
 * a «lo dedujo un modelo» arruina la credibilidad del producto entero, porque
 * quien firma el pedimento deja de poder separar la norma de la conjetura.
 */

import type { EvidenceKind } from '../api/client'
import { TIPOS_EVIDENCIA } from './evidenceKinds'

export function EvidenceKindBadge({ kind }: { kind: EvidenceKind | null | undefined }) {
  // Sin tipo declarado NO se supone uno. Adivinar aquí sería exactamente el
  // error que este componente existe para evitar: presentar como conocida la
  // procedencia de una evidencia que no la declara.
  if (!kind) {
    return (
      <span
        className="evidencia-tipo evidencia-tipo--indefinida"
        title="La evidencia no declara su tipo, así que no puede tratarse como fundamento jurídico."
      >
        Tipo no declarado
      </span>
    )
  }

  const tipo = TIPOS_EVIDENCIA[kind]

  return (
    <span
      className={`evidencia-tipo ${tipo.fundamenta ? 'evidencia-tipo--fundamenta' : ''}`}
      title={tipo.ayuda}
      aria-label={`${tipo.etiqueta}. ${tipo.ayuda}`}
    >
      {tipo.fundamenta && <span aria-hidden="true">§ </span>}
      {tipo.etiqueta}
    </span>
  )
}
