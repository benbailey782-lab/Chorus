import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Field, FieldRow } from "../components/Field";
import Select from "../components/Select";
import TagInput from "../components/TagInput";
import VoiceboxStatusBanner from "../components/VoiceboxStatusBanner";
import {
  VOICEBOX_ENGINES,
  api,
  sampleAudioUrl,
  type Voice,
  type VoiceCreate,
  type VoiceboxEngine,
} from "../lib/api";
import {
  AGE_RANGES,
  AUDIO_ACCEPT,
  ENGINE_PREFERENCES,
  GENDERS,
  PACES,
  POOLS,
  REGISTERS,
  TIMBRES,
  type AgeRange,
  type EnginePreference,
  type Gender,
  type Pace,
  type Pool,
  type Register,
  type Timbre,
} from "../lib/constants";

// Suggested tag lists — these mirror the voice library examples in the
// few-shot prompts so the UI nudges toward the same vocabulary the LLM uses.
const TONE_SUGGESTIONS = [
  "gravelly", "measured", "stern", "silky", "wry", "earnest", "cold",
  "warm", "weathered", "rough", "gruff", "direct", "commanding", "clipped",
  "soft", "curious", "fierce", "quick", "bright", "serene", "weighty",
];
const ARCHETYPE_SUGGESTIONS = [
  "hero", "mentor", "warrior", "aristocrat", "rogue", "villain", "tragic",
  "innocent", "child", "mystic", "everyman", "specialized",
];
const TAG_SUGGESTIONS = [
  "mature", "authoritative", "narrator", "literary", "british", "american",
  "northern", "classic", "young", "old",
];

const DEFAULT_FORM: VoiceCreate = {
  display_name: "",
  pool: "main",
  tone: [],
  character_archetypes: [],
  tags: [],
  // Phase-5R: default engine on create. Editing hydrates from the voice row.
  voicebox_engine: "qwen3-tts",
};

export default function VoiceEditor() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { id } = useParams();
  const isNew = !id;

  const existing = useQuery({
    queryKey: ["voice", id],
    queryFn: () => api.getVoice(id!),
    enabled: !!id,
  });

  const [form, setForm] = useState<VoiceCreate>(DEFAULT_FORM);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Phase-5R: non-fatal Voicebox sync error from the last save. The voice
   *  is still persisted; we show this as a warning banner so the user can
   *  retry the sync later from the library. */
  const [syncWarning, setSyncWarning] = useState<string | null>(null);
  const loadedRef = useRef(false);

  // Hydrate the form once the existing voice lands.
  useEffect(() => {
    if (isNew || !existing.data || loadedRef.current) return;
    loadedRef.current = true;
    const v = existing.data;
    setForm({
      display_name: v.display_name,
      gender: v.gender,
      age_range: v.age_range,
      accent: v.accent ?? "",
      tone: v.tone,
      timbre: v.timbre,
      pace: v.pace,
      register: v.register,
      character_archetypes: v.character_archetypes,
      pool: v.pool,
      engine_preference: v.engine_preference,
      sample_text: v.sample_text ?? "",
      source_notes: v.source_notes ?? "",
      tags: v.tags,
      voicebox_engine: v.voicebox_engine,
      voicebox_effect_preset_id: v.voicebox_effect_preset_id,
    });
  }, [isNew, existing.data]);

  const patch = <K extends keyof VoiceCreate>(key: K, v: VoiceCreate[K]) =>
    setForm((prev) => ({ ...prev, [key]: v }));

  const createMut = useMutation({
    mutationFn: async () => {
      const body: VoiceCreate = {
        ...form,
        accent: nullIfEmpty(form.accent),
        sample_text: nullIfEmpty(form.sample_text),
        source_notes: nullIfEmpty(form.source_notes),
      };
      return api.createVoice(body, file);
    },
    onSuccess: (resp) => {
      qc.invalidateQueries({ queryKey: ["voices"] });
      qc.invalidateQueries({ queryKey: ["voice-pool-counts"] });
      if (resp.voicebox_sync_error) {
        // Voice was saved — sync failed. Surface the warning + navigate
        // away (library card will show "Needs sync" so the user can retry).
        setSyncWarning(resp.voicebox_sync_error);
        window.setTimeout(() => navigate("/voices"), 2200);
      } else {
        navigate("/voices");
      }
    },
    onError: (e: Error) => setError(e.message),
  });

  const updateMut = useMutation({
    mutationFn: async () => {
      const body = {
        ...form,
        accent: nullIfEmpty(form.accent),
        sample_text: nullIfEmpty(form.sample_text),
        source_notes: nullIfEmpty(form.source_notes),
      };
      const voice = await api.updateVoice(id!, body);
      if (file) await api.replaceVoiceSample(id!, file);
      return voice;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["voices"] });
      qc.invalidateQueries({ queryKey: ["voice-pool-counts"] });
      qc.invalidateQueries({ queryKey: ["voice", id] });
      navigate("/voices");
    },
    onError: (e: Error) => setError(e.message),
  });

  const deleteSampleMut = useMutation({
    mutationFn: () => api.deleteVoiceSample(id!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["voice", id] }),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!form.display_name.trim()) {
      setError("Display name is required.");
      return;
    }
    (isNew ? createMut : updateMut).mutate();
  };

  const pending = createMut.isPending || updateMut.isPending;

  if (!isNew && existing.isLoading) {
    return <p className="text-muted">Loading…</p>;
  }
  if (!isNew && existing.isError) {
    return (
      <p className="text-error">
        {(existing.error as Error).message}{" "}
        <Link to="/voices" className="text-accent underline">
          Back
        </Link>
      </p>
    );
  }

  const currentSample = !isNew && existing.data?.has_sample_audio
    ? (existing.data as Voice)
    : null;

  return (
    <form onSubmit={handleSubmit} className="space-y-5 pb-24">
      <div>
        <Link to="/voices" className="text-sm text-muted hover:text-fg">
          ← Voices
        </Link>
        <h1 className="text-3xl mt-1">
          {isNew ? "New voice" : form.display_name || "Voice"}
        </h1>
      </div>

      <VoiceboxStatusBanner />

      {/* Identity ----------------------------------------------------- */}
      <section className="card p-4 space-y-3">
        <h2 className="text-lg font-display">Identity</h2>
        <Field label="Display name" required>
          <input
            value={form.display_name}
            onChange={(e) => patch("display_name", e.target.value)}
            placeholder="Grizzled Northern Lord"
            className="input"
            maxLength={200}
            required
          />
        </Field>
        <Field
          label="Pool"
          required
          hint="Narrator = reader. Main = named characters. Background = one-line bits."
        >
          <Select<Pool>
            value={form.pool}
            onChange={(v) => patch("pool", v ?? "main")}
            options={POOLS}
          />
        </Field>
        <FieldRow>
          <Field label="Gender">
            <Select<Gender>
              value={form.gender ?? null}
              onChange={(v) => patch("gender", v)}
              options={GENDERS}
              placeholder="—"
            />
          </Field>
          <Field label="Age range">
            <Select<AgeRange>
              value={form.age_range ?? null}
              onChange={(v) => patch("age_range", v)}
              options={AGE_RANGES}
              placeholder="—"
            />
          </Field>
        </FieldRow>
        <Field label="Accent" hint="Free-form, e.g., neutral_northern_english, scottish_highland.">
          <input
            value={form.accent ?? ""}
            onChange={(e) => patch("accent", e.target.value)}
            placeholder="neutral_american"
            className="input"
          />
        </Field>
      </section>

      {/* Voice character --------------------------------------------- */}
      <section className="card p-4 space-y-3">
        <h2 className="text-lg font-display">Voice character</h2>
        <FieldRow>
          <Field label="Timbre">
            <Select<Timbre>
              value={form.timbre ?? null}
              onChange={(v) => patch("timbre", v)}
              options={TIMBRES}
              placeholder="—"
            />
          </Field>
          <Field label="Pace">
            <Select<Pace>
              value={form.pace ?? null}
              onChange={(v) => patch("pace", v)}
              options={PACES}
              placeholder="—"
            />
          </Field>
        </FieldRow>
        <Field label="Register" hint="Formal, casual, rough, warm, etc.">
          <Select<Register>
            value={form.register ?? null}
            onChange={(v) => patch("register", v)}
            options={REGISTERS}
            placeholder="—"
          />
        </Field>
        <Field label="Tone" hint="Descriptors like gravelly, warm, measured. Enter or comma to add.">
          <TagInput
            value={form.tone ?? []}
            onChange={(v) => patch("tone", v)}
            placeholder="gravelly, measured, stern"
            suggestions={TONE_SUGGESTIONS}
          />
        </Field>
        <Field
          label="Character archetypes"
          hint="Used by auto-casting to match characters. e.g., mentor, warrior, aristocrat."
        >
          <TagInput
            value={form.character_archetypes ?? []}
            onChange={(v) => patch("character_archetypes", v)}
            placeholder="mentor, warrior"
            suggestions={ARCHETYPE_SUGGESTIONS}
          />
        </Field>
        <Field label="Tags" hint="Free-form searchable labels.">
          <TagInput
            value={form.tags ?? []}
            onChange={(v) => patch("tags", v)}
            placeholder="mature, authoritative"
            suggestions={TAG_SUGGESTIONS}
          />
        </Field>
      </section>

      {/* TTS + provenance -------------------------------------------- */}
      <section className="card p-4 space-y-3">
        <h2 className="text-lg font-display">TTS + provenance</h2>
        <Field label="Engine" required>
          <select
            value={form.voicebox_engine ?? "qwen3-tts"}
            onChange={(e) =>
              patch("voicebox_engine", e.target.value as VoiceboxEngine)
            }
            className="input"
          >
            {VOICEBOX_ENGINES.map((e) => (
              <option key={e.id} value={e.id}>
                {e.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted mt-1">
            {
              VOICEBOX_ENGINES.find((e) => e.id === form.voicebox_engine)
                ?.description
            }
          </p>
          <p className="text-xs text-muted mt-1">
            Engine choice can be changed later but requires regeneration of
            any existing audio.
          </p>
        </Field>
        <Field label="Engine preference (legacy)" hint="Kept for Phase 2/3 data. The Engine field above is the authoritative per-voice TTS engine.">
          <Select<EnginePreference>
            value={form.engine_preference ?? null}
            onChange={(v) => patch("engine_preference", v)}
            options={ENGINE_PREFERENCES}
            placeholder="—"
          />
        </Field>
        <Field
          label="Sample text"
          hint="A short line used for previews. e.g., “Winter is coming.”"
        >
          <input
            value={form.sample_text ?? ""}
            onChange={(e) => patch("sample_text", e.target.value)}
            placeholder="Winter is coming."
            className="input"
          />
        </Field>
        <Field
          label="Source notes"
          hint="Where this voice came from. Keep a record in case of takedowns or provenance questions."
        >
          <textarea
            value={form.source_notes ?? ""}
            onChange={(e) => patch("source_notes", e.target.value)}
            placeholder="Cloned from public-domain BBC archive recording, 1952"
            className="input min-h-[72px] py-2"
            rows={3}
          />
        </Field>
      </section>

      {/* Reference audio --------------------------------------------- */}
      <section className="card p-4 space-y-3">
        <h2 className="text-lg font-display">Reference audio</h2>
        <p className="text-xs text-muted">
          Optional. Upload a clean recording (single speaker, 10–60s). Up to 25 MB.
          Accepts WAV, MP3, M4A, FLAC, OGG.
        </p>
        {currentSample && !file && (
          <div className="space-y-2">
            <div className="text-xs text-muted">Current sample</div>
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <audio
              controls
              preload="none"
              src={sampleAudioUrl(currentSample.id)}
              className="w-full"
            />
            <button
              type="button"
              className="btn-danger"
              onClick={() => {
                if (window.confirm("Remove the reference audio for this voice?")) {
                  deleteSampleMut.mutate();
                }
              }}
            >
              Remove reference audio
            </button>
          </div>
        )}
        <input
          type="file"
          accept={AUDIO_ACCEPT}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-muted file:mr-3 file:btn-surface file:border-0 file:cursor-pointer"
        />
        {file && (
          <div className="text-xs text-muted">
            Selected: {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
          </div>
        )}
      </section>

      {error && (
        <div className="card border-error/40 bg-error/10 text-error px-3 py-2 text-sm">
          {error}
        </div>
      )}

      {syncWarning && (
        <div className="card border-warn/40 bg-warn/10 text-warn px-3 py-2 text-sm">
          Voice saved but Voicebox sync failed: {syncWarning}. You can sync
          later from the library.
        </div>
      )}

      {/* Fixed submit bar sits above the bottom nav on mobile. */}
      <div className="fixed left-0 right-0 z-10 bg-bg/95 backdrop-blur border-t border-border px-4 py-3
                      bottom-[calc(4rem+env(safe-area-inset-bottom,0px))]
                      md:static md:border-t-0 md:bg-transparent md:backdrop-blur-0 md:p-0">
        <div className="max-w-5xl mx-auto flex items-center justify-end gap-2">
          <Link to="/voices" className="btn-ghost">Cancel</Link>
          <button
            type="submit"
            disabled={pending || !form.display_name.trim()}
            className="btn-primary"
          >
            {pending ? "Saving…" : isNew ? "Create voice" : "Save changes"}
          </button>
        </div>
      </div>
    </form>
  );
}

function nullIfEmpty(v: string | null | undefined): string | null {
  if (v === undefined || v === null) return null;
  const trimmed = String(v).trim();
  return trimmed === "" ? null : trimmed;
}
