/**
 * Las pantallas de la consola, agrupadas como trabaja una agencia aduanal.
 *
 * Los `id` NO cambian: son la referencia interna (navegación, enlaces desde el
 * Panorama, capturas de los recorridos). Lo que cambia es lo que se lee.
 *
 * NOMBRES COMPROBADOS CONTRA LO QUE HACE CADA PANTALLA (21-oct)
 *
 * - «Pedimentos», no «Pedimento Shadow» ni «Simulación»: la pantalla revisa un
 *   pedimento declarado contra lo que el sistema espera (el Espejo). No
 *   presenta ni simula nada ante la autoridad.
 * - «Expedientes de mercancías»: el Product DNA es la ficha técnica de una
 *   mercancía con la procedencia de cada atributo.
 * - «Revisión»: casos que el motor no pudo sostener y esperan el dictamen de un
 *   clasificador. Es revisión interna, no una autorización.
 */

export type Grupo = 'Operación' | 'Control y cumplimiento' | 'Consulta' | 'Administración'

export type NombreIcono =
  | 'panorama'
  | 'expediente'
  | 'clasificacion'
  | 'pedimento'
  | 'hallazgo'
  | 'evidencia'
  | 'vigilancia'
  | 'revision'
  | 'consulta'
  | 'sistema'

export interface DefinicionPantalla {
  id: string
  titulo: string
  descripcion: string
  grupo: Grupo
  icono: NombreIcono
  /** Falso mientras no exista endpoint: se pinta como Placeholder. */
  implementada: boolean
}

export const GRUPOS: Grupo[] = ['Operación', 'Control y cumplimiento', 'Consulta', 'Administración']

export const PANTALLAS: DefinicionPantalla[] = [
  {
    id: 'executive-dashboard',
    titulo: 'Panorama operativo',
    descripcion: 'Qué requiere atención y en qué está cada operación',
    grupo: 'Operación',
    icono: 'panorama',
    implementada: true,
  },
  {
    id: 'product-dna',
    titulo: 'Expedientes de mercancías',
    descripcion: 'Ficha técnica: los atributos que deciden la clasificación',
    grupo: 'Operación',
    icono: 'expediente',
    implementada: true,
  },
  {
    id: 'classification',
    titulo: 'Clasificación arancelaria',
    descripcion: 'Fracción y NICO propuestos, con su razonamiento',
    grupo: 'Operación',
    icono: 'clasificacion',
    implementada: true,
  },
  {
    id: 'pedimento-shadow',
    titulo: 'Pedimentos',
    descripcion: 'Revisión espejo: lo declarado contra lo esperado',
    grupo: 'Operación',
    icono: 'pedimento',
    implementada: true,
  },
  {
    id: 'finding-detail',
    titulo: 'Hallazgos',
    descripcion: 'Divergencias con su severidad, monto y fuente',
    grupo: 'Control y cumplimiento',
    icono: 'hallazgo',
    implementada: true,
  },
  {
    id: 'evidence',
    titulo: 'Evidencia documental',
    descripcion: 'Las diez preguntas del §49 sobre una decisión',
    grupo: 'Control y cumplimiento',
    icono: 'evidencia',
    implementada: true,
  },
  {
    id: 'regulatory-sentinel',
    titulo: 'Vigilancia normativa',
    descripcion: 'Lo que publicó el DOF y a quién toca',
    grupo: 'Control y cumplimiento',
    icono: 'vigilancia',
    implementada: true,
  },
  {
    id: 'human-review',
    titulo: 'Revisión',
    descripcion: 'Casos que esperan el dictamen de un clasificador',
    grupo: 'Control y cumplimiento',
    icono: 'revision',
    implementada: true,
  },
  {
    id: 'copilot',
    titulo: 'AduLex',
    descripcion: 'Qué dice la norma que regía ese día, con su cita',
    grupo: 'Consulta',
    icono: 'consulta',
    implementada: true,
  },
  {
    id: 'system-status',
    titulo: 'Estado del sistema',
    descripcion: 'Disponibilidad de la infraestructura',
    grupo: 'Administración',
    icono: 'sistema',
    implementada: true,
  },
]
