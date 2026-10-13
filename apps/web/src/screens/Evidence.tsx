/**
 * Evidence UI — las diez preguntas del §49 sobre una decisión.
 *
 * Es la pantalla que se enseña cuando alguien audita, y por eso es donde
 * mentir cuesta más caro.
 *
 * LA REGLA: SE MUESTRA LO NO RESPONDIDO.
 *
 * Un dossier incompleto pintado como completo miente. Las preguntas sin
 * contestar aparecen en su sitio, marcadas, con el mismo peso que las demás
 * — no se ocultan, no se agrupan al final, no se rellenan con un guion
 * discreto que se lea como «no aplica».
 *
 * Esto se ve peor que un dossier lleno. Es correcto que se vea peor: la
 * diferencia entre «esto está documentado» y «esto tiene huecos» es
 * exactamente lo que quien audita necesita ver de un vistazo.
 */

import { useState } from 'react'

import { SyntheticBanner } from '../components/DataOriginBadge'
import { useDecisionesAuditables, useDossier } from '../hooks/useDossier'
import type { DossierRead } from '../api/client'

/** Las diez del §49, en el orden en que se responden ante una auditoría. */
const PREGUNTAS: { campo: keyof DossierRead; texto: string }[] = [
  { campo: 'what', texto: '¿Qué detectaste?' },
  { campo: 'why', texto: '¿Por qué?' },
  { campo: 'which_rule', texto: '¿Con qué regla?' },
  { campo: 'which_source', texto: '¿Con qué fuente?' },
  { campo: 'source_version', texto: '¿Qué versión de esa fuente?' },
  { campo: 'validity', texto: '¿Cuándo era vigente?' },
  { campo: 'data_used', texto: '¿Qué dato utilizaste?' },
  { campo: 'confidence', texto: '¿Cuánta confianza tienes?' },
  { campo: 'money_impact', texto: '¿Cuánto dinero representa?' },
  { campo: 'requires_human_review', texto: '¿Requiere revisión humana?' },
]

/**
 * Centinela que usa `answer_all()` cuando no pudo responder.
 *
 * Viene como texto dentro de la respuesta, así que sin esto la pantalla
 * pintaría «UNKNOWN» como si fuera un dato — exactamente la mentira que esta
 * pantalla existe para evitar.
 */
const SIN_DATO = 'UNKNOWN'

/** ¿La respuesta dice algo real?
 *
 * `unanswered` es la fuente de verdad: el ensamblado ya decidió qué no pudo
 * contestar. Se comprueba además el contenido, porque un centinela puede
 * viajar dentro de una lista sin que la pregunta entera esté marcada.
 */
function tieneRespuesta(campo: string, valor: unknown, sinResponder: string[]): boolean {
  if (sinResponder.includes(campo)) return false
  if (valor == null) return false
  if (typeof valor === 'boolean') return true
  if (Array.isArray(valor)) {
    return valor.length > 0 && !valor.every((v) => String(v).trim() === SIN_DATO)
  }
  if (typeof valor === 'object') return Object.keys(valor).length > 0
  return String(valor).trim().length > 0 && String(valor).trim() !== SIN_DATO
}

function Respuesta({ valor }: { valor: unknown }) {
  if (typeof valor === 'boolean') {
    return <p>{valor ? 'Sí' : 'No'}</p>
  }
  if (Array.isArray(valor)) {
    return (
      <ul className="respuesta-lista">
        {valor.map((v, i) => (
          <li key={i}>{String(v)}</li>
        ))}
      </ul>
    )
  }
  if (valor && typeof valor === 'object') {
    return (
      <dl className="respuesta-datos">
        {Object.entries(valor as Record<string, unknown>).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{String(v)}</dd>
          </div>
        ))}
      </dl>
    )
  }
  return <p>{String(valor)}</p>
}

export function Evidence() {
  const { decisiones, error: errorLista, cargando: cargandoLista } = useDecisionesAuditables()
  const [elegida, setElegida] = useState<string | null>(null)
  const activa = elegida ?? decisiones[0]?.id ?? null
  const { dossier, error, cargando } = useDossier(activa)

  const sinResponder = dossier?.unanswered ?? []
  const respondidas = dossier
    ? PREGUNTAS.filter((p) => tieneRespuesta(p.campo, dossier[p.campo], sinResponder)).length
    : 0

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Evidencia</h1>
          <p className="pantalla__sub">
            Las diez preguntas del §49 sobre una decisión
          </p>
        </div>
      </header>

      <SyntheticBanner />

      {(errorLista || error) && (
        <div className="alerta" role="alert">
          <strong>No se pudo cargar el dossier.</strong>
          <p>{errorLista ?? error}</p>
        </div>
      )}

      {decisiones.length > 1 && (
        <label className="selector">
          <span>Decisión</span>
          <select value={activa ?? ''} onChange={(e) => setElegida(e.target.value)}>
            {decisiones.map((d) => (
              <option key={d.id} value={d.id}>
                {d.sku ?? 'sin SKU'} · {d.fraction_code ?? d.status} ·{' '}
                {(d.producto ?? '').slice(0, 60)}
              </option>
            ))}
          </select>
        </label>
      )}

      {dossier && (
        <>
          {/* Lo primero: si el dossier está completo o tiene huecos. */}
          <div
            className={`dossier-estado ${dossier.is_complete ? 'dossier-estado--completo' : 'dossier-estado--incompleto'}`}
            role="note"
          >
            {dossier.is_complete ? (
              <strong>Dossier completo — las diez preguntas contestadas.</strong>
            ) : (
              <>
                <strong>
                  Dossier incompleto: {respondidas} de 10 preguntas contestadas.
                </strong>
                <p>
                  Lo que falta se muestra abajo en su sitio. Un dossier con
                  huecos presentado como completo no resiste una auditoría, y
                  la evidencia que falta no aparece por omitir la pregunta.
                </p>
              </>
            )}
          </div>

          {dossier.uninterpretable_evidences > 0 && (
            <div className="alerta" role="note">
              <strong>
                {dossier.uninterpretable_evidences}{' '}
                {dossier.uninterpretable_evidences === 1
                  ? 'evidencia no se pudo usar'
                  : 'evidencias no se pudieron usar'}
                .
              </strong>
              <p className="alerta__pista">
                No declaran su tipo (<code>evidence_kind</code>), y suponerles
                uno sería inventar la procedencia del dato. Si al dossier le
                faltan respuestas, la causa puede estar aquí.
              </p>
            </div>
          )}

          <ol className="preguntas">
            {PREGUNTAS.map(({ campo, texto }, i) => {
              const valor = dossier[campo]
              const contestada = tieneRespuesta(campo, valor, sinResponder)

              return (
                <li
                  key={campo}
                  className={`pregunta ${contestada ? '' : 'pregunta--sin-responder'}`}
                >
                  <span className="pregunta__num">{i + 1}</span>
                  <div className="pregunta__cuerpo">
                    <h3>{texto}</h3>
                    {contestada ? (
                      <Respuesta valor={valor} />
                    ) : (
                      <p className="pregunta__hueco">
                        No se pudo responder con la evidencia disponible.
                      </p>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>

          {sinResponder.length > 0 && (
            <div className="sin-responder">
              <h2 className="seccion">Lo que el ensamblado no alcanzó a contestar</h2>
              <ul>
                {sinResponder.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {!dossier && !error && (cargando || cargandoLista) && (
        <p className="vacio">Cargando el dossier…</p>
      )}

      {!dossier && !cargando && !cargandoLista && !error && !errorLista && (
        <p className="vacio">No hay decisiones que auditar todavía.</p>
      )}
    </section>
  )
}
