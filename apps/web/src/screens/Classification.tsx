/**
 * Classification — la pantalla que se le enseña al cliente (§18, §32, §49).
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

import { ComoSeLeeUnCodigo } from '../components/ComoSeLeeUnCodigo'
import { SyntheticBanner } from '../components/DataOriginBadge'
import { QUE_ES_EL_ESTADO, QUE_PREGUNTA, comoLeerLaConfianza } from '../components/glosas'
import { EvidenceKindBadge } from '../components/EvidenceKindBadge'
import { fundamenta } from '../components/evidenceKinds'
import { useClassification, useClassifications } from '../hooks/useClassifications'

interface PreguntaRGI {
  atributo: string
  valor_declarado: string
  codigo: string
  exige: string
  texto: string
}

/** Un paso de la traza, tal como lo congela `database/repositories`. */
interface PasoRGI {
  rule_id?: string
  status?: string
  reasoning_summary?: string
  candidate_codes?: string[]
  confidence?: string | null
  missing_information?: string[]
  preguntas?: PreguntaRGI[]
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
          <ComoSeLeeUnCodigo />

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

          {/* El dictamen va ANTES del aviso de revisión: si alguien ya se
              pronunció, enseñar primero «requiere que una persona lo revise»
              deja invisible el trabajo del clasificador justo donde más
              falta hace. */}
          {detalle.dictamen && (
            <div className="dictamen" role="note">
              <strong>
                Ya lo dictaminó una persona
                {detalle.dictamen.fraction_code
                  ? ': '
                  : ', y coincide en que no se puede determinar.'}
                {detalle.dictamen.fraction_code && (
                  <code className="dictamen__codigo">
                    {detalle.dictamen.fraction_code}
                  </code>
                )}
              </strong>
              {detalle.dictamen.reasoning && <p>{detalle.dictamen.reasoning}</p>}

              {/* Un veredicto humano es autoridad sobre el CRITERIO, no sobre
                  qué códigos existen. Un dígito mal teclado no se convierte en
                  fracción por venir de una persona, y pintarlo en verde como
                  «la única verdad que no generamos nosotros» es peor que no
                  enseñarlo: le da el respaldo de la tarifa a algo que la
                  tarifa no respalda. */}
              {detalle.dictamen.en_catalogo === false && (
                <p className="dictamen__fuera-de-catalogo">
                  <strong>Esta fracción no está en la TIGIE vigente ese día.</strong>{' '}
                  El veredicto se conserva tal como lo dejó la persona —no lo
                  corregimos nosotros, porque elegir la fracción es justo lo que
                  no nos toca— pero no se puede declarar hasta que quien lo
                  firmó la confirme.
                </p>
              )}

              <p className="dictamen__pie">
                Se conservan las dos respuestas —la del motor y la de la
                persona— a propósito: es lo único que permite medir en qué
                porcentaje coinciden.
              </p>
            </div>
          )}

          {detalle.requires_human_review && !detalle.dictamen && (
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
                      <span
                        className={`paso__estado paso__estado--${(paso.status ?? '').toLowerCase()}`}
                        title={QUE_ES_EL_ESTADO[paso.status ?? ''] ?? ''}
                      >
                        {paso.status}
                      </span>
                      {ultimo && <span className="ruta__marca">resolvió</span>}
                    </div>

                    {/* Qué PREGUNTA esta regla. Sin esto, «RGI-3a» no le dice
                        nada a quien no clasifica a diario, y la traza entera
                        se lee como jerga en vez de como un razonamiento. */}
                    {QUE_PREGUNTA[paso.rule_id ?? ''] && (
                      <p className="paso__glosa">{QUE_PREGUNTA[paso.rule_id ?? '']}</p>
                    )}

                    {QUE_ES_EL_ESTADO[paso.status ?? ''] && (
                      <p className="paso__glosa paso__glosa--estado">
                        {QUE_ES_EL_ESTADO[paso.status ?? '']}
                      </p>
                    )}

                    {paso.reasoning_summary && (
                      <p className="paso__razon">{paso.reasoning_summary}</p>
                    )}

                    {/* La confianza, con su lectura. Un 0.45 a secas se
                        entiende como «45 % de probabilidad de acertar», que es
                        lo contrario de lo que significa. */}
                    {paso.confidence != null && (
                      <p className="paso__confianza">
                        <span className="paso__confianza-valor">
                          Confianza {Number(paso.confidence).toFixed(2)}
                        </span>
                        <span>{comoLeerLaConfianza(paso.confidence, paso.rule_id)}</span>
                      </p>
                    )}

                    {paso.candidate_codes && paso.candidate_codes.length > 0 && (
                      <p className="paso__candidatos">
                        Consideró {paso.candidate_codes.length}
                        {paso.candidate_codes.length === 1 ? ' posición' : ' posiciones'} de la
                        tarifa:{' '}
                        {paso.candidate_codes.map((c) => (
                          <code key={c}>{c}</code>
                        ))}
                      </p>
                    )}

                    {/* La pregunta concreta. Es lo que convierte «requiere
                        revisión» en algo que se contesta en cinco segundos — y
                        cuya respuesta sirve para todos los casos iguales. */}
                    {paso.preguntas && paso.preguntas.length > 0 && (
                      <div className="pregunta-desempate">
                        <strong>Para desatascarlo basta con responder esto:</strong>
                        <ul>
                          {paso.preguntas.map((q) => (
                            <li key={`${q.codigo}-${q.atributo}`}>
                              <p className="pregunta-desempate__texto">{q.texto}</p>
                              <p className="pregunta-desempate__caras">
                                <span>
                                  la ficha dice <code>{q.atributo}</code> ={' '}
                                  <strong>{q.valor_declarado}</strong>
                                </span>
                                <span>
                                  la <code>{q.codigo}</code> exige{' '}
                                  <strong>{q.exige}</strong>
                                </span>
                              </p>
                            </li>
                          ))}
                        </ul>
                        <p className="pregunta-desempate__pie">
                          La respuesta se guarda firmada y no se vuelve a
                          preguntar: resuelve este caso y todos los iguales.
                        </p>
                      </div>
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
