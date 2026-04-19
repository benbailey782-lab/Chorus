/**
 * IncompleteChapterDialog — modal shown when an attempt to load a chapter
 * surfaces missing-audio segments. Gives the user a direct path into Chapter
 * Review so they can generate what's missing.
 *
 * NOTE (Phase 6 Commit 5): We navigate to Chapter Review with a
 * `?filter=missing-audio` hint. Phase-4 review filter state (see
 * `frontend/src/lib/review-filters.ts`) currently persists filters in
 * localStorage keyed by chapterId and does NOT read URL query params, nor
 * does it include a "missing audio" axis. The query param is therefore
 * aspirational today — it lands harmlessly. Phase 7 (or whichever phase
 * adds an audio-status filter to the Review UI) should wire it up.
 */

import { useNavigate } from "react-router-dom";

interface Props {
  open: boolean;
  missingCount: number;
  totalCount: number;
  projectIdOrSlug: string;
  chapterId: string;
  onClose: () => void;
}

export default function IncompleteChapterDialog({
  open,
  missingCount,
  totalCount,
  projectIdOrSlug,
  chapterId,
  onClose,
}: Props) {
  const navigate = useNavigate();

  if (!open) return null;

  function goGenerate() {
    navigate(
      `/project/${projectIdOrSlug}/chapters/${chapterId}?filter=missing-audio`,
    );
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="incomplete-chapter-title"
      className="fixed inset-0 z-40 bg-bg/80 backdrop-blur flex items-center
                 justify-center px-4 py-6"
      onClick={onClose}
    >
      <div
        className="card max-w-md w-full p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <h2 id="incomplete-chapter-title" className="font-display text-xl">
            Chapter incomplete
          </h2>
          <p className="mt-2 text-sm text-muted">
            This chapter has{" "}
            <span className="text-fg font-medium">{missingCount}</span> of{" "}
            <span className="text-fg font-medium">{totalCount}</span> segments
            without audio. Generate them first?
          </p>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={goGenerate}>
            Generate missing
          </button>
        </div>
      </div>
    </div>
  );
}
