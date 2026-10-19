export type IconName =
  | 'sun' | 'moon' | 'monitor' | 'check' | 'check-circle' | 'alert-circle'
  | 'alert-triangle' | 'x-circle' | 'loader' | 'arrow-up' | 'arrow-down'
  | 'arrow-right' | 'chevron-down' | 'chart-line' | 'table' | 'download'
  | 'clock' | 'radio' | 'alert-octagon' | 'bell-off' | 'x'

interface Props {
  name: IconName
  size?: 12 | 14 | 16 | 24
  className?: string
}

/** Traces 24x24 dessines a la main (style Lucide), sans bibliotheque. */
function paths(name: IconName) {
  switch (name) {
    case 'sun':
      return <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" /></>
    case 'moon':
      return <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    case 'monitor':
      return <><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></>
    case 'check':
      return <path d="M20 6 9 17l-5-5" />
    case 'check-circle':
      return <><circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" /></>
    case 'alert-circle':
      return <><circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" /></>
    case 'alert-triangle':
      return <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0ZM12 9v4M12 17h.01" />
    case 'x-circle':
      return <><circle cx="12" cy="12" r="10" /><path d="m15 9-6 6M9 9l6 6" /></>
    case 'loader':
      return <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    case 'arrow-up':
      return <path d="M12 19V5M5 12l7-7 7 7" />
    case 'arrow-down':
      return <path d="M12 5v14M19 12l-7 7-7-7" />
    case 'arrow-right':
      return <path d="M5 12h14M12 5l7 7-7 7" />
    case 'chevron-down':
      return <path d="m6 9 6 6 6-6" />
    case 'chart-line':
      return <path d="M3 3v16a2 2 0 0 0 2 2h16M7 15l4-5 4 4 5-6" />
    case 'table':
      return <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M3 15h18M12 3v18" /></>
    case 'download':
      return <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
    case 'clock':
      return <><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></>
    case 'alert-octagon':
      return <><path d="M7.86 2h8.28L22 7.86v8.28L16.14 22H7.86L2 16.14V7.86Z" /><path d="M12 8v4M12 16h.01" /></>
    case 'bell-off':
      return <><path d="M10.27 21a2 2 0 0 0 3.46 0M17 17H4a1 1 0 0 1-.74-1.67C4.59 13.96 6 12.5 6 8a6 6 0 0 1 .26-1.74M8.67 3.01A6 6 0 0 1 18 8c0 2.69.77 4.65 1.71 6.05" /><path d="m2 2 20 20" /></>
    case 'x':
      return <path d="M18 6 6 18M6 6l12 12" />
    case 'radio':
      return <><circle cx="12" cy="12" r="2" /><path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5M19.1 4.9C23 8.8 23 15.2 19.1 19.1" /></>
  }
}

/** Icone de ligne monochrome (currentColor). La coche de selection des
 * segmentes est en trait epais (2.5). */
export function Icon({ name, size = 14, className }: Props) {
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor"
      strokeWidth={name === 'check' ? 2.5 : 1.75}
      strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false"
    >
      {paths(name)}
    </svg>
  )
}
