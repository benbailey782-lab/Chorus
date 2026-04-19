import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import ChaptersSection from "../components/casting/ChaptersSection";
import PendingJobsBanner from "../components/PendingJobsBanner";
import {
  api,
  type Character,
  type ExtractCastResult,
  type Job,
  type Voice,
} from "../lib/api";
import { POOL_TARGETS, type Pool } from "../lib/constants";

const TIER_TO_POOL: Record<string, Pool> = {
  main: "main",
  supporting: "main",
  minor: "background",
  background: "background",
};

const ACTIVE_STATUSES = new Set(["queued", "running", "awaiting_response"] as const);

export default function Casting() {
  const { idOrSlug = "" } = useParams();
  const qc = useQueryClient();

  const project = useQuery({
    queryKey: ["project", idOrSlug],
    queryFn: () => api.getProject(idOrSlug),
    enabled: !!idOrSlug,
  });

  const characters = useQuery({
    queryKey: ["characters", idOrSlug],
    queryFn: () => api.listCharacters(idOrSlug),
    enabled: !!idOrSlug,
  });

  const voices = useQuery({
    queryKey: ["voices", {}],
    queryFn: () => api.listVoices(),
  });

  const jobs = useQuery({
    queryKey: ["project-jobs", idOrSlug],
    queryFn: () => api.listProjectJobs(idOrSlug),
    refetchInterval: (q) => {
      const data = q.state.data as Job[] | undefined;
      if (!data) return 2000;
      return data.some((j) => ACTIVE_STATUSES.has(j.status as typeof ACTIVE_STATUSES extends Set<infer T> ? T : never))
        ? 2000
        : false;
    },
    enabled: !!idOrSlug,
  });

  const extractMut = useMutation({
    mutationFn: () => api.extractCast(idOrSlug),
    onSuccess: (res) => {
      setExtractPreview(res);
      qc.invalidateQueries({ queryKey: ["project-jobs", idOrSlug] });
    },
  });

  const autoCastMut = useMutation({
    mutationFn: () => api.autoCast(idOrSlug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-jobs", idOrSlug] });
    },
  });

  const assignMut = useMutation({
    mutationFn: ({ id, voice_id }: { id: string; voice_id: string | null }) =>
      api.updateCharacter(id, { voice_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["characters", idOrSlug] });
    },
  });

  const [selectedCharId, setSelectedCharId] = useState<string | null>(null);
  const [extractModalOpen, setExtractModalOpen] = useState(false);
  const [extractPreview, setExtractPreview] = useState<ExtractCastResult | null>(null);

  const hasCast = (characters.data?.length ?? 0) > 0;
  const voiceCount = voices.data?.length ?? 0;

  const activeJob = (jobs.data ?? []).find((j) =>
    ACTIVE_STATUSES.has(j.status as typeof ACTIVE_STATUSES extends Set<infer T> ? T : never),
  );
  const extractJobActive =
    !!activeJob && activeJob.kind === "extract_characters";
  const autoCastJobActive = !!activeJob && activeJob.kind === "auto_cast";

  const selectedChar =
    selectedCharId && characters.data
      ? characters.data.find((c) => c.id === selectedCharId) ?? null
      : null;

  if (project.isLoading) return <p className="text-muted">Loading…</p>;
  if (project.isError)
    return (
      <p className="text-error">
        {(project.error as Error).message}{" "}
        <Link to="/" className="underline text-accent">Back</Link>
      </p>
    );
  if (!project.data) return null;

  const p = project.data;

  return (
    <div className="space-y-4 pb-6">
      <div>
        <Link to={`/project/${idOrSlug}`} className="text-sm text-muted hover:text-fg">
          ← {p.title}
        </Link>
        <h1 className="text-3xl mt-1">Casting</h1>
        <div className="text-xs mt-1 text-muted">
          project status: {p.status} · {p.chapter_count} chapters
        </div>
      </div>

      <PendingJobsBanner projectIdOrSlug={idOrSlug} />

      {/* Top actions ------------------------------------------------- */}
      <div className="flex flex-wrap gap-2 items-center">
        {!hasCast && (
          <button
            type="button"
            className="btn-primary"
            disabled={extractJobActive || extractMut.isPending || p.chapter_count === 0}
            onClick={() => setExtractModalOpen(true)}
          >
            {extractJobActive ? "Extracting…" : "Extract Cast"}
          </button>
        )}
        {hasCast && (
          <button
            type="button"
            className="btn-primary"
            disabled={autoCastJobActive || autoCastMut.isPending || voiceCount === 0}
            onClick={() => autoCastMut.mutate()}
          >
            {autoCastJobActive ? "Auto-casting…" : "Run Auto-Cast"}
          </button>
        )}
        {hasCast && voiceCount === 0 && (
          <span className="text-xs text-muted">
            Add a voice to the <Link to="/voices" className="text-accent underline">voice library</Link> before auto-casting.
          </span>
        )}
        {!hasCast && p.chapter_count === 0 && (
          <span className="text-xs text-muted">
            Ingest a source file on the <Link to={`/project/${idOrSlug}`} className="text-accent underline">project page</Link> before extracting the cast.
          </span>
        )}
        <Link
          to={`/project/${idOrSlug}/pronunciations`}
          className="btn-surface text-sm"
        >
          Pronunciations
        </Link>
        <Link
          to={`/play/${idOrSlug}`}
          className="btn-surface text-sm"
          title="Open the full-screen player for this project"
        >
          Open player
        </Link>
      </div>

      {/* Main layout ------------------------------------------------- */}
      {!hasCast ? (
        <EmptyCastState
          disabled={p.chapter_count === 0}
          onExtract={() => setExtractModalOpen(true)}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-[1.2fr_1fr]">
          <CharacterGrid
            characters={characters.data ?? []}
            selectedId={selectedCharId}
            voices={voices.data ?? []}
            onSelect={(id) => setSelectedCharId(id)}
          />
          <CastingPane
            character={selectedChar}
            voices={voices.data ?? []}
            saving={assignMut.isPending}
            onAssign={(voice_id) => {
              if (!selectedChar) return;
              assignMut.mutate({ id: selectedChar.id, voice_id });
            }}
          />
        </div>
      )}

      {/* Chapters section ------------------------------------------- */}
      <ChaptersSection projectIdOrSlug={idOrSlug} projectId={p.id} />

      {/* Extract-cast modal ----------------------------------------- */}
      {extractModalOpen && (
        <ExtractCastModal
          project={{ slug: idOrSlug }}
          preview={extractPreview}
          pending={extractMut.isPending}
          error={(extractMut.error as Error | undefined)?.message ?? null}
          onClose={() => {
            setExtractModalOpen(false);
            setExtractPreview(null);
            extractMut.reset();
          }}
          onSubmit={() => extractMut.mutate()}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyCastState({ disabled, onExtract }: { disabled: boolean; onExtract: () => void }) {
  return (
    <div className="card p-6 text-sm space-y-3">
      <div className="font-display text-xl">No cast extracted yet</div>
      <p className="text-muted">
        The cast is the set of characters that will be voiced in this audiobook.
        Chorus drops a prompt file into <code className="font-mono">data/llm_queue/pending/</code>;
        your companion Claude Code session processes it and drops the response
        back into <code className="font-mono">data/llm_queue/responses/</code>.
      </p>
      <div>
        <button
          type="button"
          className="btn-primary"
          disabled={disabled}
          onClick={onExtract}
        >
          Extract Cast
        </button>
      </div>
      {disabled && (
        <p className="text-xs text-muted">
          Ingest a source file first. The project has no chapters yet.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Character grid
// ---------------------------------------------------------------------------

function CharacterGrid({
  characters,
  selectedId,
  voices,
  onSelect,
}: {
  characters: Character[];
  selectedId: string | null;
  voices: Voice[];
  onSelect: (id: string) => void;
}) {
  const voiceById = useMemo(() => {
    const m = new Map<string, Voice>();
    voices.forEach((v) => m.set(v.id, v));
    return m;
  }, [voices]);

  return (
    <ul className="grid gap-2 sm:grid-cols-2 md:grid-cols-1 lg:grid-cols-2">
      {characters.map((c) => (
        <li key={c.id}>
          <button
            type="button"
            onClick={() => onSelect(c.id)}
            className={`card w-full p-3 text-left transition-colors
                        ${selectedId === c.id ? "border-accent" : "hover:border-accent/40"}`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-display text-lg leading-tight truncate">
                  {c.name}
                  {c.is_narrator && (
                    <span className="ml-2 text-[10px] uppercase tracking-wider text-accent">
                      narrator
                    </span>
                  )}
                </div>
                <div className="text-xs text-muted truncate">
                  {[c.gender, c.age_estimate, c.character_archetype]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </div>
              </div>
              {c.estimated_line_count && (
                <span className="chip text-[10px] uppercase tracking-wider text-muted shrink-0">
                  {c.estimated_line_count}
                </span>
              )}
            </div>
            {c.description && (
              <p className="mt-2 text-xs text-muted line-clamp-2">
                {c.description}
              </p>
            )}
            <div className="mt-2 flex items-center gap-2">
              {c.voice_id ? (
                <span className="text-xs text-fg truncate">
                  🎤 {voiceById.get(c.voice_id)?.display_name ?? c.voice_id}
                </span>
              ) : (
                <span className="text-xs text-muted italic">unassigned</span>
              )}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Casting pane
// ---------------------------------------------------------------------------

function CastingPane({
  character,
  voices,
  saving,
  onAssign,
}: {
  character: Character | null;
  voices: Voice[];
  saving: boolean;
  onAssign: (voice_id: string | null) => void;
}) {
  if (!character) {
    return (
      <div className="card p-4 text-sm text-muted">
        Select a character on the left to assign or change a voice.
      </div>
    );
  }

  // Filter voices by tier-derived pool, with same-gender preference pinned first.
  const preferredPool = character.estimated_line_count
    ? TIER_TO_POOL[character.estimated_line_count]
    : null;
  const eligible = voices
    .filter((v) => {
      if (character.is_narrator) return v.pool === "narrator" || v.pool === "main";
      if (preferredPool === "background") return v.pool === "background" || v.pool === "main";
      return v.pool !== "narrator";
    })
    .sort((a, b) => {
      const ga = character.gender && a.gender === character.gender ? 0 : 1;
      const gb = character.gender && b.gender === character.gender ? 0 : 1;
      if (ga !== gb) return ga - gb;
      return a.display_name.localeCompare(b.display_name);
    });

  return (
    <div className="card p-4 space-y-4">
      <div>
        <div className="font-display text-xl">{character.name}</div>
        {character.description && (
          <p className="mt-1 text-sm text-muted">{character.description}</p>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-2 text-xs">
        <Meta label="Gender" value={character.gender} />
        <Meta label="Age" value={character.age_estimate} />
        <Meta label="Archetype" value={character.character_archetype} />
        <Meta label="Tier" value={character.estimated_line_count} />
        <Meta
          label="First appears"
          value={
            character.first_appearance_chapter
              ? `ch. ${character.first_appearance_chapter}`
              : null
          }
        />
        {character.engine_override && (
          <Meta label="Engine" value={character.engine_override} />
        )}
      </dl>

      {character.speaking_style && (
        <div className="text-xs">
          <div className="text-muted uppercase tracking-wider mb-1">Speaking style</div>
          <p className="text-fg">{character.speaking_style}</p>
        </div>
      )}

      <div>
        <div className="flex items-baseline justify-between mb-2">
          <div className="text-xs text-muted uppercase tracking-wider">
            Voice (pool: {preferredPool ?? (character.is_narrator ? "narrator" : "main")})
          </div>
          {character.voice_id && (
            <button
              type="button"
              className="text-xs text-error hover:underline"
              onClick={() => onAssign(null)}
              disabled={saving}
            >
              Clear assignment
            </button>
          )}
        </div>
        {eligible.length === 0 ? (
          <div className="text-xs text-muted italic">
            No eligible voices in the library for this character.{" "}
            <Link to="/voices/new" className="text-accent underline">
              Add a voice
            </Link>
            .
          </div>
        ) : (
          <ul className="space-y-1.5 max-h-80 overflow-auto">
            {eligible.map((v) => {
              const selected = v.id === character.voice_id;
              return (
                <li key={v.id}>
                  <button
                    type="button"
                    onClick={() => onAssign(v.id)}
                    disabled={saving}
                    className={`card w-full p-2.5 text-left text-sm transition-colors
                                ${selected ? "border-accent bg-accent/5" : "hover:border-accent/40"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium truncate">{v.display_name}</span>
                      <span className="chip text-[10px] uppercase text-muted shrink-0">
                        {v.pool}
                      </span>
                    </div>
                    <div className="text-xs text-muted truncate">
                      {[v.gender, v.age_range, v.accent].filter(Boolean).join(" · ") || "—"}
                    </div>
                    {v.tone.length > 0 && (
                      <div className="text-[11px] text-muted truncate">
                        {v.tone.slice(0, 4).join(" · ")}
                      </div>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-muted uppercase tracking-wider">{label}</dt>
      <dd className="text-fg">{value || "—"}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Extract-cast modal
// ---------------------------------------------------------------------------

function ExtractCastModal({
  project,
  preview,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  project: { slug: string };
  preview: ExtractCastResult | null;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const submitted = preview !== null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-30 bg-bg/80 backdrop-blur flex items-center justify-center px-4 py-6"
      onClick={onClose}
    >
      <div
        className="card max-w-lg w-full p-5 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-baseline justify-between">
          <h2 className="font-display text-xl">Extract cast</h2>
          <button
            type="button"
            className="text-muted hover:text-fg text-xl leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {!submitted && (
          <>
            <p className="text-sm text-muted">
              Chorus will render the extract-cast prompt, substitute the book
              text, and write it to
              <code className="font-mono">
                {" "}data/llm_queue/pending/request_&lt;job-id&gt;.md
              </code>
              . Your companion Claude Code session should pick it up and drop the
              response JSON at
              <code className="font-mono">
                {" "}data/llm_queue/responses/response_&lt;job-id&gt;.json
              </code>
              .
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" className="btn-ghost" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={pending}
                onClick={onSubmit}
              >
                {pending ? "Writing…" : "Write request file"}
              </button>
            </div>
          </>
        )}

        {submitted && preview && (
          <>
            <div className="text-sm space-y-2">
              <p>
                Request written:{" "}
                <code className="font-mono text-xs break-all">
                  {preview.request_path}
                </code>
              </p>
              <p className="text-muted">
                {preview.book_text_chars.toLocaleString()} characters submitted.
              </p>
              {preview.truncated && preview.warnings.length > 0 && (
                <div className="card border-warn/40 bg-warn/10 px-3 py-2 text-warn text-xs">
                  <div className="font-medium mb-1">Truncation warning</div>
                  {preview.warnings.map((w, i) => (
                    <p key={i} className="whitespace-pre-wrap">{w}</p>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted">
                The job is now in <span className="font-mono">awaiting_response</span>.
                Once the response file lands, the cast list will appear here.
              </p>
            </div>
            <div className="flex justify-end pt-2">
              <button type="button" className="btn-primary" onClick={onClose}>
                Got it
              </button>
            </div>
          </>
        )}

        {error && !submitted && (
          <div className="card border-error/40 bg-error/10 px-3 py-2 text-sm text-error">
            {error}
          </div>
        )}

        <p className="text-[10px] text-muted mt-2">
          Pool targets (§7.3): main {POOL_TARGETS.main.min}–{POOL_TARGETS.main.max},
          narrator {POOL_TARGETS.narrator.min}–{POOL_TARGETS.narrator.max},
          background {POOL_TARGETS.background.min}–{POOL_TARGETS.background.max}. Project slug: {project.slug}.
        </p>
      </div>
    </div>
  );
}
