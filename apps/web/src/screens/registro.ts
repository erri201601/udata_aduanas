/** Las siete pantallas de §32, más el estado del sistema. */

export interface DefinicionPantalla {
  id: string
  titulo: string
  descripcion: string
  /** Falso mientras no exista endpoint: se pinta como Placeholder. */
  implementada: boolean
}

export const PANTALLAS: DefinicionPantalla[] = [
  {
    id: 'system-status',
    titulo: 'Estado del sistema',
    descripcion: 'Salud de la infraestructura del equipo',
    implementada: true,
  },
  {
    id: 'executive-dashboard',
    titulo: 'Executive Dashboard',
    descripcion: 'Indicadores de operación y oportunidad',
    implementada: false,
  },
  {
    id: 'product-dna',
    titulo: 'Product DNA',
    descripcion: 'Atributos técnicos que determinan la clasificación',
    implementada: true,
  },
  {
    id: 'classification',
    titulo: 'Classification',
    descripcion: 'Motor de RGI y fracción arancelaria propuesta',
    implementada: true,
  },
  {
    id: 'pedimento-shadow',
    titulo: 'Pedimento Shadow',
    descripcion: 'Pedimento sombra contra el declarado',
    implementada: false,
  },
  {
    id: 'finding-detail',
    titulo: 'Finding Detail',
    descripcion: 'Hallazgo con su evidencia y trazabilidad',
    implementada: true,
  },
  {
    id: 'regulatory-sentinel',
    titulo: 'Regulatory Sentinel',
    descripcion: 'Vigilancia de DOF y cambios regulatorios',
    implementada: false,
  },
  {
    id: 'copilot',
    titulo: 'Copilot',
    descripcion: 'Asistente sobre el corpus jurídico y la operación',
    implementada: false,
  },
]
