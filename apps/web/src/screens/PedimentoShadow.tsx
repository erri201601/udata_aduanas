/**
 * Pedimento Shadow (§32, §36) — lo declarado al lado de lo esperado.
 *
 * LA CONFUSIÓN QUE ESTA PANTALLA EXISTE PARA IMPEDIR
 *
 * «Cero hallazgos» y «no pude revisarlo» se ven igual en cualquier tabla que
 * no los separe, y la diferencia es enorme: alguien puede presentar ante la
 * autoridad un pedimento sin revisar creyendo que pasó el filtro.
 *
 * Por eso cada partida sale con un estado explícito —CONFORME, DIVERGENTE o
 * SIN VERIFICAR— y nunca por descarte. Una partida sin hallazgos sólo se
 * llama conforme si consta que se comprobó. Cuando no consta, la pantalla lo
 * dice con todas sus letras arriba del todo, antes de la tabla.
 *
 * Y hay un cuarto caso que tampoco se colapsa: la partida donde SÍ se
 * comprobó la fracción pero NO se supo qué NOM exige. Tiene hallazgo y tiene
 * hueco a la vez, y se marca como verificación parcial en vez de elegir uno.
 */

import { useEffect, useState } from 'react'

import { fetchEspejo, fetchPedimentos } from '../api/client'
import type { LineaEspejo, PedimentoEspejo, PedimentoRead } from '../api/client'
import { detalleDe, etiquetaDe } from '../components/divergencias'
import { SyntheticBanner } from '../components/DataOriginBadge'
import { SEVERIDADES, formatearMonto } from '../components/severity'
import type { Severity } from '../api/client'

const ESTADOS: Record<string, { etiqueta: string; ayuda: string }> = {
  CONFORME: {
    etiqueta: 'Conforme',
    ayuda: 'Se comprobó y coincide con lo esperado.',
  },
  DIVERGENTE: {
    etiqueta: 'Divergente',
    ayuda: 'Lo declarado no coincide con lo que el espejo esperaba.',
  },
  PARCIAL: {
    etiqueta: 'Parcial',
    ayuda: 'Parte se comprobó y pasó; otra parte no se pudo comprobar.',
  },
  SIN_VERIFICAR: {
    etiqueta: 'Sin verificar',
    ayuda: 'No se pudo comprobar NADA de esta partida.',
  },
}

function Estado({ estado }: { estado: string }) {
  const info = ESTADOS[estado]
  return (
    <span className={`estado-espejo estado-espejo--${estado.toLowerCase()}`} title={info?.ayuda}>
      {info?.etiqueta ?? estado}
    </span>
  )
}

/** Lo declarado y lo esperado, uno al lado del otro. */
function Comparacion({ linea }: { linea: LineaEspejo }) {
  return (
    <div className="espejo__caras">
      <div className="cara cara--declarada">
        <h4>Declarado</h4>
        <dl>
          <div>
            <dt>Fracción</dt>
            <dd>
              <code>{linea.declared_fraction_code ?? '—'}</code>
            </dd>
          </div>
          <div>
            <dt>NICO</dt>
            <dd>
              <code>{linea.declared_nico_code ?? '—'}</code>
            </dd>
          </div>
          <div>
            <dt>Origen</dt>
            <dd>{linea.country_of_origin ?? '—'}</dd>
          </div>
          <div>
            <dt>Valor en aduana</dt>
            <dd>
              {formatearMonto(linea.customs_value, linea.customs_value_currency) ?? '—'}
            </dd>
          </div>
        </dl>
      </div>

      <div className="cara cara--esperada">
        <h4>Esperado por el espejo</h4>
        {linea.expected_fraction_code ? (
          <dl>
            <div>
              <dt>Fracción</dt>
              <dd>
                <code className="cara__divergente">{linea.expected_fraction_code}</code>
              </dd>
            </div>
          </dl>
        ) : (
          <p className="cara__sin-expectativa">
            {linea.estado === 'CONFORME'
              ? 'La expectativa coincidió con lo declarado y no dejó rastro. Repetir aquí la fracción declarada fabricaría una confirmación que el motor nunca emitió.'
              : 'No se construyó una expectativa que se pudiera sostener, así que no hay nada que contrastar.'}
          </p>
        )}
      </div>
    </div>
  )
}

/** Lo que SÍ se comprobó, con su denominador.
 *
 * El bloque de al lado dice lo que no se pudo comprobar y lleva meses
 * diciéndolo solo. Sin esta mitad, una partida con nueve comprobaciones
 * buenas y una imposible se leía igual que una donde no se comprobó nada, y
 * el sistema parecía no verificar nada cuando verificaba casi todo.
 *
 * El denominador llega de la API (`comprobaciones_posibles`) y no se escribe
 * aquí: con un 10 a mano, añadir una comprobación al motor dejaría la consola
 * diciendo «10 de 10» sobre una partida a la que le falta una.
 *
 * Enumerarlas NO afloja el §36. Una partida no está limpia por tener nueve
 * comprobaciones buenas si le falta la décima — por eso las que faltan se
 * nombran aquí mismo, y no sólo se restan.
 */
function Comprobado({ hechas, posibles }: { hechas: string[]; posibles: string[] }) {
  if (hechas.length === 0) return null
  const faltan = posibles.filter((c) => !hechas.includes(c))
  return (
    <div className="espejo-linea__bloque espejo-linea__bloque--comprobado">
      <h5>
        Lo que sí se comprobó{' '}
        {posibles.length > 0 && (
          <span className="comprobado__cuenta">
            {hechas.length} de {posibles.length}
          </span>
        )}
      </h5>
      <ul className="comprobaciones">
        {hechas.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      {faltan.length > 0 && (
        <p className="comprobado__faltan">
          No se comprobó: {faltan.join(', ')}. El motivo está abajo.
        </p>
      )}
    </div>
  )
}

/** ¿Es de los tipos cuyo monto es un error de cálculo de una contribución? */
function esDeCalculo(tipo: string): boolean {
  return tipo === 'IGI_RATE_MISMATCH' || tipo === 'VAT_MISMATCH'
}

type Divergencia = LineaEspejo['divergencias'][number]

const claveDe = (d: Divergencia) => `${d.finding_type}|${d.declared_value}|${d.expected_value}`

/** Lo que difiere IGUAL en todas las partidas y no tiene monto: es del documento.
 *
 * El tipo de cambio se declara una vez por pedimento. Cuando está mal, salía
 * como CRÍTICO doce veces, una por partida, con el mismo texto — y en la demo
 * escondía lo que sí distingue a cada partida. Se enseña una vez arriba y cada
 * partida lo remite. Sólo lo que no tiene monto: con monto, cada partida es
 * una cifra distinta y juntarlas cambiaría lo que se presenta. */
function delDocumento(lineas: LineaEspejo[]): Divergencia[] {
  if (lineas.length < 2) return []
  const [primera, ...resto] = lineas
  return primera.divergencias.filter(
    (d) =>
      !d.impact_amount &&
      resto.every((l) => l.divergencias.some((x) => !x.impact_amount && claveDe(x) === claveDe(d))),
  )
}

function Partida({
  linea,
  posibles,
  delPedimento,
}: {
  linea: LineaEspejo
  posibles: string[]
  delPedimento: Set<string>
}) {
  const propias = linea.divergencias.filter((d) => !delPedimento.has(claveDe(d)))
  const remitidas = linea.divergencias.length - propias.length
  return (
    <li className={`espejo-linea espejo-linea--${linea.estado.toLowerCase()}`}>
      <header className="espejo-linea__cabecera">
        <div>
          <span className="espejo-linea__numero">Partida {linea.line_number}</span>
          <span className="espejo-linea__desc">{linea.description}</span>
        </div>
        <div className="espejo-linea__marcas">
          <Estado estado={linea.estado} />
          {linea.verificacion_parcial && (
            <span
              className="estado-espejo estado-espejo--parcial"
              title="Parte se comprobó y parte no. Presentarla como revisada sería exacto en un campo y falso en el conjunto."
            >
              Verificación parcial
            </span>
          )}
        </div>
      </header>

      <Comparacion linea={linea} />

      {remitidas > 0 && (
        <p className="espejo-linea__remite">
          Y lo que difiere en todo el pedimento, arriba.
        </p>
      )}

      {propias.length > 0 && (
        <div className="espejo-linea__bloque">
          <h5>Lo que difiere</h5>
          <ul className="divergencias">
            {propias.map((d) => {
              const monto = formatearMonto(d.impact_amount, d.impact_amount_currency)
              return (
                <li key={d.finding_id}>
                  <div className="divergencia__titulo">
                    <span className={`sev sev--${d.severity.toLowerCase()}`}>
                      {SEVERIDADES[d.severity as Severity]?.etiqueta ?? d.severity}
                    </span>
                    <span className="divergencia__tipo" title={detalleDe(d.finding_type)}>
                      {etiquetaDe(d.finding_type)}
                    </span>
                    {d.field && <span className="divergencia__campo">{d.field}</span>}
                  </div>
                  <p className="divergencia__valores">
                    <span>
                      declarado <code>{d.declared_value ?? '—'}</code>
                    </span>
                    <span aria-hidden="true">→</span>
                    <span>
                      esperado <code>{d.expected_value ?? '—'}</code>
                    </span>
                  </p>
                  {d.rationale && <p className="divergencia__razon">{d.rationale}</p>}
                  <p className="divergencia__monto">
                    {monto ? (
                      /* El mismo importe mide dos cosas distintas y presentarlas
                         con la misma etiqueta haría que una cifra condicionada
                         se leyera como una deuda cierta. */
                      d.impact_scope === 'UNA_CONTRIBUCION' ? (
                        <>
                          <strong>Falta de esta contribución: {monto}</strong> — exacto, y no
                          depende de clasificar: es lo que la ley da para la fracción que se
                          declaró, menos lo que se escribió.
                        </>
                      ) : (
                        <>
                          Se movería {monto} si esto se corrigiera. Depende de la fracción
                          esperada —del motor o de un dictamen—, así que no es una deuda
                          cierta todavía.
                        </>
                      )
                    ) : esDeCalculo(d.finding_type) ? (
                      /* Y aquí la razón importa: no es que no se pudiera
                         calcular, es que la base del cálculo está en duda. */
                      <em>
                        Sin monto porque la base está en duda: este importe se mediría
                        contra la tasa y el valor que el sistema cuestiona en esta misma
                        partida. Ponerle precio prometería una cifra que no se sostiene.
                      </em>
                    ) : (
                      <em>
                        Sin monto. Se puede investigar, no presentar — y no por eso es menos
                        grave.
                      </em>
                    )}
                  </p>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <Comprobado hechas={linea.comprobado ?? []} posibles={posibles} />

      {linea.no_verificable_por.length > 0 && (
        <div className="espejo-linea__bloque espejo-linea__bloque--hueco">
          <h5>Lo que no se pudo comprobar</h5>
          <ul className="huecos">
            {linea.no_verificable_por.map((motivo) => (
              <li key={motivo}>{motivo}</li>
            ))}
          </ul>
        </div>
      )}
    </li>
  )
}

export function PedimentoShadow() {
  const [pedimentos, setPedimentos] = useState<PedimentoRead[]>([])
  const [elegido, setElegido] = useState<string | null>(null)
  const [datos, setDatos] = useState<PedimentoEspejo | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const control = new AbortController()
    fetchPedimentos(control.signal)
      .then((lista) => {
        setPedimentos(lista)
        setElegido((actual) => actual ?? lista[0]?.id ?? null)
      })
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setError(causa instanceof Error ? causa.message : 'No se pudo contactar la API')
      })
    return () => control.abort()
  }, [])

  useEffect(() => {
    if (!elegido) return
    const control = new AbortController()
    fetchEspejo(elegido, control.signal)
      .then((d) => {
        setDatos(d)
        setError(null)
      })
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setError(causa instanceof Error ? causa.message : 'No se pudo cargar el espejo')
      })
    return () => control.abort()
  }, [elegido])

  /* «Ninguna se pudo comprobar» es que NINGUNA produjo veredicto, no que
     ninguna saliera conforme. Una partida DIVERGENTE sí se comprobó: se
     comprobó y no cuadró. Mientras la condición fue `conformes === 0`, el
     cartel rojo salía sobre un pedimento con 5 divergentes y 8 hallazgos con
     importe al peso, diciendo que el sistema «no pudo afirmar nada» encima de
     la pantalla donde acababa de afirmar ocho cosas. Se contradecía sola.

     Es la sexta vez en este proyecto que se colapsan dos estados distintos en
     una sola condición. Aquí los dos merecen decirse, y dicen cosas opuestas:
     no haber podido comprobar nada, y haberlo comprobado sin encontrar una
     sola partida correcta. */
  /* PARCIAL entró en la API y aquí no se sumaba a nada. Con doce partidas
     parciales —cada una con nueve de diez comprobaciones hechas— esta cuenta
     daba cero y el cartel rojo volvía a salir diciendo que el sistema no pudo
     afirmar nada. Séptima vez. */
  const comprobadas = datos != null ? datos.divergentes + datos.conformes + datos.parciales : 0
  const nadaComprobado = datos != null && datos.partidas > 0 && comprobadas === 0

  /* Y «ninguna conforme» tampoco es un solo estado. Si todas las comprobadas
     divergieron, es un resultado sobre el pedimento. Si lo comprobado pasó y
     lo que falta es comprobación, no falló nada: lo que no hay es ninguna
     partida cerrada. Decir «ninguna coincidió con lo esperado» sobre la
     segunda sería falso — en una partida parcial, lo que se comparó coincidió;
     si no, sería divergente. */
  const todoDivergente = datos != null && datos.divergentes > 0 && datos.divergentes === comprobadas
  const ningunaCerrada =
    datos != null && comprobadas > 0 && datos.conformes === 0 && datos.divergentes === 0

  /* La cifra que contesta «¿esto verifica algo?» con un número y no con una
     etiqueta. Se cuenta sobre las partidas, no sobre el pedimento: el espejo
     comprueba diez cosas DE CADA partida. */
  const hechasTotales =
    datos?.lineas.reduce((suma, l) => suma + (l.comprobado?.length ?? 0), 0) ?? 0
  const posiblesTotales =
    (datos?.comprobaciones_posibles?.length ?? 0) * (datos?.partidas ?? 0)

  const documento = datos?.revision ? delDocumento(datos.lineas) : []

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Pedimento Shadow</h1>
          <p className="pantalla__sub">
            El pedimento que se declaró, frente al que el sistema esperaba
          </p>
        </div>
        {pedimentos.length > 0 && (
          <label className="selector">
            <span>Pedimento</span>
            <select value={elegido ?? ''} onChange={(e) => setElegido(e.target.value)}>
              {pedimentos.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.pedimento_number}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      {datos?.is_simulation && <SyntheticBanner />}

      {error && (
        <div className="alerta" role="alert">
          <strong>No se pudo cargar el espejo.</strong>
          <p>{error}</p>
        </div>
      )}

      {datos && datos.revision === null && (
        <div className="alerta" role="note">
          <strong>Este pedimento nunca se ha auditado.</strong>
          <p>
            No hay corrida del espejo, así que no consta qué se revisó. No está limpio: está
            sin tocar. Para auditarlo hay que lanzar <code>POST /pedimentos/{'{id}'}/review</code>.
          </p>
        </div>
      )}

      {datos && datos.revision && (
        <>
          {nadaComprobado && (
            <div className="alerta alerta--fuerte" role="note">
              <strong>
                Ninguna partida de este pedimento se pudo comprobar. No está limpio: está sin
                verificar.
              </strong>
              <p>
                Cero hallazgos aquí no significa que todo esté bien — significa que el sistema
                no pudo afirmar nada. Abajo está el motivo de cada partida.
              </p>
            </div>
          )}

          {/* El otro estado, que NO es el anterior y antes se pintaba igual:
              sí se comprobaron partidas, y ninguna resultó correcta. Eso no es
              un hueco del sistema; es un resultado sobre el pedimento, y se
              dice con otro tono porque significa lo contrario. */}
          {todoDivergente && (
            <div className="alerta" role="note">
              <strong>
                De las {comprobadas} partidas que se pudieron comprobar, ninguna coincidió con
                lo esperado.
              </strong>
              <p>
                Las otras {datos.sin_verificar} no se pudieron comprobar, y no cuentan ni a
                favor ni en contra. Cero conformes aquí es un resultado sobre el pedimento, no
                una limitación del sistema.
              </p>
            </div>
          )}

          {/* El tercer estado: lo comprobado pasó y a ninguna partida le dio
              para cerrarse. No es una mala noticia sobre el pedimento ni un
              fallo del sistema — es una lista de lo que falta cargar. */}
          {ningunaCerrada && (
            <div className="alerta" role="note">
              <strong>
                Nada de lo que se comprobó falló, y ninguna partida quedó cerrada del todo.
              </strong>
              <p>
                A las {datos.parciales} partidas parciales les falta alguna de las{' '}
                {datos.comprobaciones_posibles?.length ?? 0} comprobaciones. Cada una dice
                abajo cuáles hizo y cuáles no: lo que falta es dato cargado, no un hallazgo.
              </p>
            </div>
          )}

          <div className="tablero">
            <div className="tablero__cifra">
              <span className="tablero__valor">{datos.partidas}</span>
              <span className="tablero__etiqueta">partidas</span>
            </div>
            <div
              className={`tablero__cifra tablero__cifra--${datos.divergentes > 0 ? 'atencion' : 'normal'}`}
            >
              <span className="tablero__valor">{datos.divergentes}</span>
              <span className="tablero__etiqueta">divergentes</span>
            </div>
            {/* `parciales` no tenía cifra, así que los totales no sumaban
                `partidas` y nadie podía ver dónde se habían ido las que
                faltaban. */}
            <div
              className={`tablero__cifra tablero__cifra--${datos.parciales > 0 ? 'atencion' : 'normal'}`}
            >
              <span className="tablero__valor">{datos.parciales}</span>
              <span className="tablero__etiqueta">parciales</span>
              <span className="tablero__nota">Comprobadas a medias, sin fallo.</span>
            </div>
            <div
              className={`tablero__cifra tablero__cifra--${datos.sin_verificar > 0 ? 'atencion' : 'normal'}`}
            >
              <span className="tablero__valor">{datos.sin_verificar}</span>
              <span className="tablero__etiqueta">sin verificar</span>
              <span className="tablero__nota">Nada comprobado. No es limpia.</span>
            </div>
            <div className="tablero__cifra tablero__cifra--bien">
              <span className="tablero__valor">{datos.conformes}</span>
              <span className="tablero__etiqueta">conformes</span>
              <span className="tablero__nota">Comprobadas y coincidentes.</span>
            </div>
            <div className="tablero__cifra">
              <span className="tablero__valor">
                {hechasTotales} de {posiblesTotales}
              </span>
              <span className="tablero__etiqueta">comprobaciones</span>
              <span className="tablero__nota">
                De las {datos.comprobaciones_posibles?.length ?? 0} que el espejo sabe hacer,
                por cada partida.
              </span>
            </div>
            <div className="tablero__cifra">
              <span className="tablero__valor">
                {datos.monedas_mezcladas
                  ? '—'
                  : (formatearMonto(datos.exposicion_cuantificada, datos.exposicion_moneda) ??
                    '—')}
              </span>
              <span className="tablero__etiqueta">exposición cuantificada</span>
              <span className="tablero__nota">
                {datos.monedas_mezcladas
                  ? 'Hay montos en varias monedas: no se suman.'
                  : datos.sobrepagos > 0
                    ? `Sólo lo que se debe. ${datos.sobrepagos} de más queda fuera: está en Oportunidad.`
                    : 'Sólo lo que tiene monto. Lo demás no se estima.'}
              </span>
            </div>
          </div>

          <p className="espejo__revision">
            Revisión <code>{datos.revision.review_id.slice(0, 8)}</code> del{' '}
            {new Date(datos.revision.reviewed_at).toLocaleDateString('es-MX')}
            {datos.revisiones_totales > 1 && (
              <> · es la más reciente de {datos.revisiones_totales} corridas</>
            )}
            {datos.revision.engine_version && <> · motor {datos.revision.engine_version}</>}
            {!datos.revision.is_complete && (
              <> · <strong>la auditoría quedó incompleta</strong></>
            )}
          </p>

          {documento.length > 0 && (
            <div className="espejo-documento" role="note">
              <h5>Del pedimento entero</h5>
              <p className="espejo-documento__pie">
                Igual en las {datos.lineas.length} partidas: es un dato del documento, no de
                cada mercancía.
              </p>
              <ul className="divergencias">
                {documento.map((d) => (
                  <li key={claveDe(d)}>
                    <div className="divergencia__titulo">
                      <span className={`sev sev--${d.severity.toLowerCase()}`}>
                        {SEVERIDADES[d.severity as Severity]?.etiqueta ?? d.severity}
                      </span>
                      <span className="divergencia__tipo" title={detalleDe(d.finding_type)}>
                        {etiquetaDe(d.finding_type)}
                      </span>
                      {d.field && <span className="divergencia__campo">{d.field}</span>}
                    </div>
                    <p className="divergencia__valores">
                      <span>
                        declarado <code>{d.declared_value ?? '—'}</code>
                      </span>
                      <span aria-hidden="true">→</span>
                      <span>
                        esperado <code>{d.expected_value ?? '—'}</code>
                      </span>
                    </p>
                    {d.rationale && <p className="divergencia__razon">{d.rationale}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <ul className="espejo-lineas">
            {datos.lineas.map((linea) => (
              <Partida
                key={linea.line_number}
                linea={linea}
                posibles={datos.comprobaciones_posibles ?? []}
                delPedimento={new Set(documento.map(claveDe))}
              />
            ))}
          </ul>

          {datos.motivos_sin_atribuir.length > 0 && (
            <div className="alerta" role="note">
              <strong>Hay motivos que no se pudieron colgar de una partida.</strong>
              <p>
                El motor cambió el formato con el que los escribe. Se muestran aquí en vez de
                perderlos:
              </p>
              <ul>
                {datos.motivos_sin_atribuir.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          )}

          <p className="tablero__pie">
            Esta pantalla lee la última auditoría; no dispara una nueva. Abrirla no gasta
            llamadas a modelo ni escribe filas — auditar es un acto deliberado, no un efecto
            de mirar.
          </p>
        </>
      )}

      {!datos && !error && <p className="vacio">Cargando el espejo…</p>}
    </section>
  )
}
