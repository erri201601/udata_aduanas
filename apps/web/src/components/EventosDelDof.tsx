/**
 * Lo que publicó el DOF y a quién toca (ADR 0022).
 *
 * Cada publicación se cruza con las fracciones que los clientes declaran o
 * tienen clasificadas: directamente (la nota las cita) o por la NOM que la
 * publicación nombra. Una nota sin leer no se presenta como «no toca nada».
 */

import type { Sentinel } from '../api/client'

type Evento = Sentinel['eventos'][number]

function codigo(fraccion: string): string {
  return fraccion.length === 8
    ? `${fraccion.slice(0, 4)}.${fraccion.slice(4, 6)}.${fraccion.slice(6)}`
    : fraccion
}

function Impacto({ e }: { e: Evento }) {
  if (!e.nota_leida) {
    return (
      <p className="evento__impacto evento__impacto--pendiente">
        Nota aún sin leer: no se sabe qué toca.
      </p>
    )
  }
  if (e.total_afectadas === 0) {
    return (
      <p className="evento__impacto">
        {e.fracciones_citadas > 0
          ? `Cita ${e.fracciones_citadas} fracción(es); ninguna la importa o clasifica un cliente.`
          : 'No cita fracciones ni NOM que exijan las mercancías de los clientes.'}
      </p>
    )
  }
  return (
    <div className="evento__impacto evento__impacto--toca">
      <strong>
        Toca {e.total_afectadas} fracción(es) de los clientes · {e.partidas_afectadas} partida(s)
        {e.todas_simuladas && ' — todas SYNTHETIC DEMO DATA'}
      </strong>
      {e.fracciones_de_clientes.length > 0 && (
        <p>
          La nota las cita: <code>{e.fracciones_de_clientes.map(codigo).join(', ')}</code>
        </p>
      )}
      {e.por_nom.length > 0 && (
        <p>
          Exigen {e.noms.join(', ')}: <code>{e.por_nom.map(codigo).join(', ')}</code>
        </p>
      )}
    </div>
  )
}

export function EventosDelDof({ eventos }: { eventos: Evento[] }) {
  if (eventos.length === 0) return null
  return (
    <section aria-labelledby="eventos-dof-titulo">
      <h2 className="seccion" id="eventos-dof-titulo">
        Lo que publicó el DOF y a quién toca
      </h2>
      <ul className="eventos">
        {eventos.map((e) => (
          <li key={e.url} className="evento">
            <p className="evento__cabecera">
              {e.publicado ?? 'sin fecha'}
              {e.entra_en_vigor && ` · en vigor desde ${e.entra_en_vigor}`}
              {e.vigente_hasta && ` hasta ${e.vigente_hasta}`}
              {e.noms.length > 0 && ` · ${e.noms.join(', ')}`}
            </p>
            <a href={e.url} target="_blank" rel="noreferrer" className="evento__titulo">
              {e.titulo}
            </a>
            <Impacto e={e} />
          </li>
        ))}
      </ul>
    </section>
  )
}
