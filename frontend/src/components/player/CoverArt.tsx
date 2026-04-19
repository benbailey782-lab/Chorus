/**
 * CoverArt — placeholder cover card shown in the player.
 *
 * The Project type carries `cover_art_path` (spec §13B), but an upload
 * pipeline for covers hasn't been added yet. If/when that ships, this
 * component should accept a `coverPath` prop and render an <img> that falls
 * back to the placeholder for nullable paths.
 *
 * Decoration is a pure-CSS subtle diagonal grid so there's no image
 * dependency; it stays crisp at any viewport.
 */

interface Props {
  title: string;
  chapterTitle?: string;
  chapterNumber?: number;
  /** 16:9 for desktop, square for mobile. */
  ratio?: "square" | "wide";
}

export default function CoverArt({
  title,
  chapterTitle,
  chapterNumber,
  ratio = "wide",
}: Props) {
  const aspect = ratio === "square" ? "aspect-square" : "aspect-video";

  return (
    <div
      className={`${aspect} w-full rounded-card border border-border overflow-hidden
                  relative bg-gradient-to-br from-surface to-surface-2`}
      aria-hidden
    >
      {/* Diagonal stripe decoration */}
      <div
        className="absolute inset-0 opacity-20 pointer-events-none"
        style={{
          backgroundImage:
            "repeating-linear-gradient(45deg, rgba(78, 200, 190, 0.35) 0px, rgba(78, 200, 190, 0.35) 1px, transparent 1px, transparent 28px)",
        }}
      />
      <div
        className="absolute inset-0 opacity-10 pointer-events-none"
        style={{
          backgroundImage:
            "radial-gradient(circle at 30% 20%, rgba(78, 200, 190, 0.5), transparent 60%)",
        }}
      />

      <div className="relative h-full w-full flex flex-col justify-between p-5 md:p-6">
        <div className="text-[10px] uppercase tracking-[0.2em] text-accent/80">
          Chorus
        </div>
        <div className="space-y-2">
          <div className="font-display text-2xl md:text-3xl leading-tight">
            {title}
          </div>
          {(chapterNumber !== undefined || chapterTitle) && (
            <div className="text-xs md:text-sm text-muted">
              {chapterNumber !== undefined && (
                <span className="uppercase tracking-wider">
                  Chapter {chapterNumber}
                </span>
              )}
              {chapterTitle && chapterNumber !== undefined && (
                <span className="mx-2 opacity-60">·</span>
              )}
              {chapterTitle && <span className="italic">{chapterTitle}</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
