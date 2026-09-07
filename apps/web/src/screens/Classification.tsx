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

/** Estados que no resolvieron: se muestran como tales, no como un hueco. */
const SIN_RESOLVER: Record<string, string> = {
  INSUFFICIENT_INFORMATION: 'No hubo información suficiente para clasificar.',
  HUMAN_REVIEW_REQUIRED: 'Requiere que una persona lo revise antes de usarse.',
  BLOCKED: 'La clasificación no resultó defendible y se bloqueó.',
}

export function Classification() {
  const { decisiones, error: errorLista, cargando: cargandoLista } = useClassifications()
  const [elegida, setElegida] = useState<string | null>(null)
  const activa = elegida ?? decisiones[0]?.id ?? null
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

          {detalle.rgi_path.length > 0 && (
            <ol className="ruta">
              {detalle.rgi_path.map((regla, i) => (
                <li key={regla} className={i === detalle.rgi_path.length - 1 ? 'ruta--final' : ''}>
                  <span className="ruta__regla">{regla}</span>
                  {i === detalle.rgi_path.length - 1 && (
                    <span className="ruta__marca">resolvió</span>
                  )}
                </li>
              ))}
            </ol>
          )}

          {detalle.reasoning && <p className="razonamiento">{detalle.reasoning}</p>}

          {!detalle.trace_available && (
            <div className="traza-parcial" role="note">
              <strong>Traza parcial.</strong>
              <p>
                Se muestran las reglas aplicadas y el razonamiento global, pero
                no el razonamiento de cada paso: el motor lo produce y la base
                todavía no lo guarda. Se dice aquí en vez de presentar una
                explicación incompleta como si fuera completa.
              </p>
            </div>
          )}

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
