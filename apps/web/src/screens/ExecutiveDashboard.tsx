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
 */

import { useEffect, useState } from 'react'

import { fetchDashboard } from '../api/client'
import type { Dashboard } from '../api/client'
import { SyntheticBanner } from '../components/DataOriginBadge'
import { formatearMonto } from '../components/severity'

interface CifraProps {
  valor: number | string
  etiqueta: string
  nota?: string
  tono?: 'normal' | 'atencion' | 'bien'
}

function Cifra({ valor, etiqueta, nota, tono = 'normal' }: CifraProps) {
  return (
    <div className={`tablero__cifra tablero__cifra--${tono}`}>
      <span className="tablero__valor">{valor}</span>
      <span className="tablero__etiqueta">{etiqueta}</span>
      {nota && <span className="tablero__nota">{nota}</span>}
    </div>
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
  const ahorro = datos
    ? formatearMonto(datos.oportunidades.ahorro_cuantificado, datos.oportunidades.ahorro_moneda)
    : null

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Panorama</h1>
          <p className="pantalla__sub">
            Qué ha resuelto el sistema, y qué sigue esperando
          </p>
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
          <h2 className="seccion">Clasificación</h2>
          <div className="tablero">
            <Cifra valor={datos.clasificaciones.total} etiqueta="decisiones" />
            <Cifra
              valor={datos.clasificaciones.resueltas}
              etiqueta="resueltas"
              tono="bien"
            />
            <Cifra
              valor={datos.clasificaciones.requieren_revision}
              etiqueta="esperan a una persona"
              nota="Ni error ni éxito: trabajo pendiente."
              tono={datos.clasificaciones.requieren_revision > 0 ? 'atencion' : 'normal'}
            />
            <Cifra
              valor={datos.clasificaciones.sin_informacion}
              etiqueta="sin información suficiente"
              nota="El motor no pudo, y lo dice."
            />
            <Cifra
              valor={`${datos.clasificaciones.con_traza}/${datos.clasificaciones.total}`}
              etiqueta="con traza conservada"
              nota="De las demás no consta el razonamiento."
            />
          </div>

          <h2 className="seccion">Auditoría de pedimentos</h2>
          <div className="tablero">
            <Cifra valor={datos.auditoria.pedimentos} etiqueta="pedimentos" />
            <Cifra
              valor={datos.auditoria.sin_auditar}
              etiqueta="sin auditar"
              nota="No están limpios: nadie los ha mirado."
              tono={datos.auditoria.sin_auditar > 0 ? 'atencion' : 'normal'}
            />
            <Cifra
              valor={datos.auditoria.auditados_completos}
              etiqueta="revisados por completo"
              nota="Los únicos de los que se puede afirmar que están limpios."
              tono="bien"
            />
          </div>

          <h2 className="seccion">Riesgo detectado</h2>
          <div className="tablero">
            <Cifra valor={datos.hallazgos.total} etiqueta="hallazgos" />
            <Cifra
              valor={datos.hallazgos.peor_severidad ?? '—'}
              etiqueta="peor severidad"
              tono={
                ['CRITICAL', 'HIGH'].includes(datos.hallazgos.peor_severidad ?? '')
                  ? 'atencion'
                  : 'normal'
              }
            />
            <Cifra
              valor={impacto ?? '—'}
              etiqueta="impacto cuantificado"
              nota="Sólo lo que tiene monto. Lo demás no se estima."
            />
            <Cifra
              valor={datos.hallazgos.solo_investigables}
              etiqueta="sin monto"
              nota="Se pueden investigar, no presentar. No son menos graves."
            />
          </div>

          {datos.oportunidades.total > 0 && (
            <>
              <h2 className="seccion">Oportunidad</h2>
              <div className="tablero">
                <Cifra valor={datos.oportunidades.total} etiqueta="oportunidades" />
                <Cifra
                  valor={ahorro ?? '—'}
                  etiqueta="ahorro cuantificado"
                  tono="bien"
                />
              </div>
            </>
          )}

          <p className="tablero__pie">
            {datos.filas_simuladas} de las filas contadas son simulación
            {datos.todo_simulado ? ' — todas' : ', y el resto no'}. No se
            mezclan con datos reales en una misma cifra: una que sumara ambos
            dejaría de poder presentarse.
          </p>
        </>
      )}

      {!datos && !error && cargando && <p className="vacio">Cargando cifras…</p>}
    </section>
  )
}
