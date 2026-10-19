/** Meme dessin que public/favicon.svg. */
export function BrandMark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" fill="currentColor" />
      <rect x="7" y="7" width="8" height="8" rx="2" fill="var(--page)" />
      <rect x="17" y="7" width="8" height="8" rx="2" fill="var(--page)" />
      <rect x="7" y="17" width="8" height="8" rx="2" fill="var(--page)" />
      <rect x="17" y="17" width="8" height="8" rx="2" fill="var(--accent)" />
    </svg>
  )
}
