/**
 * Estado del sistema: la infraestructura de la que depende la consola.
 *
 * Consume GET /health/ready, que reporta Postgres, Redis, Neo4j y MinIO
 * del dev server de Persona 1. Nada aquí es sintético: no lleva badge.
 *
 * Que todo esté disponible dice que los servicios contestan, NO que las
 * operaciones estén validadas. La pantalla lo dice para que nadie lea un
 * «Sistema disponible» como un visto bueno sobre los pedimentos.
 *
 * Direcciones y mensajes técnicos van en un desplegable: sirven para
 * diagnosticar, no para leer el estado.
 */

import type { ServiceStatus } from '../api/client'
import { Icono } from '../components/Icono'
import { API_BASE_URL } from '../config'
import { useReadiness } from '../hooks/useReadiness'

const SERVICIOS: Record<string, { nombre: string; funcion: string }> = {
  postgres: { nombre: 'PostgreSQL', funcion: 'Base principal: pedimentos, tarifa, revisiones' },
  redis: { nombre: 'Redis', funcion: 'Caché y colas' },
  neo4j: { nombre: 'Neo4j', funcion: 'Grafo de relaciones normativas' },
  minio: { nombre: 'MinIO', funcion: 'Documentos fuente tal como llegaron (RAW)' },
}

const ESTADO: Record<ServiceStatus, { texto: string; tono: string }> = {
  up: { texto: 'Disponible', tono: 'ok' },
  down: { texto: 'Sin respuesta', tono: 'mal' },
  not_configured: { texto: 'Sin configurar', tono: 'aviso' },
}

function horaLegible(valor: string | Date): string {
  const fecha = valor instanceof Date ? valor : new Date(valor)
  return Number.isNaN(fecha.getTime()) ? '—' : fecha.toLocaleTimeString('es-MX')
}

export function SystemStatus() {
  const { datos, error, cargando, consultadoEn, recargar } = useReadiness()
  const servicios = Object.entries(datos?.services ?? {})
  const caidos = servicios.filter(([, c]) => c.status !== 'up').length

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Estado del sistema</h1>
          <p className="pantalla__sub">Servicios de infraestructura de los que depende la consola</p>
        </div>
        <button className="boton boton--secundario" onClick={recargar} disabled={cargando}>
          <Icono nombre="actualizar" className={cargando ? 'girando' : undefined} />
          {cargando ? 'Consultando…' : 'Actualizar'}
        </button>
      </header>

      {error && (
        <div className="alerta" role="alert">
          <strong>No hay conexión con la API.</strong>
          <p>{error}</p>
          <p className="alerta__pista">
            Verifica que Tailscale esté activo (<code>tailscale status</code>) y que el dev
            server de Persona 1 esté encendido.
          </p>
        </div>
      )}

      {datos && (
        <>
          <div
            className={`estado-general estado-general--${datos.status === 'ready' ? 'ok' : 'mal'}`}
            role="status"
          >
            <span className="estado-general__punto" aria-hidden="true" />
            <div>
              <strong>
                {datos.status === 'ready'
                  ? 'Todos los servicios disponibles'
                  : `${caidos} ${caidos === 1 ? 'servicio no responde' : 'servicios no responden'}`}
              </strong>
              <p>
                Última comprobación de la API: {horaLegible(datos.timestamp)}
                {consultadoEn && ` · consultado ${horaLegible(consultadoEn)}`}
              </p>
            </div>
          </div>

          <div className="tabla-envoltura">
            <table className="tabla tabla--estado">
              <thead>
                <tr>
                  <th scope="col">Servicio</th>
                  <th scope="col">Disponibilidad</th>
                  <th scope="col" className="num">
                    Latencia
                  </th>
                </tr>
              </thead>
              <tbody>
                {servicios.map(([clave, check]) => {
                  const s = SERVICIOS[clave] ?? { nombre: clave, funcion: '' }
                  const e = ESTADO[check.status]
                  return (
                    <tr key={clave}>
                      <th scope="row" data-etiqueta="Servicio">
                        {s.nombre}
                        {s.funcion && <span className="tenue celda__sub">{s.funcion}</span>}
                      </th>
                      <td data-etiqueta="Disponibilidad">
                        <span className={`chip chip--${e.tono}`}>
                          <span className="chip__punto" aria-hidden="true" />
                          {e.texto}
                        </span>
                      </td>
                      <td data-etiqueta="Latencia" className="num mono">
                        {check.latency_ms != null ? `${check.latency_ms} ms` : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <p className="nota">
            Disponibilidad de infraestructura no equivale a operaciones validadas: que los
            servicios respondan no dice nada sobre si un pedimento está bien.
          </p>

          <details className="bloque desplegable">
            <summary>Detalles técnicos</summary>
            <dl className="detalles">
              <dt>API</dt>
              <dd>
                <code>{API_BASE_URL}</code>
              </dd>
              {servicios.map(([clave, check]) => (
                <div key={clave} className="detalles__fila">
                  <dt>{SERVICIOS[clave]?.nombre ?? clave}</dt>
                  <dd>
                    <code>{check.detail ?? 'sin detalle'}</code>
                  </dd>
                </div>
              ))}
            </dl>
          </details>
        </>
      )}

      {!datos && !error && cargando && (
        <p className="vacio" aria-live="polite">
          Consultando la API…
        </p>
      )}
    </section>
  )
}
