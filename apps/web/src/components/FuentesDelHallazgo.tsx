/**
 * De qué filas sale un hallazgo (§21): documento, vigencia y huella.
 *
 * Es lo que hay que poder enseñar para defender un hallazgo ante la autoridad:
 * no «la fracción está mal», sino «contra este texto de la LIGIE, publicado
 * tal día, con esta huella». Un dictamen o una ficha no son norma, y la
 * etiqueta lo dice.
 */

import type { Fuente } from './fuente'

const NO_ES_NORMA: Record<string, string> = {
  HUMAN_VALIDATED: 'criterio firmado',
  SYNTHETIC: 'dato sintético',
}

export function FuentesDelHallazgo({ fuentes }: { fuentes: Fuente[] }) {
  if (fuentes.length === 0) return null
  return (
    <ul className="fuentes" aria-label="Fuentes del hallazgo">
      {fuentes.map((f) => (
        <li key={`${f.table}|${f.row_id ?? f.what}`}>
          <span className="fuentes__que">{f.what}</span>
          {f.document && (
            <>
              {' · '}
              {f.url ? (
                <a href={f.url} target="_blank" rel="noreferrer">
                  {f.document}
                </a>
              ) : (
                f.document
              )}
            </>
          )}
          {f.valid_from && <span className="fuentes__nota"> · vigente desde {f.valid_from}</span>}
          {f.content_hash && (
            <span className="fuentes__nota" title={f.content_hash}>
              {' · '}huella {f.content_hash.replace(/^sha256:/, '').slice(0, 10)}
            </span>
          )}
          {f.data_origin && NO_ES_NORMA[f.data_origin] && (
            <span className="fuentes__nota"> · {NO_ES_NORMA[f.data_origin]}</span>
          )}
        </li>
      ))}
    </ul>
  )
}
