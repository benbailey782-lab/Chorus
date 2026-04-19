import { Link, Outlet, useLocation } from "react-router-dom";

import BottomNav from "./BottomNav";
import ToastContainer from "./Toast";
import MiniPlayer from "./player/MiniPlayer";
import ModelLoadingBanner from "./voicebox/ModelLoadingBanner";
import { useModelLoadingStore } from "../stores/modelLoadingStore";

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

  // Phase-5R Commit 6: surface Voicebox model-load progress whenever any
  // page kicks a load. Read at Layout level so the banner lives above the
  // route Outlet — if it moved inside per-page banners it would unmount
  // on navigation and lose the polling query.
  const loadingModelName = useModelLoadingStore((s) => s.modelName);
  const setLoadingModelName = useModelLoadingStore((s) => s.setModelName);

  return (
    <div className="min-h-full flex flex-col">
      {/* Header is compact on mobile so the useful stuff is above the fold
          at 375px. Nav is at the bottom on mobile, inline here on ≥md.
          Phase 6.6 commit 3: on /play/:id mobile we hide the global
          "Chorus" brand row entirely — the player route renders its own
          44px compressed header. Desktop (≥md) keeps the brand row since
          it hosts the inline nav. */}
      <header
        className={`sticky top-0 z-10 border-b border-border bg-bg/90 backdrop-blur ${
          onFullPlayer ? "hidden md:block" : ""
        }`}
      >
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
        className={
          onFullPlayer
            ? // Mobile player owns its own padding + flush-to-BottomNav
              // layout. On mobile, we zero out the wrapper's px/py so the
              // 44px header + card + transport can stretch edge-to-edge
              // and sit flush above the BottomNav. Desktop keeps the
              // standard gutter since the 3-column desktop player fits
              // inside the max-w-5xl content area.
              "flex-1 max-w-5xl w-full mx-auto px-0 py-0 md:px-4 md:py-6"
            : "flex-1 max-w-5xl w-full mx-auto px-4 py-4 md:py-6"
        }
        style={{
          // MiniPlayer is now a floating card (absolutely positioned) so
          // main content only needs to reserve BottomNav space (4rem) plus
          // iOS home-indicator inset. Phase-6.5 commit 3.
          // On /play/:id the mobile Player.tsx manages its own bottom-nav
          // clearance via a flex column sized to viewport, so we drop the
          // wrapper's pb entirely on mobile (desktop still wants the gap
          // to keep the main column clear of the inline BottomNav).
          paddingBottom: onFullPlayer
            ? undefined
            : "calc(4rem + env(safe-area-inset-bottom, 0px))",
        }}
      >
        {loadingModelName && (
          <div className="mb-3">
            <ModelLoadingBanner
              modelName={loadingModelName}
              onComplete={() => {
                // The banner clears the store itself after its success
                // flash; this callback is here so future pages can plug
                // in "now actually trigger generation" flows if we pivot
                // to the "wait for banner complete" pattern.
              }}
              onError={(msg) => {
                // Error banner stays until the user dismisses it; we
                // don't auto-clear on error to give them time to read.
                // This void is intentional — parent logic currently has
                // no work to do beyond what the banner already renders.
                void msg;
                void setLoadingModelName;
              }}
            />
          </div>
        )}

        <Outlet />
      </main>

      {/* Persistent surfaces. MiniPlayer floats above everything; BottomNav
          sits at the bottom of the viewport on mobile. */}
      {!onFullPlayer && <MiniPlayer />}

      {/* Mobile bottom nav — hidden on ≥md where it lives in the header. */}
      <div className="md:hidden">
        <BottomNav />
      </div>

      <ToastContainer />
    </div>
  );
}
