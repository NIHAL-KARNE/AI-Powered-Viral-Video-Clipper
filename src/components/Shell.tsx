import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  PlusSquare,
  Film,
  Scissors,
  Settings as SettingsIcon,
  Sparkles,
  Menu,
  X,
} from "lucide-react";
import { useState } from "react";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/new", label: "New Project", icon: PlusSquare },
  { to: "/videos", label: "My Videos", icon: Film },
  { to: "/clips", label: "Generated Clips", icon: Scissors },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  return (
    <div className="flex min-h-screen">
      {/* Sidebar: a floating glass rail, inset from the window edge so the page
          light shows around it. */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[260px] shrink-0 flex-col px-3 py-4 transition-transform duration-300 lg:static lg:translate-x-0
        ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="glass top-sheen flex min-h-0 flex-1 flex-col rounded-[20px] px-3 pb-4 pt-5">
          <div className="flex items-center justify-between px-2">
            <Link to="/" className="group flex items-center gap-2.5" onClick={() => setOpen(false)}>
              <span className="relative grid h-9 w-9 place-items-center overflow-hidden rounded-[11px] bg-gradient-to-br from-violet-400 via-violet-500 to-indigo-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.45),0_8px_20px_-8px_rgba(112,80,245,0.9)]">
                <span className="absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-white/35 to-transparent" />
                <Scissors className="relative h-4 w-4 text-white" size={16} />
              </span>
              <span className="text-[15px] font-semibold tracking-tight text-white">
                Clip<span className="text-violet-300">Forge</span>
              </span>
            </Link>
            <button
              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white lg:hidden"
              onClick={() => setOpen(false)}
              aria-label="Close menu"
            >
              <X size={18} />
            </button>
          </div>

          <nav className="mt-7 space-y-0.5">
            {NAV.map(({ to, label, icon: Icon }) => {
              const active = to === "/" ? pathname === "/" : pathname.startsWith(to);
              return (
                <Link
                  key={to}
                  to={to}
                  onClick={() => setOpen(false)}
                  className={`nav-link ${active ? "nav-link-active" : ""}`}
                >
                  <Icon
                    size={16}
                    className={active ? "text-violet-200" : "text-slate-400 transition group-hover:text-slate-300"}
                  />
                  {label}
                </Link>
              );
            })}
          </nav>

          <div className="mt-auto px-1 pt-4">
            <div className="glass-inset px-3.5 py-3.5">
              <div className="flex items-center gap-2 text-[11.5px] font-semibold text-violet-200">
                <span className="grid h-5 w-5 place-items-center rounded-md bg-violet-500/20">
                  <Sparkles size={11} className="text-violet-200" />
                </span>
                Local AI engine
              </div>
              <p className="mt-2 text-[11px] leading-[1.55] text-slate-400">
                Whisper transcription and signal analysis run on this machine. No third-party video
                uploads.
              </p>
            </div>
          </div>
        </div>
      </aside>

      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-white/8 bg-ink-950/60 px-4 py-3 backdrop-blur-xl lg:hidden">
          <button
            className="rounded-lg border border-white/10 bg-white/5 p-2 text-slate-300"
            onClick={() => setOpen(true)}
            aria-label="Open menu"
          >
            <Menu size={18} />
          </button>
          <span className="text-sm font-semibold text-white">
            Clip<span className="text-violet-300">Forge</span>
          </span>
        </header>
        <main className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
          {children}
        </main>
      </div>
    </div>
  );
}
