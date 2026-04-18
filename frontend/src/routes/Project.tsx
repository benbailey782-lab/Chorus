import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type IngestResult } from "../lib/api";

export default function Project() {
  const { idOrSlug = "" } = useParams();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [lastIngest, setLastIngest] = useState<IngestResult | null>(null);

  const project = useQuery({
    queryKey: ["project", idOrSlug],
    queryFn: () => api.getProject(idOrSlug),
    enabled: !!idOrSlug,
  });

  const chapters = useQuery({
    queryKey: ["project", idOrSlug, "chapters"],
    queryFn: () => api.listChapters(idOrSlug),
    enabled: !!idOrSlug,
  });

  const ingestMut = useMutation({
    mutationFn: (file: File) => api.ingest(idOrSlug, file),
    onSuccess: (res) => {
      setLastIngest(res);
      qc.invalidateQueries({ queryKey: ["project", idOrSlug] });
      qc.invalidateQueries({ queryKey: ["project", idOrSlug, "chapters"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const handlePick = () => fileRef.current?.click();
  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) ingestMut.mutate(file);
    e.target.value = "";
  };

  if (project.isLoading) return <p className="text-muted">Loading…</p>;
  if (project.isError)
    return (
      <p className="text-error">
        {(project.error as Error).message}{" "}
        <Link to="/" className="underline text-accent">
          Back
        </Link>
      </p>
    );
  if (!project.data) return null;

  const p = project.data;
  const needsIngest = (chapters.data?.length ?? 0) === 0;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-muted hover:text-fg">
          ← Library
        </Link>
        <h1 className="text-3xl mt-1">{p.title}</h1>
        {p.author && <div className="text-muted">{p.author}</div>}
        <div className="text-xs mt-1 text-muted">
          status: {p.status} · mode: {p.mode} · {p.chapter_count} chapters
        </div>
      </div>

      <section className="card p-4 space-y-3">
        <h2 className="text-xl">Source</h2>
        <p className="text-sm text-muted">
          Upload a .epub or .txt. Chorus will parse chapters automatically.
          Re-ingesting replaces the current chapter list.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".epub,.txt,.text"
          className="hidden"
          onChange={handleFile}
        />
        <button
          onClick={handlePick}
          disabled={ingestMut.isPending}
          className="btn-primary"
        >
          {ingestMut.isPending
            ? "Ingesting…"
            : needsIngest
              ? "Upload source"
              : "Replace source"}
        </button>
        {ingestMut.isError && (
          <p className="text-sm text-error">
            {(ingestMut.error as Error).message}
          </p>
        )}
        {lastIngest && (
          <div className="text-sm space-y-1">
            <div>
              Parsed{" "}
              <strong className="text-fg">{lastIngest.chapters_detected}</strong>{" "}
              chapters ({lastIngest.source_kind}).
            </div>
            {lastIngest.warnings.length > 0 && (
              <details className="text-muted">
                <summary className="cursor-pointer">
                  {lastIngest.warnings.length} warnings
                </summary>
                <ul className="list-disc pl-5 text-xs mt-1">
                  {lastIngest.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </section>

      <section className="card p-4">
        <h2 className="text-xl mb-3">Chapters</h2>
        {chapters.isLoading && <p className="text-muted">Loading…</p>}
        {chapters.data && chapters.data.length === 0 && (
          <p className="text-muted text-sm">
            No chapters yet. Upload a source file above.
          </p>
        )}
        {chapters.data && chapters.data.length > 0 && (
          <ol className="divide-y divide-border">
            {chapters.data.map((c) => (
              <li key={c.id} className="py-2 flex items-baseline gap-3">
                <span className="tabular-nums text-muted w-10 text-right">
                  {c.number}.
                </span>
                <span className="flex-1 truncate">{c.title || "Untitled"}</span>
                <span className="text-xs text-muted tabular-nums">
                  {c.word_count?.toLocaleString() ?? "—"} words
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
