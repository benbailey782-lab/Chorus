import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import VoiceboxStatusBanner from "../components/VoiceboxStatusBanner";
import { api, sampleAudioUrl, type Voice } from "../lib/api";
import { POOLS, POOL_TARGETS, type Gender, type Pool } from "../lib/constants";

export default function VoiceLibrary() {
  const qc = useQueryClient();
  const [pool, setPool] = useState<Pool | null>(null);
  const [gender, setGender] = useState<Gender | null>(null);
  const [q, setQ] = useState("");

  const filter = useMemo(
    () => ({
      pool: pool ?? undefined,
      gender: gender ?? undefined,
      q: q.trim() || undefined,
    }),
    [pool, gender, q],
  );

  const voices = useQuery({
    queryKey: ["voices", filter],
    queryFn: () => api.listVoices(filter),
  });

  const counts = useQuery({
    queryKey: ["voice-pool-counts"],
    queryFn: api.voicePoolCounts,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteVoice(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["voices"] });
      qc.invalidateQueries({ queryKey: ["voice-pool-counts"] });
    },
  });

  const noFilters = !pool && !gender && !q.trim();
  const empty = voices.data?.length === 0 && noFilters;

  return (
    <div className="space-y-5 pb-6">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-3xl">Voices</h1>
        <Link to="/voices/new" className="btn-primary">
          + Add voice
        </Link>
      </div>

      <VoiceboxStatusBanner />

      {/* Pool summary pills — §7.3 targets shown as guidance (adjustment C). */}
      <ul className="grid grid-cols-3 gap-2">
        {POOLS.map((p) => {
          const n = counts.data?.[p] ?? 0;
          const t = POOL_TARGETS[p];
          const active = pool === p;
          return (
            <li key={p}>
              <button
                type="button"
                onClick={() => setPool(active ? null : p)}
                className={`card w-full px-3 py-2 text-left transition-colors
                            ${active ? "border-accent text-accent" : "hover:border-accent/40"}`}
              >
                <div className="text-[11px] uppercase tracking-wide text-muted">
                  {t.label}
                </div>
                <div className="text-2xl font-display leading-tight">{n}</div>
                <div className="text-[11px] text-muted">
                  target {t.min}–{t.max}
                </div>
              </button>
            </li>
          );
        })}
      </ul>

      {/* Filters */}
      <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto]">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name, accent, tone, archetype, tag…"
          className="input"
          aria-label="Search voices"
        />
        <select
          value={gender ?? ""}
          onChange={(e) => setGender((e.target.value || null) as Gender | null)}
          className="input sm:w-40"
          aria-label="Filter by gender"
        >
          <option value="">Any gender</option>
          <option value="male">Male</option>
          <option value="female">Female</option>
          <option value="nonbinary">Nonbinary</option>
          <option value="unknown">Unknown</option>
        </select>
        {!noFilters && (
          <button
            type="button"
            onClick={() => {
              setPool(null);
              setGender(null);
              setQ("");
            }}
            className="btn-ghost"
          >
            Clear
          </button>
        )}
      </div>

      {voices.isLoading && <p className="text-muted">Loading…</p>}
      {voices.isError && (
        <p className="text-error">
          Failed to load: {(voices.error as Error).message}
        </p>
      )}

      {empty && (
        <EmptyState />
      )}

      {voices.data && voices.data.length === 0 && !noFilters && (
        <div className="card p-6 text-center text-muted">
          No voices match these filters.
        </div>
      )}

      {voices.data && voices.data.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {voices.data.map((v) => (
            <VoiceCard
              key={v.id}
              voice={v}
              onDelete={() => {
                if (
                  window.confirm(
                    `Delete "${v.display_name}"? This removes the voice and its reference audio. Cannot be undone.`,
                  )
                ) {
                  deleteMut.mutate(v.id);
                }
              }}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function VoiceCard({ voice, onDelete }: { voice: Voice; onDelete: () => void }) {
  return (
    <li className="card p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-display text-lg leading-tight truncate">
            {voice.display_name}
          </div>
          <div className="text-xs text-muted">
            {[voice.gender, voice.age_range, voice.accent]
              .filter(Boolean)
              .join(" · ") || "—"}
          </div>
        </div>
        <PoolBadge pool={voice.pool} />
      </div>

      {voice.tone.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {voice.tone.slice(0, 4).map((t) => (
            <span key={t} className="chip text-[11px] text-muted">
              {t}
            </span>
          ))}
          {voice.tone.length > 4 && (
            <span className="text-[11px] text-muted self-center">
              +{voice.tone.length - 4}
            </span>
          )}
        </div>
      )}

      <div className="mt-auto flex items-center gap-2">
        {voice.has_sample_audio ? (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <audio
            controls
            preload="none"
            src={sampleAudioUrl(voice.id)}
            className="flex-1 min-w-0 h-9"
          />
        ) : (
          <span className="flex-1 text-xs text-muted italic">
            No reference audio uploaded
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 text-sm">
        <Link
          to={`/voices/${voice.id}/edit`}
          className="btn-surface flex-1 text-center"
        >
          Edit
        </Link>
        <button type="button" onClick={onDelete} className="btn-danger">
          Delete
        </button>
      </div>
    </li>
  );
}

function PoolBadge({ pool }: { pool: Pool }) {
  const map: Record<Pool, string> = {
    narrator: "bg-accent/15 text-accent border-accent/40",
    main: "bg-surface-2 text-fg border-border",
    background: "bg-surface-2 text-muted border-border",
  };
  return (
    <span
      className={`chip text-[10px] uppercase tracking-wider shrink-0 ${map[pool]}`}
    >
      {pool}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="card p-6 text-sm space-y-3">
      <div className="font-display text-xl">Start your voice library</div>
      <p className="text-muted">
        Chorus doesn't ship with pre-cloned voices — legally, it's a minefield.
        Record or upload your own.
      </p>
      <p className="text-muted">Suggested sources:</p>
      <ul className="list-disc pl-5 text-muted space-y-1">
        <li>Your own voice (tap the mic on your phone)</li>
        <li>
          <a
            href="https://librivox.org/"
            target="_blank"
            rel="noreferrer"
            className="text-accent underline"
          >
            LibriVox
          </a>{" "}
          public-domain audiobooks
        </li>
        <li>
          <a
            href="https://archive.org/details/oldtimeradio"
            target="_blank"
            rel="noreferrer"
            className="text-accent underline"
          >
            Internet Archive old-time radio
          </a>
        </li>
        <li>Consenting friends</li>
      </ul>
      <div className="pt-2">
        <Link to="/voices/new" className="btn-primary">
          Add your first voice
        </Link>
      </div>
    </div>
  );
}
