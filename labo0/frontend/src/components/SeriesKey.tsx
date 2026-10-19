/** Slot 1-8 ; decorative : le nom du capteur est toujours ecrit a cote. */
export function SeriesKey({ slot }: { slot: number }) {
  return <span className="key" style={{ background: `var(--series-${slot})` }} aria-hidden="true" />
}
