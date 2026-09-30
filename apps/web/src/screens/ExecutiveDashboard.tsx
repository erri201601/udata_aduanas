/**
 * Tablero ejecutivo (§32) — lo primero que ve alguien del cliente.
 *
 * Es la pantalla donde más tienta el número bonito, y por eso es donde más
 * importa no ponerlo. Aquí no hay «ahorro potencial detectado»: sumar
 * hallazgos sin confirmar produce una cifra de folleto que se lee como dinero
 * recuperable y no lo es.
 *
 * Lo que sí se enseña, con el mismo peso visual que lo hecho, es LO PENDIENTE:
 * cuántas decisiones esperan a una persona y cuántos pedimentos nadie ha
 * mirado. Un tablero que sólo cuenta éxitos no sirve para dirigir; sirve para
 * vender, que es otra cosa.
 *
 * SOBRE EL ASPECTO (30-sep, Persona 1)
 *
 * Aquí se probó el rediseño —tarjetas, KPI con la etiqueta arriba, barras— y
 * de aquí se llevó a las otras nueve pantallas. Sus estilos ya no son propios:
 * viven en `.kpi`, `.tarjeta` y `.barras`, que usa toda la consola.
 *
 * Las barras salen de repartos que EXISTEN —severidad de los hallazgos,
 * cobertura de la auditoría—. No hay ni una serie temporal, aunque el ejemplo
 * que inspiró esto las tenga por todas partes: los 16 pedimentos entraron en
 * dos días, y una línea de tiempo con eso sería un adorno que insinúa una
 * historia que no tenemos.
 */

import { useEffect, useState } from 'react'

import { fetchDashboard } from '../api/client'
import type { Dashboard } from '../api/client'
import { SyntheticBanner } from '../components/DataOriginBadge'
import { formatearMonto } from '../components/severity'

type Tono = 'normal' | 'atencion' | 'bien'

/** Una cifra grande, con la etiqueta ARRIBA: se lee antes qué es que cuánto. */
function Kpi({
  valor,
  etiqueta,
  nota,
  tono = 'normal',
}: {
  valor: number | string
  etiqueta: string
  nota?: string
  tono?: Tono
}) {
  return (
    <article className={`kpi kpi--${tono}`}>
      <span className="kpi__etiqueta">{etiqueta}</span>
      <span className="kpi__valor">{valor}</span>
      {nota && <span className="kpi__nota">{nota}</span>}
    </article>
  )
}

interface Barra {
  etiqueta: string
  valor: number
  tono?: Tono
}

/**
 * Barras horizontales proporcionales al mayor valor de SU grupo.
 *
 * Contra el total no: varios de estos repartos no son particiones —una
 * decisión resuelta puede además estar dictaminada—, y una barra que llega al
 * 100 % del total afirmaría un reparto que no existe.
 */
function Barras({ datos }: { datos: Barra[] }) {
  const tope = Math.max(...datos.map((d) => d.valor), 1)
  return (
    <ul className="barras">
      {datos.map((d) => (
        <li key={d.etiqueta} className="barras__fila">
          <span className="barras__etiqueta">{d.etiqueta}</span>
          <span className="barras__pista">
            <span
              className={`barras__barra barras__barra--${d.tono ?? 'normal'}`}
              style={{ width: `${Math.max((d.valor / tope) * 100, d.valor > 0 ? 2 : 0)}%` }}
            />
          </span>
          <span className="barras__valor">{d.valor}</span>
        </li>
      ))}
    </ul>
  )
}

function Tarjeta({
  titulo,
  children,
  pie,
}: {
  titulo: string
  children: React.ReactNode
  pie?: string
}) {
  return (
    <section className="tarjeta">
      <h2 className="tarjeta__titulo">{titulo}</h2>
      {children}
      {pie && <p className="tarjeta__pie">{pie}</p>}
    </section>
  )
}

export function ExecutiveDashboard() {
  const [datos, setDatos] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    const control = new AbortController()

    fetchDashboard(control.signal)
      .then((d) => {
        setDatos(d)
        setError(null)
      })
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setError(causa instanceof Error ? causa.message : 'No se pudo contactar la API')
      })
      .finally(() => {
        if (!control.signal.aborted) setCargando(false)
      })

    return () => control.abort()
  }, [])

  const impacto = datos
    ? formatearMonto(datos.hallazgos.impacto_cuantificado, datos.hallazgos.impacto_moneda)
    : null

  const severidades = Object.entries(datos?.hallazgos.por_severidad ?? {})
  const orden = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
  const porSeveridad: Barra[] = severidades
    .sort((a, b) => orden.indexOf(a[0]) - orden.indexOf(b[0]))
    .map(([nivel, n]) => ({
      etiqueta: nivel,
      valor: n,
      tono: nivel === 'CRITICAL' || nivel === 'HIGH' ? 'atencion' : 'normal',
    }))

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Panorama</h1>
          <p className="pantalla__sub">Qué ha resuelto el sistema, y qué sigue esperando</p>
        </div>
      </header>

      {/* La marca aparece si hay UNA fila simulada, no sólo si lo son todas.
          Cuando entró el primer dictamen humano, `todo_simulado` pasó a falso
          y el banner desapareció — con los 16 pedimentos igual de inventados
          que antes. Una mezcla es justo cuando más hace falta la advertencia
          (§10, §33). */}
      {(datos?.filas_simuladas ?? 0) > 0 && <SyntheticBanner />}

      {error && (
        <div className="alerta" role="alert">
          <strong>No se pudieron cargar las cifras.</strong>
          <p>{error}</p>
        </div>
      )}

      {datos && (
        <>
          <div className="kpis">
            <Kpi valor={datos.clasificaciones.total} etiqueta="Decisiones de clasificación" />
            <Kpi valor={datos.auditoria.pedimentos} etiqueta="Pedimentos auditados" />
            <Kpi
              valor={datos.hallazgos.total}
              etiqueta="Hallazgos"
              tono={datos.hallazgos.total > 0 ? 'atencion' : 'normal'}
            />
            <Kpi
              valor={datos.clasificaciones.dictaminadas}
              etiqueta="Dictaminadas por una persona"
              tono={datos.clasificaciones.dictaminadas > 0 ? 'bien' : 'normal'}
            />
          </div>

          <div className="rejilla">
            <Tarjeta
              titulo="Riesgo por severidad"
              pie="Un CRITICAL entre ochenta y ocho y ochenta y ocho CRITICAL se leían igual. El reparto evita creer que el alarmado es el sistema y no los pedimentos."
            >
              {porSeveridad.length > 0 ? (
                <Barras datos={porSeveridad} />
              ) : (
                <p className="sin-dato">No hay hallazgos.</p>
              )}
            </Tarjeta>

            <Tarjeta
              titulo="Clasificación"
              pie="Estas cifras no suman al total: una decisión resuelta puede además estar dictaminada. Son etiquetas, no un reparto."
            >
              <Barras
                datos={[
                  { etiqueta: 'Resueltas', valor: datos.clasificaciones.resueltas, tono: 'bien' },
                  {
                    etiqueta: 'Esperan a una persona',
                    valor: datos.clasificaciones.requieren_revision,
                    tono: 'atencion',
                  },
                  {
                    etiqueta: 'Dictaminadas',
                    valor: datos.clasificaciones.dictaminadas,
                    tono: 'bien',
                  },
                  {
                    etiqueta: 'Sin información',
                    valor: datos.clasificaciones.sin_informacion,
                  },
                  { etiqueta: 'Con traza', valor: datos.clasificaciones.con_traza },
                ]}
              />
            </Tarjeta>

            <Tarjeta
              titulo="Cobertura de la auditoría"
              pie="«Sin auditar» no es «limpio»: es que nadie los ha mirado. Sólo de los revisados por completo se puede afirmar algo."
            >
              <Barras
                datos={[
                  { etiqueta: 'Auditados', valor: datos.auditoria.auditados },
                  {
                    etiqueta: 'Sin auditar',
                    valor: datos.auditoria.sin_auditar,
                    tono: datos.auditoria.sin_auditar > 0 ? 'atencion' : 'normal',
                  },
                  {
                    etiqueta: 'Revisados por completo',
                    valor: datos.auditoria.auditados_completos,
                    tono: 'bien',
                  },
                ]}
              />
            </Tarjeta>

            <Tarjeta
              titulo="Impacto"
              pie="Sólo lo que tiene monto. Lo demás no se estima: un hallazgo sin importe no es menos grave, es que no se puede presentar como dinero."
            >
              <div className="kpis kpis--interno">
                <Kpi valor={impacto ?? '—'} etiqueta="Cuantificado" />
                <Kpi
                  valor={datos.hallazgos.solo_investigables}
                  etiqueta="Sin monto"
                  nota="Se investigan, no se presentan."
                />
              </div>
            </Tarjeta>

            {datos.oportunidades.total > 0 && (
              <Tarjeta titulo="Oportunidad">
                <div className="kpis kpis--interno">
                  <Kpi valor={datos.oportunidades.total} etiqueta="Oportunidades" tono="bien" />
                  <Kpi
                    valor={
                      formatearMonto(
                        datos.oportunidades.ahorro_cuantificado,
                        datos.oportunidades.ahorro_moneda,
                      ) ?? '—'
                    }
                    etiqueta="Ahorro cuantificado"
                    tono="bien"
                  />
                </div>
              </Tarjeta>
            )}
          </div>

          <p className="tablero__pie">
            {datos.filas_simuladas} de las filas contadas son simulación
            {datos.todo_simulado ? ' — todas' : ', y el resto no'}. No se mezclan con datos
            reales en una misma cifra: una que sumara ambos dejaría de poder presentarse.
          </p>
        </>
      )}

      {!datos && !error && cargando && <p className="vacio">Cargando cifras…</p>}
    </section>
  )
}
