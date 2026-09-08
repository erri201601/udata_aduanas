/**
 * Hallazgos del Pedimento Espejo (§9.3, §9.4 y §36).
 *
 * LA DISTINCIÓN QUE ESTA PANTALLA NO PUEDE PERDER
 *
 * «Sin hallazgos» y «no pude revisarlo» son cosas distintas. Un pedimento que
 * nadie verificó no está limpio: está sin verificar. Si esta pantalla los
 * mezclara, alguien presentaría ante la autoridad un pedimento sin revisar
 * creyendo que pasó el filtro — y ese error se descubre en la aduana.
 *
 * Por eso, mientras `coverage_known` sea falso, aquí NUNCA aparece la palabra
 * «limpio». Lo más que se dice es «sin hallazgos en lo revisado».
 *
 * LA SEGUNDA: un hallazgo sin impacto económico NO es menos grave. Una NOM
 * faltante no cambia lo que se paga y aun así detiene la mercancía. El monto
 * decide si se puede PRESENTAR a un cliente, no cuánto importa.
 */

import { useState } from 'react'

import { SyntheticBanner } from '../components/DataOriginBadge'
import {
  SEVERIDADES,
  esAccionable,
  formatearMonto,
} from '../components/severity'
import { usePedimentoFindings, usePedimentos } from '../hooks/useFindings'
import type { Severity } from '../api/client'

function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERIDADES[severity] ?? { etiqueta: severity, ayuda: '' }

  return (
    <span className={`sev sev--${severity.toLowerCase()}`} title={s.ayuda}>
      {s.etiqueta}
    </span>
  )
}

export function Findings() {
  const { pedimentos, error: errorLista, cargando: cargandoLista } = usePedimentos()
  const [elegido, setElegido] = useState<string | null>(null)
  const activo = elegido ?? pedimentos[0]?.id ?? null
  const { revision, error, cargando } = usePedimentoFindings(activo)

  const hallazgos = revision?.findings ?? []
  const accionables = hallazgos.filter((h) => esAccionable(h.impact_amount))

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Hallazgos</h1>
          <p className="pantalla__sub">
            Diferencias entre lo declarado y el pedimento espejo
          </p>
        </div>
      </header>

      <SyntheticBanner />

      {(errorLista || error) && (
        <div className="alerta" role="alert">
          <strong>No se pudieron cargar los hallazgos.</strong>
          <p>{errorLista ?? error}</p>
        </div>
      )}

      {pedimentos.length > 1 && (
        <label className="selector">
          <span>Pedimento</span>
          <select value={activo ?? ''} onChange={(e) => setElegido(e.target.value)}>
            {pedimentos.map((p) => (
              <option key={p.id} value={p.id}>
                {p.pedimento_number} — {p.operation_date}
              </option>
            ))}
          </select>
        </label>
      )}

      {revision && (
        <>
          {/* Lo primero que se lee: qué se sabe y qué no.

              Tres estados, no dos. Un pedimento que nadie miró, uno revisado
              a medias y uno revisado entero son cosas distintas, y sólo del
              tercero se puede decir que está limpio. */}
          {!revision.coverage_known ? (
            <div className="cobertura cobertura--incierta" role="note">
              <strong>Este pedimento no se ha auditado.</strong>
              <p>
                No hay ninguna revisión registrada, así que{' '}
                <em>ausencia de hallazgos no significa que esté limpio</em>:
                significa que nadie lo ha mirado.
              </p>
            </div>
          ) : revision.is_complete ? (
            <div className="cobertura" role="note">
              <strong>Revisión completa.</strong>
              <p>
                Se comprobaron todas las partidas
                {revision.reviewed_at &&
                  ` · ${new Date(revision.reviewed_at).toLocaleString('es-MX')}`}
                . Esto sí autoriza a decir que el pedimento está limpio si no
                hay hallazgos.
              </p>
            </div>
          ) : (
            <div className="cobertura cobertura--parcial" role="note">
              <strong>
                Revisión incompleta: {revision.unverifiable.length}{' '}
                {revision.unverifiable.length === 1
                  ? 'partida no se pudo comprobar'
                  : 'partidas no se pudieron comprobar'}
                .
              </strong>
              <p>
                Lo que aparece abajo es lo encontrado{' '}
                <em>en lo que sí se revisó</em>. Las partidas de esta lista
                quedaron fuera:
              </p>
              <ul className="cobertura__pendientes">
                {revision.unverifiable.map((razon) => (
                  <li key={razon}>{razon}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="resumen-hallazgos">
            <div className="cifra">
              <span className="cifra__valor">{hallazgos.length}</span>
              <span className="cifra__k">
                {hallazgos.length === 1 ? 'hallazgo' : 'hallazgos'} en lo revisado
              </span>
            </div>
            <div className="cifra">
              <span className="cifra__valor">
                {revision.worst_severity
                  ? SEVERIDADES[revision.worst_severity as Severity]?.etiqueta
                  : '—'}
              </span>
              <span className="cifra__k">peor severidad</span>
            </div>
            <div className="cifra">
              <span className="cifra__valor">{accionables.length}</span>
              <span className="cifra__k">
                presentables a cliente
                <em title="Los demás se pueden investigar, pero no presentar: sin monto cuantificado no hay conversación con el cliente. No son menos graves.">
                  ?
                </em>
              </span>
            </div>
          </div>

          {hallazgos.length === 0 ? (
            <p className="vacio">
              {revision.coverage_known && revision.is_complete
                ? 'Revisión completa sin hallazgos: el pedimento está limpio.'
                : 'Sin hallazgos en lo revisado. No equivale a un pedimento limpio.'}
            </p>
          ) : (
            <ul className="hallazgos">
              {hallazgos.map((h) => {
                const monto = formatearMonto(h.impact_amount, h.impact_amount_currency)
                const accionable = esAccionable(h.impact_amount)

                return (
                  <li
                    key={h.id}
                    className={`hallazgo hallazgo--${(h.severity || 'info').toLowerCase()}`}
                  >
                    <div className="hallazgo__cabecera">
                      <SeverityBadge severity={h.severity as Severity} />
                      <code className="hallazgo__tipo">{h.finding_type}</code>
                      {h.is_simulation && <span className="sim">simulación</span>}
                    </div>

                    {(h.declared_value || h.expected_value) && (
                      <p className="hallazgo__contraste">
                        <span className="declarado">{h.declared_value ?? '—'}</span>
                        <span aria-hidden="true"> → </span>
                        <span className="esperado">{h.expected_value ?? '—'}</span>
                      </p>
                    )}

                    {h.rationale && <p className="hallazgo__razon">{h.rationale}</p>}

                    <p className="hallazgo__impacto">
                      {accionable ? (
                        <strong>{monto}</strong>
                      ) : (
                        <span className="sin-monto">
                          Sin impacto económico cuantificado — se puede
                          investigar, no presentar. No lo hace menos grave.
                        </span>
                      )}
                    </p>
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}

      {!revision && !error && (cargando || cargandoLista) && (
        <p className="vacio">Cargando la revisión…</p>
      )}

      {!revision && !cargando && !cargandoLista && !error && !errorLista && (
        <p className="vacio">No hay pedimentos revisados todavía.</p>
      )}
    </section>
  )
}

