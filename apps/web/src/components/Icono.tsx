/**
 * Iconos de la consola: trazo de 1.75 px, 20×20, sin librería.
 *
 * Son decorativos (`aria-hidden`): el texto de al lado dice siempre lo mismo
 * que el icono, así que un lector de pantalla no pierde nada.
 */

import type { NombreIcono } from '../screens/registro'

const TRAZOS: Record<NombreIcono | 'menu' | 'cerrar' | 'actualizar' | 'flecha', string> = {
  panorama: 'M3 3h6v8H3zM11 3h6v5h-6zM11 10h6v7h-6zM3 13h6v4H3z',
  expediente: 'M3 5.5A1.5 1.5 0 0 1 4.5 4H8l2 2h5.5A1.5 1.5 0 0 1 17 7.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5zM7 10h6M7 13h4',
  clasificacion: 'M10.6 3H16a1 1 0 0 1 1 1v5.4a1 1 0 0 1-.3.7l-6.6 6.6a1 1 0 0 1-1.4 0l-5.4-5.4a1 1 0 0 1 0-1.4l6.6-6.6a1 1 0 0 1 .7-.3zM13.5 6.5h.01',
  pedimento: 'M5 2.5h7l3 3v12H5zM12 2.5v3h3M7.5 9h5M7.5 12h5M7.5 15h3',
  hallazgo: 'M10 3 2.5 16.5h15zM10 8v4M10 14.2v.01',
  evidencia: 'M14.5 9.5 9 15a3.2 3.2 0 0 1-4.5-4.5l6-6a2.1 2.1 0 0 1 3 3l-6 6a1 1 0 0 1-1.5-1.5L11.5 6.5',
  vigilancia: 'M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10zM10 12.3a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6z',
  revision: 'M4 3h9l3 3v11H4zM7 11l2 2 4-4.5',
  consulta: 'M4 4.5A1.5 1.5 0 0 1 5.5 3H16v12H5.5A1.5 1.5 0 0 0 4 16.5zM4 16.5A1.5 1.5 0 0 0 5.5 18H16v-3M8 7h5',
  sistema: 'M3 4h14v5H3zM3 11h14v5H3zM6 6.5h.01M6 13.5h.01M9 6.5h5M9 13.5h5',
  menu: 'M3 5h14M3 10h14M3 15h14',
  cerrar: 'M5 5l10 10M15 5 5 15',
  actualizar: 'M16 10a6 6 0 1 1-1.8-4.3M16 3.5v3.7h-3.7',
  flecha: 'M7.5 4.5 13 10l-5.5 5.5',
}

export function Icono({
  nombre,
  tamano = 18,
  className,
}: {
  nombre: keyof typeof TRAZOS
  tamano?: number
  className?: string
}) {
  return (
    <svg
      className={className ? `icono ${className}` : 'icono'}
      width={tamano}
      height={tamano}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={TRAZOS[nombre]} />
    </svg>
  )
}
