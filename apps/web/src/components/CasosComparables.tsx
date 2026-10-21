/**
 * Lo que decidió otra aduana para la misma subpartida (ADR 0019).
 *
 * Va DESPUÉS de «En qué se sostiene» y separado de él a propósito: un caso de
 * CBP no fundamenta una fracción mexicana. El aviso viene de la API y se
 * enseña siempre, y el extracto es texto literal de la resolución.
 */

import type { ComparablesRead } from '../api/client'

const DE_DONDE: Record<string, string> = {
  justificacion: 'justificación de la clasificación (idioma del país emisor)',
  subpartida: 'frase en que fija la subpartida',
  holding: 'resolutivo (HOLDING)',
  hechos: 'hechos (FACTS)',
  inicio: 'inicio del texto',
}

export function CasosComparables({ datos }: { datos: ComparablesRead | null }) {
  if (!datos || !datos.hs6) return null

  const hs6 = `${datos.hs6.slice(0, 4)}.${datos.hs6.slice(4)}`
  return (
    <section className="comparables" aria-labelledby="comparables-titulo">
      <h2 className="seccion" id="comparables-titulo">
        Casos comparables · subpartida {hs6}
      </h2>
      <p className="comparables__aviso" role="note">
        {datos.aviso}
      </p>
      <p className="comparable__meta">
        {datos.orden === 'parecido'
          ? 'Ordenadas por parecido con la ficha del producto (vigentes primero).'
          : `Ordenadas por fecha${datos.motivo_orden ? `: ${datos.motivo_orden}` : ''}.`}
      </p>

      {datos.comparables.length === 0 ? (
        <p className="sin-dato">Ninguna resolución cargada cita esta subpartida.</p>
      ) : (
        <>
          <ul className="comparables__lista">
            {datos.comparables.map((c) => (
              <li
                key={`${c.authority}-${c.ruling_number}`}
                className={c.is_revoked ? 'comparable comparable--revocada' : 'comparable'}
              >
                <p className="comparable__cabecera">
                  <a href={c.url} target="_blank" rel="noreferrer">
                    {c.authority} {c.ruling_number}
                  </a>{' '}
                  · {c.ruling_date} · <code>{c.tariff_codes.join(', ')}</code>
                  {c.is_revoked && (
                    <strong className="comparable__revocada">
                      {' '}
                      · Revocada{c.revoked_by.length > 0 && ` por ${c.revoked_by.join(', ')}`}
                    </strong>
                  )}
                </p>
                <p className="comparable__asunto">{c.subject}</p>
                <blockquote className="comparable__extracto" lang="en">
                  {c.extracto}
                </blockquote>
                <p className="comparable__meta">
                  Texto literal: {DE_DONDE[c.extracto_de] ?? c.extracto_de} · {c.data_origin}
                </p>
              </li>
            ))}
          </ul>
          {datos.total > datos.comparables.length && (
            <p className="sin-dato">
              {datos.total - datos.comparables.length} resoluciones más citan esta subpartida.
            </p>
          )}
        </>
      )}
    </section>
  )
}
