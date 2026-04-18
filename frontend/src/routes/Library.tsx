import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Project } from "../lib/api";

function StatusPill({ status }: { status: Project["status"] }) {
  const label = status.replace(/_/g, " ");
  return (
    <span className="chip uppercase tracking-wide text-[10px] text-muted">
      {label}
    </span>
  );
}

export default function Library() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
  });

  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [showForm, setShowForm] = useState(false);

  const createMut = useMutation({
    mutationFn: api.createProject,
    onSuccess: (proj) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      setTitle("");
      setAuthor("");
      setShowForm(false);
      navigate(`/project/${proj.slug}`);
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    createMut.mutate({ title: title.trim(), author: author.trim() || null });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-3xl">Library</h1>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className={showForm ? "btn-surface" : "btn-primary"}
        >
          {showForm ? "Cancel" : "New project"}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="card p-4 space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">
            <label className="text-sm">
              <span className="block text-muted mb-1">Title</span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="A Game of Thrones"
                className="input"
                autoFocus
              />
            </label>
            <label className="text-sm">
              <span className="block text-muted mb-1">Author</span>
              <input
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                placeholder="George R. R. Martin"
                className="input"
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            <button
              type="submit"
              disabled={!title.trim() || createMut.isPending}
              className="btn-primary"
            >
              {createMut.isPending ? "Creating…" : "Create project"}
            </button>
            {createMut.isError && (
              <span className="text-sm text-error">
                {(createMut.error as Error).message}
              </span>
            )}
          </div>
        </form>
      )}

      {projects.isLoading && <p className="text-muted">Loading…</p>}
      {projects.isError && (
        <p className="text-error">
          Failed to load: {(projects.error as Error).message}
        </p>
      )}

      {projects.data && projects.data.length === 0 && !showForm && (
        <div className="card p-8 text-center text-muted border-dashed">
          No projects yet. Tap <strong className="text-fg">New project</strong> to start.
        </div>
      )}

      {projects.data && projects.data.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.data.map((p) => (
            <li key={p.id}>
              <Link
                to={`/project/${p.slug}`}
                className="card p-4 block hover:border-accent/60 transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-display text-lg leading-tight truncate">
                      {p.title}
                    </div>
                    {p.author && (
                      <div className="text-sm text-muted truncate">{p.author}</div>
                    )}
                  </div>
                  <StatusPill status={p.status} />
                </div>
                <div className="mt-3 text-xs text-muted">
                  {p.chapter_count > 0
                    ? `${p.chapter_count} chapters`
                    : "not yet ingested"}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
