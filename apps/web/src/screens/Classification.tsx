/**
 * Classification — la pantalla que se le enseña a AJR (§18, §32, §49).
 *
 * Lo valioso no es el código que devuelve el sistema: es poder explicar cómo
 * se llegó a él. Un agente aduanal firma con su nombre, y no puede firmar una
 * caja negra con un número.
 *
 * Por eso la fracción no es el protagonista visual. Lo son la ruta de reglas,
 * las alternativas descartadas con su motivo, y la evidencia separada por
 * tipo: sólo `LEGAL_SOURCE` fundamenta, y presentar una deducción de modelo
 * con el mismo peso que la LIGIE arruina la credibilidad de todo lo demás.
 */

import { useState } from 'react'

import { SyntheticBanner } from '../components/DataOriginBadge'
import { EvidenceKindBadge } from '../components/EvidenceKindBadge'
import { fundamenta } from '../components/evidenceKinds'
import { useClassification, useClassifications } from '../hooks/useClassifications'

/** Un paso de la traza, tal como lo congela `database/repositories`. */
interface PasoRGI {
  rule_id?: string
  status?: string
  reasoning_summary?: string
  candidate_codes?: string[]
  confidence?: string | null
  missing_information?: string[]
}

/** Estados que no resolvieron: se muestran como tales, no como un hueco. */
const SIN_RESOLVER: Record<string, string> = {
  INSUFFICIENT_INFORMATION: 'No hubo información suficiente para clasificar.',
  HUMAN_REVIEW_REQUIRED: 'Requiere que una persona lo revise antes de usarse.',
  BLOCKED: 'La clasificación no resultó defendible y se bloqueó.',
}

interface Props {
  /** Decisión recién creada. Abre en ella en vez de en la primera. */
  decisionInicial?: string | null
}

export function Classification({ decisionInicial = null }: Props = {}) {
  const { decisiones, error: errorLista, cargando: cargandoLista } = useClassifications()
  const [elegida, setElegida] = useState<string | null>(null)
  const activa = elegida ?? decisionInicial ?? decisiones[0]?.id ?? null
  const { detalle, error, cargando } = useClassification(activa)

  const candidatos = detalle?.candidates ?? []
  const descartados = candidatos.filter((c) => !c.is_selected)
  const evidencias = detalle?.evidences ?? []
  const juridicas = evidencias.filter((e) => fundamenta(e.evidence_kind))
  const interpretativas = evidencias.filter((e) => !fundamenta(e.evidence_kind))

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Classification</h1>
          <p className="pantalla__sub">
            Cómo se llegó a la fracción, no sólo cuál es
          </p>
        </div>
      </header>

      <SyntheticBanner />

      {(errorLista || error) && (
        <div className="alerta" role="alert">
          <strong>No se pudieron cargar las decisiones.</strong>
          <p>{errorLista ?? error}</p>
        </div>
      )}

      {decisiones.length > 1 && (
        <label className="selector">
          <span>Decisión</span>
          <select value={activa ?? ''} onChange={(e) => setElegida(e.target.value)}>
            {decisiones.map((d) => (
              <option key={d.id} value={d.id}>
                {d.fraction_code ?? d.status} — {d.operation_date}
              </option>
            ))}
          </select>
        </label>
      )}

      {detalle && (
        <>
          <div className={`veredicto veredicto--${detalle.status.toLowerCase()}`}>
            {detalle.fraction_code ? (
              <>
                <span className="veredicto__codigo">
                  {detalle.fraction_code}
                  {detalle.nico_code && <em>{detalle.nico_code}</em>}
                </span>
                <p className="veredicto__nota">
                  Fracción arancelaria propuesta · operación del{' '}
                  {detalle.operation_date}
                </p>
              </>
            ) : (
              <>
                <span className="veredicto__codigo veredicto__codigo--sin">
                  Sin fracción
                </span>
                <p className="veredicto__nota">
                  {SIN_RESOLVER[detalle.status] ?? detalle.status}
                </p>
              </>
            )}
          </div>

          {detalle.requires_human_review && (
            <div className="revision" role="note">
              <strong>Requiere revisión humana antes de declararse.</strong>
              {detalle.missing_information.length > 0 && (
                <p>
                  Falta información:{' '}
                  {detalle.missing_information.map((m) => (
                    <code key={m}>{m}</code>
                  ))}
                </p>
              )}
            </div>
          )}

          {/* ── El razonamiento ─────────────────────────────────────────── */}

          <h2 className="seccion">Cómo se llegó</h2>

          {detalle.trace_available && detalle.rgi_trace ? (
            <ol className="traza">
              {(detalle.rgi_trace as PasoRGI[]).map((paso, i) => {
                const ultimo = i === (detalle.rgi_trace?.length ?? 0) - 1

                return (
                  <li
                    key={`${paso.rule_id}-${i}`}
                    className={`paso ${ultimo ? 'paso--final' : ''}`}
                  >
                    <div className="paso__cabecera">
                      <span className="paso__regla">{paso.rule_id}</span>
                      <span className={`paso__estado paso__estado--${(paso.status ?? '').toLowerCase()}`}>
                        {paso.status}
                      </span>
                      {ultimo && <span className="ruta__marca">resolvió</span>}
                    </div>

                    {paso.reasoning_summary && (
                      <p className="paso__razon">{paso.reasoning_summary}</p>
                    )}

                    {paso.candidate_codes && paso.candidate_codes.length > 0 && (
                      <p className="paso__candidatos">
                        Consideró:{' '}
                        {paso.candidate_codes.map((c) => (
                          <code key={c}>{c}</code>
                        ))}
                      </p>
                    )}

                    {paso.missing_information && paso.missing_information.length > 0 && (
                      <p className="paso__falto">
                        Le faltó:{' '}
                        {paso.missing_information.map((m) => (
                          <code key={m}>{m}</code>
                        ))}
                      </p>
                    )}
                  </li>
                )
              })}
            </ol>
          ) : (
            <>
              {detalle.rgi_path.length > 0 && (
                <ol className="ruta">
                  {detalle.rgi_path.map((regla, i) => (
                    <li
                      key={regla}
                      className={i === detalle.rgi_path.length - 1 ? 'ruta--final' : ''}
                    >
                      <span className="ruta__regla">{regla}</span>
                      {i === detalle.rgi_path.length - 1 && (
                        <span className="ruta__marca">resolvió</span>
                      )}
                    </li>
                  ))}
                </ol>
              )}

              <div className="traza-parcial" role="note">
                <strong>De esta decisión no se conservó la traza.</strong>
                <p>
                  Es anterior a que el sistema empezara a guardarla, así que
                  sólo consta qué reglas se aplicaron, no el razonamiento de
                  cada paso. No significa que el motor no evaluara reglas:
                  significa que no lo escribimos. Las decisiones nuevas sí la
                  traen.
                </p>
              </div>
            </>
          )}

          {detalle.reasoning && <p className="razonamiento">{detalle.reasoning}</p>}

          {/* ── Alternativas descartadas ────────────────────────────────── */}

          {descartados.length > 0 && (
            <>
              <h2 className="seccion">Por qué no fue otra cosa</h2>
              <ul className="descartes">
                {descartados.map((c) => (
                  <li key={c.id}>
                    <code className="descartes__codigo">{c.fraction_code ?? '—'}</code>
                    <p>{c.rejected_reason ?? 'Sin motivo registrado.'}</p>
                  </li>
                ))}
              </ul>
            </>
          )}

          {/* ── Evidencia, separada por lo que fundamenta ───────────────── */}

          <h2 className="seccion">En qué se sostiene</h2>

          <div className="evidencias">
            <div className="evidencias__grupo evidencias__grupo--juridica">
              <h3>Fundamento jurídico</h3>
              {juridicas.length === 0 ? (
                <p className="sin-fundamento">
                  Ninguna fuente jurídica respalda esta decisión. No es
                  declarable sin ella.
                </p>
              ) : (
                juridicas.map((e) => (
                  <article key={e.id} className="evidencia-ficha">
                    <EvidenceKindBadge kind={e.evidence_kind} />
                    <p>{e.summary}</p>
                  </article>
                ))
              )}
            </div>

            <div className="evidencias__grupo">
              <h3>Apoyo interpretativo</h3>
              {interpretativas.length === 0 ? (
                <p className="sin-dato">Sin apoyo interpretativo registrado.</p>
              ) : (
                interpretativas.map((e) => (
                  <article key={e.id} className="evidencia-ficha">
                    <EvidenceKindBadge kind={e.evidence_kind} />
                    <p>{e.summary}</p>
                    {e.model_name && (
                      <p className="evidencia-ficha__meta">
                        {e.model_name} · prompt {e.prompt_version ?? '—'}
                      </p>
                    )}
                  </article>
                ))
              )}
            </div>
          </div>
        </>
      )}

      {!detalle && !error && (cargando || cargandoLista) && (
        <p className="vacio">Cargando la decisión…</p>
      )}

      {!detalle && !cargando && !cargandoLista && !error && !errorLista && (
        <p className="vacio">No hay decisiones de clasificación todavía.</p>
      )}
    </section>
  )
}
