// Line icons (24×24, stroke = currentColor), drawn for this app so nothing is fetched at runtime.
import type { ReactNode } from "react";

const PATHS: Record<string, ReactNode> = {
  home: <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />,
  play: (
    <>
      <circle cx={12} cy={12} r={9} />
      <path d="m10 8.5 5.5 3.5-5.5 3.5z" />
    </>
  ),
  agent: (
    <>
      <rect x={4} y={7} width={16} height={12} rx={3} />
      <path d="M12 3v4M9 12h.01M15 12h.01M9.5 15.5h5" />
    </>
  ),
  test: <path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3M7.5 14h9" />,
  report: (
    <>
      <path d="M6 3h9l4 4v14H6z" />
      <path d="M14 3v5h5M9 13h7M9 17h5" />
    </>
  ),
  bug: (
    <>
      <path d="M8 8h8v6a4 4 0 0 1-8 0z" />
      <path d="M9 8V6a3 3 0 0 1 6 0v2M4 13h4M16 13h4M5 19l3-2M19 19l-3-2M5 7l3 2M19 7l-3 2" />
    </>
  ),
  tools: <path d="M14.5 6.5a4 4 0 0 0-5.3 5.3L3.5 17.5l3 3 5.7-5.7a4 4 0 0 0 5.3-5.3l-2.6 2.6-2.5-.5-.5-2.5z" />,
  info: (
    <>
      <circle cx={12} cy={12} r={9} />
      <path d="M12 11v6M12 7.5h.01" />
    </>
  ),
  logout: <path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10" />,
  chevron: <path d="m9 6 6 6-6 6" />,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  shield: (
    <>
      <path d="M12 3 5 6v5.5c0 4.4 3 8 7 9.5 4-1.5 7-5.1 7-9.5V6z" />
      <path d="m9 12 2.2 2.2L15.5 10" />
    </>
  ),
  plug: <path d="M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5" />,
  chat: <path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-4 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM8 9.5h8M8 12.5h5" />,
  database: (
    <>
      <ellipse cx={12} cy={6} rx={7} ry={2.8} />
      <path d="M5 6v12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6M5 12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8" />
    </>
  ),
  retest: <path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  user: (
    <>
      <circle cx={12} cy={8} r={4} />
      <path d="M4 21c1.2-4 4.3-6 8-6s6.8 2 8 6" />
    </>
  ),
  lock: (
    <>
      <rect x={5} y={10} width={14} height={11} rx={2} />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </>
  ),
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18, className = "", strokeWidth = 1.8 }: { name: IconName; size?: number; className?: string; strokeWidth?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden className={`shrink-0 ${className}`}>
      {PATHS[name]}
    </svg>
  );
}

/** The ConsentTrace mark: a trace of three steps, the last one checked. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className="shrink-0">
      <defs>
        <linearGradient id="ct-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3b82f6" />
          <stop offset="1" stopColor="#4338ca" />
        </linearGradient>
      </defs>
      <rect width={32} height={32} rx={8} fill="url(#ct-mark)" />
      <path d="M7 20.5h4.5l3-9 3 9" stroke="white" strokeOpacity={0.55} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M17.5 20.5 20.5 23.5 26 15" stroke="white" strokeWidth={2.6} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
