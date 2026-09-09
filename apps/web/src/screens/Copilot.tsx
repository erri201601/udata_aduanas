/**
 * Copilot (§32) — consulta al corpus jurídico.
 *
 * ESTA PANTALLA NO REDACTA LA RESPUESTA, Y ES UNA DECISIÓN
 *
 * Un asistente que parafrasea la ley es la forma más eficiente de producir
 * una cita inventada. La manera de cumplir el «nunca inventar citas» del
 * maestro no es pedirle al modelo que se porte bien: es no ponerlo en
 * posición de inventar. Aquí se enseñan los PASAJES —artículo, texto,
 * vigencia, procedencia— y quien lee saca la conclusión sobre la norma, no
 * sobre un resumen de ella.
 *
 * LA FECHA NO ES UN FILTRO, ES LA PREGUNTA
 *
 * «¿Qué dice la ley?» no tiene respuesta sin decir cuándo. La misma consulta
 * al 2024 y a hoy devuelve artículos distintos porque la norma cambió, y la
 * pantalla lo enseña en vez de esconderlo detrás de un valor por omisión.
 *
 * Y DICE CON QUÉ BUSCÓ
 *
 * Sin vectores la búsqueda es por término y vigencia. Funciona, pero un
 * pasaje puede salir por contener una sola de las palabras. Cada resultado
 * lleva cuántos términos casó, para que el orden no se lea como pertinencia
 * cuando no lo es.
 */

import { useEffect, useState } from 'react'

import { consultarCopilot, fetchCoberturaCopilot } from '../api/client'
import type { Pasaje, RespuestaCopilot } from '../api/client'
import { DataOriginBadge } from '../components/DataOriginBadge'
import type { DataOrigin } from '../components/DataOriginBadge'

function hoyISO(): string {
  const d = new Date()
  const mes = `${d.getMonth() + 1}`.padStart(2, '0')
  const dia = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${mes}-${dia}`
}

function Resultado({ pasaje, total }: { pasaje: Pasaje; total: number }) {
  const casados = pasaje.terminos_coincidentes.length
  return (
    <li className={`pasaje ${pasaje.puede_fundamentar ? '' : 'pasaje--sin-fundamento'}`}>
      <header className="pasaje__cabecera">
        <div>
          <strong className="pasaje__cita">{pasaje.cita}</strong>
          {pasaje.encabezado && <span className="pasaje__encabezado">{pasaje.encabezado}</span>}
        </div>
        <div className="pasaje__marcas">
          <span
            className={`coincidencia ${casados === total ? 'coincidencia--plena' : ''}`}
            title="Cuántos de los términos buscados aparecen de verdad en este pasaje."
          >
            {casados}/{total} términos
          </span>
          <DataOriginBadge origin={pasaje.data_origin as DataOrigin} />
        </div>
      </header>

      <p className="pasaje__vigencia">
        Vigente desde {pasaje.valid_from}
        {pasaje.valid_to ? ` hasta ${pasaje.valid_to}` : ' · sin fecha de término'}
      </p>

      <p className="pasaje__texto">{pasaje.texto}</p>

      {!pasaje.puede_fundamentar && (
        <p className="pasaje__aviso">
          Esta fuente no puede fundamentar nada: sirve para orientarse, no para sostener una
          afirmación ante nadie.
        </p>
      )}

      <footer className="pasaje__pie">
        {pasaje.terminos_coincidentes.length > 0 && (
          <span>casó: {pasaje.terminos_coincidentes.join(', ')}</span>
        )}
        {pasaje.url && (
          <a href={pasaje.url} target="_blank" rel="noreferrer">
            fuente
          </a>
        )}
      </footer>
    </li>
  )
}

export function Copilot() {
  const [pregunta, setPregunta] = useState('')
  const [fecha, setFecha] = useState(hoyISO)
  const [datos, setDatos] = useState<RespuestaCopilot | null>(null)
  const [cobertura, setCobertura] = useState<RespuestaCopilot | null>(null)
  const [consultando, setConsultando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const control = new AbortController()
    fetchCoberturaCopilot(control.signal)
      .then(setCobertura)
      .catch(() => {
        /* La cobertura es contexto; si falla, la consulta sigue sirviendo. */
      })
    return () => control.abort()
  }, [])

  function preguntar(e: React.FormEvent) {
    e.preventDefault()
    if (pregunta.trim().length < 3) return

    setConsultando(true)
    consultarCopilot({ pregunta, fecha, limite: 8 })
      .then((d) => {
        setDatos(d)
        setError(null)
      })
      .catch((causa: unknown) => {
        setError(causa instanceof Error ? causa.message : 'No se pudo consultar')
      })
      .finally(() => setConsultando(false))
  }


  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Copilot</h1>
          <p className="pantalla__sub">Qué dice la norma que regía ese día, con su cita</p>
        </div>
      </header>

      {cobertura && (
        <div className="alerta" role="note">
          <strong>La búsqueda es por término y vigencia, no por significado.</strong>
          <p>
            Un pasaje puede salir por contener una sola de las palabras buscadas — por eso
            cada resultado enseña cuántos términos casó, y por eso el orden no debe leerse
            como pertinencia.
          </p>
          <p>
            {cobertura.chunks_vectorizados} de {cobertura.chunks_totales} fragmentos ya están
            vectorizados
            {cobertura.chunks_vectorizados > 0
              ? ", pero todavía nadie los usa: falta el adaptador que convierta la pregunta en vector, y conectarlo tiene coste por consulta."
              : "."}
          </p>
        </div>
      )}

      <form className="copilot__forma" onSubmit={preguntar}>
        <label className="copilot__pregunta">
          <span>Pregunta</span>
          <input
            type="text"
            value={pregunta}
            onChange={(e) => setPregunta(e.target.value)}
            placeholder="obligaciones del importador en el valor en aduana"
            minLength={3}
          />
        </label>
        <label className="selector">
          <span>Vigencia al</span>
          <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
        </label>
        <button className="boton" type="submit" disabled={consultando || pregunta.trim().length < 3}>
          {consultando ? 'Consultando…' : 'Consultar'}
        </button>
      </form>

      <p className="copilot__nota">
        La fecha no es un filtro: es parte de la pregunta. «Qué dice la ley» no tiene respuesta
        sin decir cuándo — la misma consulta al 2024 y a hoy devuelve artículos distintos
        porque la norma cambió.
      </p>

      {error && (
        <div className="alerta" role="alert">
          <strong>No se pudo consultar.</strong>
          <p>{error}</p>
        </div>
      )}

      {datos && !datos.hay_fundamento && (
        <div className="alerta" role="note">
          <strong>{datos.sin_evidencia}</strong>
          <p>
            Es una respuesta correcta, no un fallo. Disfrazarla de respuesta parcial sí lo
            sería.
            {datos.descartados_por_vigencia > 0 && (
              <>
                {' '}
                Se descartaron {datos.descartados_por_vigencia} fragmentos por no regir el{' '}
                {datos.fecha}.
              </>
            )}
            {datos.descartados_por_origen > 0 && (
              <>
                {' '}
                Otros {datos.descartados_por_origen} regían pero no pueden fundamentar.
              </>
            )}
          </p>
        </div>
      )}

      {datos && datos.pasajes.length > 0 && (
        <>
          <p className="copilot__resumen">
            {datos.pasajes.length} pasajes vigentes al {datos.fecha} · buscado con{' '}
            {datos.terminos_buscados.map((t) => (
              <code key={t}>{t}</code>
            ))}
            {(datos.descartados_por_vigencia > 0 || datos.descartados_por_origen > 0) && (
              <>
                {' '}
                · descartados: {datos.descartados_por_vigencia} por vigencia,{' '}
                {datos.descartados_por_origen} por procedencia
              </>
            )}
          </p>

          <ul className="pasajes">
            {datos.pasajes.map((p) => (
              <Resultado
                key={`${p.documento}-${p.articulo}-${p.content_hash}`}
                pasaje={p}
                total={datos.terminos_buscados.length}
              />
            ))}
          </ul>

          <p className="tablero__pie">
            El Copilot no redacta la respuesta: enseña la norma. Parafrasear la ley es como se
            producen las citas inventadas, y aquí se prefiere que quien lee saque la conclusión
            sobre el texto — no sobre un resumen de él.
          </p>
        </>
      )}

      {!datos && !error && (
        <p className="vacio">
          Escribe una pregunta sobre la Ley Aduanera o la LIGIE y elige la fecha de la
          operación.
        </p>
      )}
    </section>
  )
}
