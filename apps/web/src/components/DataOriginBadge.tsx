/**
 * Marcado de procedencia del dato (§33 del maestro).
 *
 * No es decoración: que alguien confunda un pedimento simulado con uno real
 * en una demo es el peor fallo posible de este producto. Todo dato operativo
 * dummy se marca SYNTHETIC DEMO DATA de forma visible.
 */

export type DataOrigin = 'SYNTHETIC' | 'OFFICIAL' | 'PUBLIC' | 'LICENSED'

const ETIQUETAS: Record<DataOrigin, string> = {
  SYNTHETIC: 'SYNTHETIC DEMO DATA',
  OFFICIAL: 'OFFICIAL SOURCE',
  PUBLIC: 'PUBLIC SOURCE',
  LICENSED: 'LICENSED SOURCE',
}

export function DataOriginBadge({ origin }: { origin: DataOrigin }) {
  return (
    <span className={`badge-origen badge-origen--${origin.toLowerCase()}`}>
      {ETIQUETAS[origin]}
    </span>
  )
}

/** Aviso a pantalla completa para vistas cuyos datos operativos son simulados. */
export function SyntheticBanner() {
  return (
    <div className="aviso-sintetico" role="note">
      <DataOriginBadge origin="SYNTHETIC" />
      <p>Operación simulada. Motor y fuentes reales.</p>
    </div>
  )
}
