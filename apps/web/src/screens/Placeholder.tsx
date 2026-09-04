/**
 * Pantalla aún sin construir.
 *
 * Todas mostrarán datos operativos simulados, así que llevan el aviso de §33
 * desde ahora: el marcado se hereda del layout, no se parcha al final.
 */

import { SyntheticBanner } from '../components/DataOriginBadge'

interface Props {
  titulo: string
  descripcion: string
}

export function Placeholder({ titulo, descripcion }: Props) {
  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>{titulo}</h1>
          <p className="pantalla__sub">{descripcion}</p>
        </div>
      </header>

      <SyntheticBanner />

      <div className="pendiente">
        <p>Layout pendiente. Sin endpoint disponible todavía.</p>
        <p className="pendiente__nota">
          La API expone hoy únicamente <code>/health</code> y{' '}
          <code>/health/ready</code>.
        </p>
      </div>
    </section>
  )
}
