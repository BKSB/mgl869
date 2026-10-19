import { useElementSize } from '../hooks/useElementSize'

interface Props {
  values: number[]
}

/** Marge interne (px) : marqueur r 4 + anneau 2 px (centre sur le bord du
 * cercle) entierement dans la boite, sans rognage. */
const PAD = 5

/** Tendance 12 points dessinee en espace pixel : la boite (.spark) prend la
 * taille que lui donne le CSS (largeur souple dans la tile, 28 px de haut ;
 * 24 px sous 720 px) et le trace s'y adapte sans mise a l'echelle. Trait
 * de-emphase 1,5 px, dernier segment et marqueur 8 px dans l'accent avec un
 * anneau surface 2 px, quelle que soit la largeur. Aucune animation. */
export function Sparkline({ values }: Props) {
  const [ref, { width, height }] = useElementSize<HTMLSpanElement>()
  const n = values.length
  if (n < 2) return null
  const w = Math.round(width)
  const h = Math.round(height)
  let svg = null
  if (w > 2 * PAD && h > 2 * PAD) {
    let min = Infinity
    let max = -Infinity
    for (const v of values) {
      if (v < min) min = v
      if (v > max) max = v
    }
    const span = max - min || 1
    // A gauche, seul le trait (1,5 px) doit tenir ; a droite, le marqueur
    const x0 = 2
    const xs = w - PAD - x0
    const ys = h - 2 * PAD
    const pts = values.map((v, i) => [x0 + (i / (n - 1)) * xs, h - PAD - ((v - min) / span) * ys] as const)
    const body = pts.slice(0, n - 1).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    const [px, py] = pts[n - 2]
    const [lx, ly] = pts[n - 1]
    svg = (
      <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true" focusable="false">
        <polyline points={body} fill="none" stroke="var(--spark)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
        <line x1={px} y1={py} x2={lx} y2={ly} stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx={lx} cy={ly} r="4" fill="var(--accent)" stroke="var(--surface-1)" strokeWidth="2" />
      </svg>
    )
  }
  return <span ref={ref} className="spark" aria-hidden="true">{svg}</span>
}
