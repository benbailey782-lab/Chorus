/**
 * MobileControlsSheet — swipe-up bottom sheet over the mobile player.
 *
 * Phase 6.6 commit 3. Houses player-level preferences and chapter nav
 * that used to live in disparate places (settings cog, chapter bottom
 * sheet). One source of truth; both the overflow menu in the compressed
 * header and the swipe-up indicator open this same sheet.
 *
 * Interactions:
 *   - Tap backdrop → close.
 *   - Tap indicator pill on sheet header → close.
 *   - Swipe-down on sheet header (pointerdown + move >30px) → close.
 *   - Escape key → close.
 *
 * Rows (see spec):
 *   1. Auto-advance toggle — wired to playerStore.
 *   2. Chapter list — tap a chapter, sheet closes, controller loads + plays.
 *   3. Sleep timer — disabled placeholder ("Coming in Phase 7").
 *   4. Equalizer — disabled placeholder.
 *   5. Output device — disabled placeholder.
 */

import { useEffect, useRef } from "react";

import { playerController } from "../../lib/audioPlayer";
import type { Chapter } from "../../lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
  autoAdvance: boolean;
  onToggleAutoAdvance: (on: boolean) => void;
  chapters: Chapter[];
  currentChapterId: string | null;
  projectIdOrSlug: string;
}

export default function MobileControlsSheet({
  open,
  onClose,
  autoAdvance,
  onToggleAutoAdvance,
  chapters,
  currentChapterId,
  projectIdOrSlug,
}: Props) {
  // Escape-to-close.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Swipe-down-to-close on the header grabber.
  const dragStartY = useRef<number | null>(null);
  function onHeaderPointerDown(e: React.PointerEvent) {
    dragStartY.current = e.clientY;
  }
  function onHeaderPointerMove(e: React.PointerEvent) {
    if (dragStartY.current === null) return;
    const dy = e.clientY - dragStartY.current;
    if (dy > 30) {
      dragStartY.current = null;
      onClose();
    }
  }
  function onHeaderPointerEnd() {
    dragStartY.current = null;
  }

  function pickChapter(id: string) {
    onClose();
    void playerController.loadChapter(projectIdOrSlug, id).then(() => {
      playerController.play();
    });
  }

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Player controls"
      className="fixed inset-0 z-50 flex items-end bg-bg/80 backdrop-blur"
      onClick={onClose}
    >
      <div
        className="w-full bg-bg border-t border-border rounded-t-card
                   max-h-[60vh] flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Grabber — tap OR swipe-down closes. */}
        <button
          type="button"
          aria-label="Close controls"
          onClick={onClose}
          onPointerDown={onHeaderPointerDown}
          onPointerMove={onHeaderPointerMove}
          onPointerUp={onHeaderPointerEnd}
          onPointerCancel={onHeaderPointerEnd}
          className="w-full py-2 flex justify-center shrink-0 touch-none"
        >
          <span
            aria-hidden="true"
            className="block h-1 w-10 rounded-full bg-border"
          />
        </button>

        <div className="px-5 pb-5 overflow-y-auto flex-1">
          <div className="font-display text-lg mb-3">Controls</div>

          {/* Auto-advance toggle */}
          <Row>
            <label className="flex items-center justify-between gap-3 w-full cursor-pointer">
              <span className="text-sm">
                <span className="block">Auto-advance</span>
                <span className="block text-xs text-muted">
                  Play next chapter automatically.
                </span>
              </span>
              <input
                type="checkbox"
                checked={autoAdvance}
                onChange={(e) => onToggleAutoAdvance(e.target.checked)}
                className="h-5 w-5 accent-accent shrink-0"
              />
            </label>
          </Row>

          {/* Chapter list */}
          <div className="mt-4 mb-1 text-[10px] uppercase tracking-wider text-muted px-1">
            Chapters
          </div>
          <div className="border border-border rounded-card overflow-hidden">
            {chapters.map((ch) => {
              const active = ch.id === currentChapterId;
              return (
                <button
                  key={ch.id}
                  type="button"
                  onClick={() => pickChapter(ch.id)}
                  className={[
                    "w-full text-left px-3 py-3 min-h-[48px] flex items-center gap-3",
                    "border-l-2 border-b border-border last:border-b-0",
                    active
                      ? "border-l-accent bg-surface-2"
                      : "border-l-transparent hover:bg-surface-2",
                  ].join(" ")}
                >
                  <span
                    className={`text-xs tabular-nums w-8 shrink-0 ${
                      active ? "text-accent" : "text-muted"
                    }`}
                  >
                    {ch.number}
                  </span>
                  <span
                    className={`text-sm truncate flex-1 ${
                      active ? "text-fg font-medium" : "text-fg"
                    }`}
                  >
                    {ch.title ?? `Chapter ${ch.number}`}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Disabled placeholders */}
          <div className="mt-4 space-y-0 border border-border rounded-card overflow-hidden">
            <DisabledRow label="Sleep timer" />
            <DisabledRow label="Equalizer" />
            <DisabledRow label="Output device" />
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-[48px] py-2 flex items-center">
      {children}
    </div>
  );
}

function DisabledRow({ label }: { label: string }) {
  return (
    <div
      aria-disabled="true"
      className="px-3 py-3 min-h-[48px] flex items-center justify-between
                 border-b border-border last:border-b-0 text-muted select-none"
    >
      <span className="text-sm">{label}</span>
      <span className="text-[10px] uppercase tracking-wider">
        Coming in Phase 7
      </span>
    </div>
  );
}
