"use client";
import { ApiError } from "@/lib/api";

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="banner fail" role="alert">
      <div className="grow">
        <div>{e ? e.message.charAt(0).toUpperCase() + e.message.slice(1) : "Something went wrong. Try again."}</div>
        {e?.requestId && <div className="ref">ref: {e.requestId}</div>}
      </div>
      {onRetry && <button className="small" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function ScoreRing({ score, max, size = 64 }: { score: string | null; max: string; size?: number }) {
  const p = score === null ? 0 : Math.min(1, Number(score) / Number(max || 1));
  const r = size / 2 - 5;
  const c = 2 * Math.PI * r;
  const color = score === null ? "var(--line)" : p >= 0.999 ? "var(--pass)" : p > 0 ? "var(--signal)" : "var(--fail)";
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={score === null ? "No score yet" : `${score} out of ${max}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e7ecf4" strokeWidth="6" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round"
        strokeDasharray={`${c * p} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="52%" textAnchor="middle" dominantBaseline="middle" fontSize={size / 4.2}
        fontFamily="var(--font-display)" fontWeight="700" fill="var(--ink)">
        {score === null ? "—" : Math.round(Number(score))}
      </text>
    </svg>
  );
}
