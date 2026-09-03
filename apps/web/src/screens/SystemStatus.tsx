/**
 * Estado del sistema — la única pantalla con datos reales hoy.
 *
 * Consume GET /health/ready, que reporta Postgres, Redis, Neo4j y MinIO
 * del dev server de Persona 1. Nada aquí es sintético: no lleva badge.
 */

import type { ServiceStatus } from '../api/client'
import { API_BASE_URL } from '../config'
import { useReadiness } from '../hooks/useReadiness'

const NOMBRES: Record<string, string> = {
  postgres: 'PostgreSQL',
  redis: 'Redis',
  neo4j: 'Neo4j',
  minio: 'MinIO',
}

const TEXTO_ESTADO: Record<ServiceStatus, string> = {
  up: 'operativo',
  down: 'caído',
  not_configured: 'sin configurar',
}

function horaLegible(valor: string | Date): string {
  const fecha = valor instanceof Date ? valor : new Date(valor)
  return Number.isNaN(fecha.getTime()) ? '—' : fecha.toLocaleTimeString('es-MX')
}

export function SystemStatus() {
  const { datos, error, cargando, consultadoEn, recargar } = useReadiness()
  const servicios = Object.entries(datos?.services ?? {})

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Estado del sistema</h1>
          <p className="pantalla__sub">
            Infraestructura del equipo · <code>{API_BASE_URL}</code>
          </p>
        </div>
        <button className="boton" onClick={recargar} disabled={cargando}>
          {cargando ? 'Consultando…' : 'Actualizar'}
        </button>
      </header>

      {error && (
        <div className="alerta" role="alert">
          <strong>No hay conexión con la API.</strong>
          <p>{error}</p>
          <p className="alerta__pista">
            Verifica que Tailscale esté activo (<code>tailscale status</code>) y
            que el dev server de Persona 1 esté encendido.
          </p>
        </div>
      )}

      {datos && (
        <>
          <div className={`resumen resumen--${datos.status}`}>
            <span className="resumen__punto" aria-hidden="true" />
            <div>
              <strong>
                {datos.status === 'ready' ? 'Sistema listo' : 'Sistema degradado'}
              </strong>
              <p>
                Reportado por la API a las {horaLegible(datos.timestamp)}
                {consultadoEn && ` · consultado ${horaLegible(consultadoEn)}`}
              </p>
            </div>
          </div>

          <ul className="servicios">
            {servicios.map(([clave, check]) => (
              <li key={clave} className={`servicio servicio--${check.status}`}>
                <span className="servicio__nombre">
                  {NOMBRES[clave] ?? clave}
                </span>
                <span className="servicio__estado">
                  {TEXTO_ESTADO[check.status]}
                </span>
                <span className="servicio__latencia">
                  {check.latency_ms != null ? `${check.latency_ms} ms` : '—'}
                </span>
                {check.detail && (
                  <span className="servicio__detalle">{check.detail}</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {!datos && !error && cargando && <p className="vacio">Consultando la API…</p>}
    </section>
  )
}
