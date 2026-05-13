export function Logo({ size = 22 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2">
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
        <path
          d="M4 5 L12 3 L20 5 L20 11 C20 16 16 20 12 21 C8 20 4 16 4 11 Z"
          stroke="url(#fluxg)"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        <defs>
          <linearGradient id="fluxg" x1="4" y1="3" x2="20" y2="21">
            <stop offset="0%" stopColor="#a892ff" />
            <stop offset="100%" stopColor="#7c5cff" />
          </linearGradient>
        </defs>
      </svg>
      <span className="font-semibold tracking-tight">Flux</span>
    </div>
  );
}
