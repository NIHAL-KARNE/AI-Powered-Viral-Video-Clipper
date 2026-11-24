import type { ReactNode } from "react";
import { scoreColor } from "../lib/api";

export function PageHead({
  title,
  subtitle,
  action,
  eyebrow,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  /** Small uppercase label above the title, for orientation. */
  eyebrow?: string;
}) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-2 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-violet-300/80">
            <span className="h-px w-6 bg-gradient-to-r from-violet-400/80 to-transparent" />
            {eyebrow}
          </p>
        )}
        <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.03em] text-white sm:text-[32px]">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-slate-400">{subtitle}</p>
        )}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  );
}

export function ScoreRing({ score, size = 54 }: { score: number; size?: number }) {
  const c = scoreColor(score);
  const r = size / 2 - 5;
  const circumference = 2 * Math.PI * r;
  const dash = (score / 100) * circumference;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke="rgba(255,255,255,0.09)"
          strokeWidth="4"
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke="currentColor"
          className={c.text}
          strokeWidth="4"
          strokeLinecap="round"
          fill="none"
          strokeDasharray={`${dash} ${circumference}`}
          style={{ filter: "drop-shadow(0 0 6px currentColor)" }}
        />
      </svg>
      <span
        className={`absolute inset-0 grid place-items-center font-semibold tabular-nums ${c.text}`}
        style={{ fontSize: size * 0.28 }}
      >
        {score.toFixed(0)}
      </span>
    </div>
  );
}

export function ScoreBadge({ score }: { score: number }) {
  const c = scoreColor(score);
  return (
    <span className={`chip ${c.text} border-current/25 bg-current/10 font-semibold`}>
      <span className={`h-1.5 w-1.5 rounded-full ${c.bg}`} />
      {score.toFixed(0)} viral score
    </span>
  );
}

export function ProgressBar({ value, className = "" }: { value: number; className?: string }) {
  return (
    <div
      className={`relative h-1.5 w-full overflow-hidden rounded-full border border-white/8 bg-black/40 ${className}`}
    >
      <div
        className="relative h-full rounded-full bg-gradient-to-r from-violet-500 via-violet-400 to-teal-300 transition-[width] duration-500 ease-out"
        style={{ width: `${Math.min(Math.max(value, 0), 1) * 100}%` }}
      >
        <span className="absolute inset-0 rounded-full bg-gradient-to-b from-white/40 to-transparent" />
      </div>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center justify-center px-6 py-16 text-center">
      <div className="relative grid h-16 w-16 place-items-center rounded-[18px] border border-white/10 bg-gradient-to-b from-white/10 to-white/[0.02] text-violet-200 shadow-[inset_0_1px_0_rgba(255,255,255,0.18),0_18px_40px_-24px_rgba(129,102,255,0.9)]">
        <span className="absolute inset-x-2 top-0 h-8 rounded-full bg-violet-400/15 blur-xl" />
        {icon}
      </div>
      <h3 className="mt-5 text-[15px] font-semibold text-white">{title}</h3>
      <p className="mt-1.5 max-w-md text-[13px] leading-relaxed text-slate-400">{body}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-rose-400/30 bg-rose-500/[0.09] px-4 py-3 text-[13px] text-rose-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.07)] backdrop-blur-xl">
      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-rose-500/25 text-[11px] font-bold text-rose-100">
        !
      </span>
      <p className="min-w-0 flex-1 break-words">{message}</p>
      {onClose && (
        <button
          onClick={onClose}
          className="text-rose-300/70 transition hover:text-rose-100"
          aria-label="Dismiss"
        >
          ×
        </button>
      )}
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      className="inline-block animate-spin rounded-full border-2 border-current border-t-transparent"
      style={{ width: size, height: size }}
    />
  );
}
