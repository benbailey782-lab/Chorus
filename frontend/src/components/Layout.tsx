import { Link, Outlet, useLocation } from "react-router-dom";

import BottomNav from "./BottomNav";
import ToastContainer from "./Toast";
import MiniPlayer from "./player/MiniPlayer";

/**
 * Root shell for every route (Phase 6, commit 6).
 *
 * Convention: ALL routes render inside this Layout via `<Outlet />`. The
 * persistent surfaces (bottom nav, mini-player, toasts) live here so they
 * stay mounted across route changes — that's what keeps audio + player
 * state alive when the user navigates from `/play/:idOrSlug` back to
 * `/library` or `/player`.
 *
 * Why not also mount VoiceboxStatusBanner + PendingJobsBanner here?
 * - VoiceboxStatusBanner is explicitly scoped to the voice-admin surfaces
 *   (VoiceLibrary, VoiceEditor) — it surfaces TTS backend health, not a
 *   global concern.
 * - PendingJobsBanner takes a `projectIdOrSlug` prop. It only makes sense
 *   inside a project context (Casting, Project). Moving it here would
 *   require either dropping the prop (and fetching all-project jobs) or
 *   deriving the id from the URL — both out of scope for this commit.
 * Keep them mounted per-route where they're actually needed.
 */
export default function Layout() {
  const location = useLocation();
  // Mini-player renders globally EXCEPT on the full Player route, where the
  // full-screen transport controls already own the UI. Showing both would
  // duplicate play/pause and look cluttered on mobile.
  const onFullPlayer = location.pathname.startsWith("/play/");

  return (
    <div className="min-h-full flex flex-col">
      {/* Header is compact on mobile so the useful stuff is above the fold
          at 375px. Nav is at the bottom on mobile, inline here on ≥md. */}
      <header className="sticky top-0 z-10 border-b border-border bg-bg/90 backdrop-blur">
        <div
          className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between gap-3"
          style={{ paddingTop: "calc(0.75rem + env(safe-area-inset-top, 0px))" }}
        >
          <Link
            to="/"
            className="font-display text-2xl tracking-tight hover:text-accent"
          >
            Chorus
          </Link>
          <div className="hidden md:block">
            <BottomNav />
          </div>
        </div>
      </header>

      <main
        className="flex-1 max-w-5xl w-full mx-auto px-4 py-4 md:py-6"
        style={{
          // Leave room for the bottom nav (mobile) + mini-player strip.
          paddingBottom:
            "calc(5rem + 80px + env(safe-area-inset-bottom, 0px))",
        }}
      >
        <Outlet />
      </main>

      {/* Persistent surfaces. Mini-player sits ABOVE the BottomNav. */}
      {!onFullPlayer && <MiniPlayer />}

      {/* Mobile bottom nav — hidden on ≥md where it lives in the header. */}
      <div className="md:hidden">
        <BottomNav />
      </div>

      <ToastContainer />
    </div>
  );
}
