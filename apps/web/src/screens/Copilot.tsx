/**
 * AduLex (§32) — consulta al corpus jurídico.
 *
 * El fichero, la ruta de la API y los tipos siguen diciendo «copilot»: es el
 * nombre del §32 del maestro y renombrarlo tocaría el contrato de la API sin
 * que el usuario gane nada. Lo que se llama AduLex es la pantalla.
 *
 * LA RESPUESTA VA ENCIMA DE LOS PASAJES, NO EN SU LUGAR (ADR 0010, 13-oct)
 *
 * Un asistente que parafrasea la ley es la forma más eficiente de producir
 * una cita inventada. Hasta el 13-oct esta pantalla no redactaba por eso.
 * Ahora sí, pero cada oración cita un pasaje como [n], el servidor descarta la
 * redacción entera si cita uno que no existe, y los pasajes siguen debajo
 * —enteros— para que cada [n] se pueda comprobar contra el texto de la norma.
 * Cada [n] es un enlace a su pasaje.
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

import { Chip } from '../components/Expediente'
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

/** El texto de `answer` con cada [n] convertido en enlace a su pasaje. */
function ConCitas({ texto }: { texto: string }) {
  const partes = texto.split(/(\[\d+(?:\s*,\s*\d+)*\])/g)
  return (
    <>
      {partes.map((parte, i) => {
        const cita = parte.match(/^\[([\d,\s]+)\]$/)
        if (!cita) return <span key={i}>{parte}</span>
        const numeros = cita[1].split(',').map((n) => n.trim())
        return (
          <span key={i} className="cita">
            [
            {numeros.map((n, j) => (
              <span key={n}>
                {j > 0 && ', '}
                <a href={`#pasaje-${n}`}>{n}</a>
              </span>
            ))}
            ]
          </span>
        )
      })}
    </>
  )
}

/** La redacción del §31: respuesta, de qué se fía y qué le falta. */
function Redaccion({ datos }: { datos: RespuestaCopilot }) {
  const confianza = Number(datos.confidence)
  return (
    <div className={`redaccion${datos.requires_human_review ? ' redaccion--revisar' : ''}`}>
      <p className="redaccion__texto">
        {datos.redacta_respuesta ? <ConCitas texto={datos.answer} /> : <strong>{datos.answer}</strong>}
      </p>

      <dl className="redaccion__meta">
        <div>
          <dt>Oraciones con cita</dt>
          {/* Es lo que mide `confidence` (ADR 0010): no la seguridad que el
              modelo dice tener, que no está calibrada. */}
          <dd>{Math.round(confianza * 100)} %</dd>
        </div>
        <div>
          <dt>Revisión humana</dt>
          <dd>
            {datos.requires_human_review ? <Chip tono="aviso">requerida</Chip> : 'no requerida'}
          </dd>
        </div>
        {datos.prompt_version && (
          <div>
            <dt>Prompt</dt>
            <dd>
              {datos.prompt_id} v{datos.prompt_version}
            </dd>
          </div>
        )}
      </dl>

      {datos.missing_information.length > 0 && (
        <div className="redaccion__falta">
          <strong>Lo que la pregunta necesita y los pasajes no traen</strong>
          <ul>
            {datos.missing_information.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {datos.sources.length > 0 && (
        <p className="redaccion__fuentes">
          Citado:{' '}
          {datos.sources.map((f) => (
            <a key={f.n} href={`#pasaje-${f.n}`} className="redaccion__fuente">
              [{f.n}] {f.documento}
              {f.articulo ? `, art. ${f.articulo}` : ''}
            </a>
          ))}
        </p>
      )}
    </div>
  )
}

function Resultado({ pasaje, total }: { pasaje: Pasaje; total: number }) {
  const casados = pasaje.terminos_coincidentes.length
  return (
    <li
      id={`pasaje-${pasaje.n}`}
      className={`pasaje ${pasaje.puede_fundamentar ? '' : 'pasaje--sin-fundamento'}`}
    >
      <header className="pasaje__cabecera">
        <div>
          <strong className="pasaje__cita">
            <span className="pasaje__n">[{pasaje.n}]</span> {pasaje.cita}
          </strong>
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
          {/* El grafo dice dónde mirar; el texto, la vigencia y el hash de
              este pasaje salen igual de Postgres (§28). */}
          {pasaje.via_grafo && (
            <span
              className="pasaje__grafo"
              title="Lo sugirió el Knowledge Graph: lo citan decisiones sobre la fracción preguntada."
            >
              sugerido por el grafo
            </span>
          )}
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
          <h1>AduLex</h1>
          <p className="pantalla__sub">Qué dice la norma que regía ese día, con su cita</p>
        </div>
      </header>

      {datos?.degradado_por && (
        <div className="alerta" role="note">
          <strong>Esta consulta se resolvió por término, no por significado.</strong>
          <p>{datos.degradado_por}</p>
          <p>
            No es un fallo: la consulta siguió respetando la vigencia (§14) y los pasajes
            fundamentan igual. Busca peor, y por eso se dice — cada resultado enseña cuántos
            términos casó para que el orden no se lea como pertinencia.
          </p>
        </div>
      )}

      {datos && !datos.degradado_por && datos.modo_busqueda === "SEMANTICA" && (
        <p className="copilot__modo">
          Búsqueda por significado sobre {cobertura?.chunks_vectorizados ?? 0} fragmentos
          vectorizados. El orden es por cercanía semántica, no por coincidencia de palabras.
        </p>
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

      {datos?.grafo && <p className="copilot__modo">{datos.grafo}</p>}
      {datos && <Redaccion datos={datos} />}

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
            La respuesta de arriba sólo puede citar estos pasajes, y cada [n] lleva a su texto.
            Si citara uno que no está aquí, el servidor la descarta entera: una cita inventada
            invalida todo lo demás.
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
