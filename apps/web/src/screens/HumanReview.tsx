/**
 * Bandeja de revisión humana (§39).
 *
 * Las correcciones que se hacen aquí son el activo más valioso del sistema:
 * son lo único que ninguna otra parte genera, y lo que permite medir si el
 * motor está mejorando.
 *
 * DOS COSAS QUE ESTA PANTALLA NO PUEDE HACER
 *
 * Confirmar no puede ser más fácil que corregir. Si el botón de aceptar
 * estuviera a un clic y corregir exigiera abrir un formulario, la bandeja se
 * vaciaría a base de confirmaciones sin leer — y las métricas dirían que el
 * motor acierta siempre.
 *
 * Y no se muestra la confianza del motor como una nota grande antes de que la
 * persona decida: un 0.91 predispone a confirmar. Aparece, pero junto al
 * resto, no como titular.
 *
 * TRES SALIDAS, NO DOS
 *
 * «Falta información» es una tercera, y es un veredicto: la persona miró la
 * ficha y dice que con lo que trae no se puede determinar la fracción. En el
 * dictamen del 5-oct César escribió eso en tres casos, y hasta entonces la
 * pantalla sólo sabía confirmar o corregir — así que la única forma de
 * registrarlo era corregir con una fracción inventada.
 *
 * EL NICO SE TECLEA APARTE DE LA FRACCIÓN
 *
 * Son dos niveles y dos campos, no diez dígitos en una caja. «La fracción de 8
 * dígitos y el NICO son niveles distintos; no deben mezclarse» (César, 5-oct).
 */

import { useEffect, useState } from 'react'

import { fetchPendientes, revisarDecision } from '../api/client'
import type { PendienteRead } from '../api/client'
import { ContestarPregunta } from '../components/ContestarPregunta'
import { SyntheticBanner } from '../components/DataOriginBadge'

interface PreguntaRGI {
  mercancia: string
  codigo: string
  exige: string
  texto: string
}

/** Las preguntas del último paso de la traza, si las hay.
 *
 * Se leen del último paso porque es donde el motor se atascó: los anteriores
 * continuaron, y preguntar por una regla que ya pasó no desatasca nada.
 */
function preguntasDe(p: PendienteRead): PreguntaRGI[] {
  const traza = p.rgi_trace
  if (!Array.isArray(traza) || traza.length === 0) return []
  const ultimo = traza[traza.length - 1] as { preguntas?: PreguntaRGI[] } | null
  return ultimo?.preguntas ?? []
}

/**
 * Nombre corto de cada causa. El texto largo lo manda la API en
 * `causas_detalle`: la explicación de qué se le pide al revisor vive junto a
 * la lógica que la determina, no duplicada aquí donde podría desincronizarse.
 */
const ETIQUETAS_CAUSA: Record<string, string> = {
  SIN_INFORMACION: 'Falta información',
  DESEMPATE_POR_NUMERACION: 'Desempate sin razón de fondo',
  SIN_FRACCION_PROPUESTA: 'Sin fracción que confirmar',
  RESUELTA_PERO_MARCADA: 'Resuelta, pero marcada',
}

export function HumanReview() {
  const [pendientes, setPendientes] = useState<PendienteRead[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [enCurso, setEnCurso] = useState<string | null>(null)
  const [hechas, setHechas] = useState<Record<string, string>>({})

  // Estado del formulario de la fila abierta.
  const [abierta, setAbierta] = useState<string | null>(null)
  /** Qué formulario está abierto. Corregir pide fracción; «falta información»
   *  pide el dato que falta, y son preguntas distintas. */
  const [modo, setModo] = useState<'CORRIGE' | 'FALTA_INFORMACION'>('CORRIGE')
  const [revisor, setRevisor] = useState('')
  const [fraccion, setFraccion] = useState('')
  const [nico, setNico] = useState('')
  const [nota, setNota] = useState('')

  useEffect(() => {
    const control = new AbortController()

    fetchPendientes(control.signal)
      .then((filas) => {
        setPendientes(filas)
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

  async function enviar(
    id: string,
    veredicto: 'CONFIRMA' | 'CORRIGE' | 'FALTA_INFORMACION',
  ) {
    setEnCurso(id)
    setError(null)

    try {
      await revisarDecision(id, {
        veredicto,
        reviewer: revisor,
        fraction_code: veredicto === 'CORRIGE' ? fraccion : null,
        // Sólo con fracción: un NICO suelto no identifica nada, y el endpoint
        // lo rechaza. Mandarlo igual daría un 422 que no se entendería desde
        // aquí.
        nico_code: veredicto === 'CORRIGE' && nico ? nico : null,
        nota: nota || null,
      })
      setHechas((h) => ({ ...h, [id]: veredicto }))
      setAbierta(null)
      setFraccion('')
      setNico('')
      setNota('')
    } catch (causa: unknown) {
      setError(causa instanceof Error ? causa.message : 'No se pudo registrar')
    } finally {
      setEnCurso(null)
    }
  }

  const restantes = pendientes.filter((p) => !hechas[p.id])

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Revisión</h1>
          <p className="pantalla__sub">
            Decisiones que el motor no pudo sostener solo
          </p>
        </div>
      </header>

      <SyntheticBanner />

      {error && (
        <div className="alerta" role="alert">
          <strong>No se pudo completar la revisión.</strong>
          <p>{error}</p>
        </div>
      )}

      <label className="revisor">
        <span>Quién revisa</span>
        <input
          value={revisor}
          onChange={(e) => setRevisor(e.target.value)}
          placeholder="tu nombre"
          maxLength={64}
        />
        <em>Una corrección anónima no es auditable.</em>
      </label>

      {restantes.length === 0 && !cargando ? (
        <p className="vacio">
          {pendientes.length > 0
            ? 'Bandeja al día. Las revisiones quedaron registradas.'
            : 'No hay decisiones esperando revisión.'}
        </p>
      ) : (
        <ul className="revisiones">
          {restantes.map((p) => (
            <li key={p.id} className="revision-fila">
              <div className="revision-fila__cabecera">
                <div>
                  <strong>{p.producto ?? 'Producto sin nombre'}</strong>
                  {p.sku && <code className="revision-fila__sku">{p.sku}</code>}
                </div>
                <code className="revision-fila__codigo">
                  {p.fraction_code ?? 'sin fracción'}
                </code>
              </div>

              {p.causas.length > 0 && (
                <ul className="causas">
                  {p.causas.map((causa, i) => (
                    <li key={causa} className={`causa causa--${causa.toLowerCase()}`}>
                      <span className="causa__nombre">{ETIQUETAS_CAUSA[causa] ?? causa}</span>
                      <span className="causa__detalle">{p.causas_detalle[i]}</span>
                    </li>
                  ))}
                </ul>
              )}

              {p.reasoning && <p className="revision-fila__razon">{p.reasoning}</p>}

              {/* LAS PREGUNTAS VAN DONDE SE TRABAJA, NO DONDE SE EXPLICA
                  (Persona 1, 5-oct)
                  El formulario se puso primero en Classification, que es la
                  pantalla para EXPLICAR una decisión. Quien revisa entra aquí,
                  a la bandeja. Tenerlo sólo allí obligaba a salir de la cola,
                  buscar el caso en un selector y encontrar el formulario
                  enterrado en la traza — y una cola que obliga a salir de ella
                  no se usa.
                  El dato ya venía: `PendienteRead` trae `rgi_trace`. */}
              {preguntasDe(p).map((q) => (
                <div className="revision-fila__pregunta" key={`${q.codigo}-${q.exige}`}>
                  <p className="revision-fila__pregunta-texto">{q.texto}</p>
                  <ContestarPregunta
                    exige={q.exige}
                    codigo={q.codigo}
                    mercancia={q.mercancia}
                  />
                </div>
              ))}

              <p className="revision-fila__meta">
                {p.status} · operación del {p.operation_date} ·{' '}
                {p.pasos_traza > 0 ? (
                  `${p.pasos_traza} reglas evaluadas`
                ) : (
                  <span className="sin-traza">
                    sin traza conservada — no consta el razonamiento
                  </span>
                )}
                {p.confidence != null && ` · confianza ${p.confidence}`}
              </p>

              {abierta === p.id && modo === 'CORRIGE' ? (
                <div className="revision-fila__forma">
                  <label>
                    <span>Fracción correcta</span>
                    <input
                      value={fraccion}
                      onChange={(e) => setFraccion(e.target.value)}
                      placeholder="84713001"
                      maxLength={8}
                    />
                  </label>
                  {/* Campo propio, no los dos últimos dígitos de la fracción:
                      son dos decisiones distintas y juntarlas en una caja
                      invita a escribir 7312100502. Opcional — se deja vacío
                      cuando sólo se determina la fracción. */}
                  <label>
                    <span>NICO (opcional)</span>
                    <input
                      value={nico}
                      onChange={(e) => setNico(e.target.value)}
                      placeholder="02"
                      maxLength={2}
                    />
                  </label>
                  <label className="ancho">
                    <span>Por qué</span>
                    <input
                      value={nota}
                      onChange={(e) => setNota(e.target.value)}
                      placeholder="Qué vio el motor que no era"
                    />
                  </label>
                  <div className="revision-fila__acciones">
                    <button
                      className="boton"
                      onClick={() => enviar(p.id, 'CORRIGE')}
                      disabled={!revisor || !fraccion || enCurso === p.id}
                    >
                      {enCurso === p.id ? 'Guardando…' : 'Guardar corrección'}
                    </button>
                    <button className="boton boton--plano" onClick={() => setAbierta(null)}>
                      Cancelar
                    </button>
                  </div>
                </div>
              ) : abierta === p.id ? (
                <div className="revision-fila__forma">
                  {/* Sin campo de fracción a propósito: lo que se está
                      declarando es que no se puede determinar. */}
                  <label className="ancho">
                    <span>Qué dato falta</span>
                    <input
                      value={nota}
                      onChange={(e) => setNota(e.target.value)}
                      placeholder="El diámetro exterior: sin él no se separan 730511 y 730519"
                    />
                  </label>
                  <div className="revision-fila__acciones">
                    <button
                      className="boton"
                      onClick={() => enviar(p.id, 'FALTA_INFORMACION')}
                      disabled={!revisor || !nota.trim() || enCurso === p.id}
                    >
                      {enCurso === p.id ? 'Guardando…' : 'Guardar: hay que pedir el dato'}
                    </button>
                    <button className="boton boton--plano" onClick={() => setAbierta(null)}>
                      Cancelar
                    </button>
                  </div>
                  <p className="revision-fila__aviso">
                    El caso sale de la bandeja y queda pidiendo este dato. No vuelve a
                    aparecer para que nadie repita la misma conclusión.
                  </p>
                </div>
              ) : (
                /* Confirmar y corregir cuestan lo mismo: un clic cada uno. Si
                   aceptar fuera más barato, la bandeja se vaciaría sin leer. */
                <div className="revision-fila__acciones">
                  <button
                    className="boton boton--plano"
                    onClick={() => enviar(p.id, 'CONFIRMA')}
                    disabled={!revisor || enCurso === p.id}
                  >
                    Es correcta
                  </button>
                  <button
                    className="boton boton--plano"
                    onClick={() => {
                      setModo('CORRIGE')
                      setAbierta(p.id)
                    }}
                    disabled={!revisor}
                  >
                    Corregir
                  </button>
                  {/* La tercera salida. Cuesta lo mismo que las otras dos: si
                      fuera más barata se convertiría en la vía de escape de
                      los casos difíciles. */}
                  <button
                    className="boton boton--plano"
                    onClick={() => {
                      setModo('FALTA_INFORMACION')
                      setAbierta(p.id)
                    }}
                    disabled={!revisor}
                  >
                    Falta información
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {cargando && <p className="vacio">Cargando la bandeja…</p>}

      <p className="revisiones__pie">
        Una revisión no borra lo que dijo el motor: crea un registro nuevo. Las
        dos respuestas se conservan porque medir si el sistema mejora exige
        comparar ambas (§39).
      </p>
    </section>
  )
}
