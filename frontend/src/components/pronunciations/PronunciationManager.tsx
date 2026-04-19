import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../lib/toast";
import { CONFIDENCE } from "../../lib/constants";
import {
  api,
  type Pronunciation,
  type PronunciationCategory,
  type PronunciationCreate,
} from "../../lib/api";

export interface PronunciationManagerProps {
  scope: "global" | "project";
  projectIdOrSlug?: string; // required if scope === 'project'
}

const CATEGORIES: { value: PronunciationCategory | "all"; label: string }[] = [
  { value: "all", label: "All categories" },
  { value: "character_name", label: "Character name" },
  { value: "place", label: "Place" },
  { value: "proper_noun", label: "Proper noun" },
  { value: "phrase", label: "Phrase" },
  { value: "other", label: "Other" },
];

const SORT_KEYS = ["term", "phonetic", "category", "confidence", "source"] as const;
type SortKey = (typeof SORT_KEYS)[number];

export default function PronunciationManager({
  scope,
  projectIdOrSlug,
}: PronunciationManagerProps) {
  if (scope === "project" && !projectIdOrSlug) {
    throw new Error("PronunciationManager: scope='project' requires projectIdOrSlug");
  }

  const qc = useQueryClient();
  const { toast } = useToast();

  const listKey =
    scope === "global"
      ? ["pronunciations-global"]
      : ["pronunciations-project", projectIdOrSlug];

  const listQuery = useQuery({
    queryKey: listKey,
    queryFn: () =>
      scope === "global"
        ? api.listGlobalPronunciations()
        : api.listProjectPronunciations(projectIdOrSlug!),
  });

  const jobsQuery = useQuery({
    queryKey: ["project-jobs", projectIdOrSlug],
    queryFn: () => api.listProjectJobs(projectIdOrSlug!),
    enabled: scope === "project" && !!projectIdOrSlug,
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return 2000;
      return data.some(
        (j) =>
          j.kind === "pronounce_unusual" &&
          (j.status === "queued" || j.status === "awaiting_response" || j.status === "running"),
      )
        ? 2000
        : false;
    },
  });

  const extractJobActive = !!jobsQuery.data?.some(
    (j) =>
      j.kind === "pronounce_unusual" &&
      (j.status === "queued" || j.status === "awaiting_response" || j.status === "running"),
  );

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: listKey }).then(() => {
      if (scope === "project" && projectIdOrSlug) {
        qc.invalidateQueries({
          queryKey: ["pronunciations-merged", projectIdOrSlug],
        });
      }
    });

  const createMut = useMutation({
    mutationFn: (body: PronunciationCreate) =>
      scope === "global"
        ? api.createGlobalPronunciation(body)
        : api.createProjectPronunciation(projectIdOrSlug!, body),
    onSuccess: () => invalidate(),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: PronunciationCreate }) =>
      scope === "global"
        ? api.updateGlobalPronunciation(id, body)
        : api.updatePronunciation(id, body),
    onSuccess: () => invalidate(),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) =>
      scope === "global"
        ? api.deleteGlobalPronunciation(id)
        : api.deletePronunciation(id),
    onSuccess: () => invalidate(),
  });

  const promoteMut = useMutation({
    mutationFn: ({ id, deleteProjectEntry }: { id: string; deleteProjectEntry: boolean }) =>
      api.promotePronunciationToGlobal(id, { deleteProjectEntry }),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["pronunciations-global"] });
    },
  });

  const extractMut = useMutation({
    mutationFn: () => api.extractPronunciations(projectIdOrSlug!),
    onSuccess: (res) => {
      toast({
        kind: "success",
        message: `Pass-3 extraction queued (${res.book_text_chars.toLocaleString()} chars${
          res.truncated ? " — truncated" : ""
        }). Job ${res.job_id.slice(0, 8)}.`,
      });
      qc.invalidateQueries({ queryKey: ["project-jobs", projectIdOrSlug] });
    },
    onError: (e: Error) => toast({ kind: "error", message: e.message }),
  });

  // --- Toolbar state ----------------------------------------------------

  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<
    PronunciationCategory | "all"
  >("all");
  const [showIpa, setShowIpa] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("term");
  const [sortAsc, setSortAsc] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [newEntryOpen, setNewEntryOpen] = useState(false);

  // --- Derived list -----------------------------------------------------

  const filtered = useMemo(() => {
    const rows = listQuery.data ?? [];
    const q = search.trim().toLowerCase();
    const cat = categoryFilter;
    return rows
      .filter((r) => {
        if (cat !== "all" && r.category !== cat) return false;
        if (!q) return true;
        return (
          r.term.toLowerCase().includes(q) ||
          r.phonetic.toLowerCase().includes(q) ||
          (r.ipa ?? "").toLowerCase().includes(q) ||
          (r.notes ?? "").toLowerCase().includes(q)
        );
      })
      .slice()
      .sort((a, b) => {
        const av = pickSortVal(a, sortKey);
        const bv = pickSortVal(b, sortKey);
        if (av === bv) return 0;
        if (av === null || av === undefined) return 1;
        if (bv === null || bv === undefined) return -1;
        if (av < bv) return sortAsc ? -1 : 1;
        return sortAsc ? 1 : -1;
      });
  }, [listQuery.data, search, categoryFilter, sortKey, sortAsc]);

  useEffect(() => {
    // Drop selection ids that no longer exist.
    if (!listQuery.data) return;
    const existing = new Set(listQuery.data.map((r) => r.id));
    let changed = false;
    const next = new Set<string>();
    for (const id of selected) {
      if (existing.has(id)) next.add(id);
      else changed = true;
    }
    if (changed) setSelected(next);
  }, [listQuery.data, selected]);

  // --- Handlers ---------------------------------------------------------

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortAsc((v) => !v);
    else {
      setSortKey(k);
      setSortAsc(true);
    }
  };

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllVisible = (checked: boolean) => {
    if (!checked) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(filtered.map((r) => r.id)));
  };

  const handleImport = async (file: File) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch (e) {
      toast({ kind: "error", message: `Import: invalid JSON — ${(e as Error).message}` });
      return;
    }
    if (!Array.isArray(parsed)) {
      toast({
        kind: "error",
        message: "Import: expected a JSON array of pronunciation entries",
      });
      return;
    }
    let ok = 0;
    let fail = 0;
    for (const raw of parsed) {
      if (!raw || typeof raw !== "object") {
        fail++;
        continue;
      }
      const r = raw as Record<string, unknown>;
      const term = typeof r.term === "string" ? r.term : null;
      const phonetic = typeof r.phonetic === "string" ? r.phonetic : null;
      if (!term || !phonetic) {
        fail++;
        continue;
      }
      try {
        await createMut.mutateAsync({
          term,
          phonetic,
          ipa: typeof r.ipa === "string" ? r.ipa : null,
          confidence: typeof r.confidence === "number" ? r.confidence : null,
          category: (typeof r.category === "string" ? (r.category as PronunciationCategory) : null),
          notes: typeof r.notes === "string" ? r.notes : null,
          source: typeof r.source === "string" ? r.source : "import",
        });
        ok++;
      } catch {
        fail++;
      }
    }
    toast({
      kind: fail === 0 ? "success" : "info",
      message: `Import complete: ${ok} added, ${fail} skipped or failed.`,
    });
  };

  const handleExport = () => {
    const rows = listQuery.data ?? [];
    const exportRows = rows.map(
      ({ created_at, updated_at, project_id, id, ...rest }) => rest,
    );
    const blob = new Blob([JSON.stringify(exportRows, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const date = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `pronunciations-${scope}-${date}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const deleteSelected = async () => {
    if (selected.size === 0) return;
    if (!window.confirm(`Delete ${selected.size} pronunciation${selected.size === 1 ? "" : "s"}?`))
      return;
    let ok = 0;
    for (const id of selected) {
      try {
        await deleteMut.mutateAsync(id);
        ok++;
      } catch {
        /* ignore — loop continues */
      }
    }
    toast({ kind: "success", message: `Deleted ${ok} entr${ok === 1 ? "y" : "ies"}.` });
    setSelected(new Set());
  };

  const promoteSelected = async () => {
    if (scope !== "project" || selected.size === 0) return;
    let ok = 0;
    for (const id of selected) {
      try {
        await promoteMut.mutateAsync({ id, deleteProjectEntry: true });
        ok++;
      } catch {
        /* swallow */
      }
    }
    toast({
      kind: "success",
      message: `Promoted ${ok} entr${ok === 1 ? "y" : "ies"} to global.`,
    });
    setSelected(new Set());
  };

  // --- Render -----------------------------------------------------------

  return (
    <div className="space-y-3">
      <Toolbar
        scope={scope}
        search={search}
        setSearch={setSearch}
        categoryFilter={categoryFilter}
        setCategoryFilter={setCategoryFilter}
        showIpa={showIpa}
        setShowIpa={setShowIpa}
        onNew={() => setNewEntryOpen(true)}
        onImport={handleImport}
        onExport={handleExport}
        onExtract={scope === "project" ? () => extractMut.mutate() : undefined}
        extracting={extractMut.isPending || extractJobActive}
      />

      {selected.size > 0 && (
        <div className="card p-2 flex flex-wrap items-center gap-2 text-sm">
          <span>
            {selected.size} selected
          </span>
          <button
            type="button"
            className="btn-danger text-xs"
            onClick={deleteSelected}
          >
            Delete selected
          </button>
          {scope === "project" && (
            <button
              type="button"
              className="btn-surface text-xs"
              onClick={promoteSelected}
            >
              Promote to global
            </button>
          )}
          <button
            type="button"
            className="btn-ghost text-xs"
            onClick={() => setSelected(new Set())}
          >
            Clear
          </button>
        </div>
      )}

      {listQuery.isLoading && <p className="text-muted">Loading…</p>}
      {listQuery.isError && (
        <p className="text-error">
          Failed to load: {(listQuery.error as Error).message}
        </p>
      )}

      {listQuery.data && listQuery.data.length === 0 && (
        <div className="card p-6 text-sm text-muted text-center">
          No pronunciations yet.
          {scope === "project" && (
            <>
              {" "}Click <span className="text-fg">Extract from book</span> to run
              Pass 3, or add entries manually.
            </>
          )}
        </div>
      )}

      {listQuery.data && listQuery.data.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-muted text-xs uppercase tracking-wider">
              <tr>
                <th className="p-2 w-8">
                  <input
                    type="checkbox"
                    aria-label="Select all visible"
                    checked={
                      filtered.length > 0 &&
                      filtered.every((r) => selected.has(r.id))
                    }
                    onChange={(e) => selectAllVisible(e.target.checked)}
                  />
                </th>
                <Th label="Term" k="term" sortKey={sortKey} asc={sortAsc} onClick={toggleSort} />
                <Th label="Phonetic" k="phonetic" sortKey={sortKey} asc={sortAsc} onClick={toggleSort} />
                {showIpa && <th className="p-2 text-left">IPA</th>}
                <Th label="Category" k="category" sortKey={sortKey} asc={sortAsc} onClick={toggleSort} />
                <Th label="Conf" k="confidence" sortKey={sortKey} asc={sortAsc} onClick={toggleSort} />
                <Th label="Source" k="source" sortKey={sortKey} asc={sortAsc} onClick={toggleSort} />
                <th className="p-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) =>
                editingId === row.id ? (
                  <EditableRow
                    key={row.id}
                    row={row}
                    showIpa={showIpa}
                    scope={scope}
                    onCancel={() => setEditingId(null)}
                    onSave={async (body) => {
                      await updateMut.mutateAsync({ id: row.id, body });
                      setEditingId(null);
                    }}
                  />
                ) : (
                  <ReadRow
                    key={row.id}
                    row={row}
                    scope={scope}
                    showIpa={showIpa}
                    selected={selected.has(row.id)}
                    onToggle={() => toggleSelected(row.id)}
                    onEdit={() => setEditingId(row.id)}
                    onDelete={() => {
                      if (window.confirm(`Delete "${row.term}"?`)) {
                        deleteMut.mutate(row.id);
                      }
                    }}
                    onPromote={
                      scope === "project"
                        ? () =>
                            promoteMut.mutate({
                              id: row.id,
                              deleteProjectEntry: true,
                            })
                        : undefined
                    }
                  />
                ),
              )}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={showIpa ? 8 : 7} className="p-4 text-center text-muted">
                    No entries match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {newEntryOpen && (
        <NewEntryModal
          scope={scope}
          pending={createMut.isPending}
          error={(createMut.error as Error | null)?.message ?? null}
          onClose={() => {
            setNewEntryOpen(false);
            createMut.reset();
          }}
          onSubmit={async (body) => {
            await createMut.mutateAsync(body);
            toast({
              kind: "success",
              message: `Added pronunciation for "${body.term}".`,
            });
            setNewEntryOpen(false);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toolbar
// ---------------------------------------------------------------------------

function Toolbar({
  scope,
  search,
  setSearch,
  categoryFilter,
  setCategoryFilter,
  showIpa,
  setShowIpa,
  onNew,
  onImport,
  onExport,
  onExtract,
  extracting,
}: {
  scope: "global" | "project";
  search: string;
  setSearch: (v: string) => void;
  categoryFilter: PronunciationCategory | "all";
  setCategoryFilter: (v: PronunciationCategory | "all") => void;
  showIpa: boolean;
  setShowIpa: (v: boolean) => void;
  onNew: () => void;
  onImport: (file: File) => void | Promise<void>;
  onExport: () => void;
  onExtract?: () => void;
  extracting?: boolean;
}) {
  const importRef = useRef<HTMLInputElement>(null);
  return (
    <div className="sticky top-0 z-10 bg-bg/90 backdrop-blur pb-2 -mx-1 px-1">
      <div className="card p-2 flex flex-wrap items-center gap-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search term, phonetic, notes…"
          className="input flex-1 min-w-[10rem]"
          aria-label="Search pronunciations"
        />
        <select
          value={categoryFilter}
          onChange={(e) =>
            setCategoryFilter(e.target.value as PronunciationCategory | "all")
          }
          className="input w-40"
          aria-label="Filter by category"
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <label className="text-xs flex items-center gap-1 text-muted">
          <input
            type="checkbox"
            checked={showIpa}
            onChange={(e) => setShowIpa(e.target.checked)}
          />
          Show IPA
        </label>
        <button type="button" className="btn-primary text-sm" onClick={onNew}>
          + New entry
        </button>
        <input
          ref={importRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onImport(f);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="btn-surface text-sm"
          onClick={() => importRef.current?.click()}
        >
          Import JSON
        </button>
        <button type="button" className="btn-surface text-sm" onClick={onExport}>
          Export JSON
        </button>
        {scope === "project" && onExtract && (
          <button
            type="button"
            className="btn-surface text-sm"
            onClick={onExtract}
            disabled={extracting}
          >
            {extracting ? "Extracting…" : "Extract from book"}
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

function Th({
  label,
  k,
  sortKey,
  asc,
  onClick,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  asc: boolean;
  onClick: (k: SortKey) => void;
}) {
  const active = k === sortKey;
  return (
    <th
      className="p-2 text-left cursor-pointer select-none whitespace-nowrap"
      onClick={() => onClick(k)}
    >
      {label}
      <span className="ml-1 text-[10px] text-muted">
        {active ? (asc ? "▲" : "▼") : ""}
      </span>
    </th>
  );
}

function ReadRow({
  row,
  scope,
  showIpa,
  selected,
  onToggle,
  onEdit,
  onDelete,
  onPromote,
}: {
  row: Pronunciation;
  scope: "global" | "project";
  showIpa: boolean;
  selected: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onPromote?: () => void;
}) {
  const bg = CONFIDENCE.hexFor(row.confidence ?? null);
  return (
    <tr className="border-t border-border hover:bg-surface-2/40">
      <td className="p-2">
        <input
          type="checkbox"
          aria-label={`Select ${row.term}`}
          checked={selected}
          onChange={onToggle}
        />
      </td>
      <td className="p-2 font-medium">{row.term}</td>
      <td className="p-2 font-mono text-xs">{row.phonetic}</td>
      {showIpa && (
        <td className="p-2 font-mono text-xs text-muted">
          {row.ipa ?? "—"}
        </td>
      )}
      <td className="p-2 text-xs text-muted">{row.category ?? "—"}</td>
      <td className="p-2">
        {row.confidence !== null && row.confidence !== undefined ? (
          <span
            className="chip text-[10px]"
            style={{
              backgroundColor: `${bg}20`,
              borderColor: `${bg}60`,
              color: bg,
            }}
          >
            {Math.round(row.confidence)}
          </span>
        ) : (
          <span className="text-muted text-xs">—</span>
        )}
      </td>
      <td className="p-2 text-xs text-muted">{row.source ?? "manual"}</td>
      <td className="p-2 text-right whitespace-nowrap">
        <button
          type="button"
          onClick={onEdit}
          className="btn-ghost text-xs px-2 py-1"
        >
          Edit
        </button>
        {scope === "project" && onPromote && (
          <button
            type="button"
            onClick={onPromote}
            className="btn-ghost text-xs px-2 py-1"
            title="Copy to the global library (removes project override by default)"
          >
            Promote
          </button>
        )}
        <button
          type="button"
          onClick={onDelete}
          className="btn-ghost text-xs px-2 py-1 text-error"
        >
          Delete
        </button>
      </td>
    </tr>
  );
}

function EditableRow({
  row,
  showIpa,
  scope,
  onCancel,
  onSave,
}: {
  row: Pronunciation;
  showIpa: boolean;
  scope: "global" | "project";
  onCancel: () => void;
  onSave: (body: PronunciationCreate) => Promise<void>;
}) {
  const [term, setTerm] = useState(row.term);
  const [phonetic, setPhonetic] = useState(row.phonetic);
  const [ipa, setIpa] = useState(row.ipa ?? "");
  const [category, setCategory] = useState<PronunciationCategory | "">(
    row.category ?? "",
  );
  const [confidence, setConfidence] = useState<string>(
    row.confidence != null ? String(row.confidence) : "",
  );
  const [notes, setNotes] = useState(row.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    if (!term.trim() || !phonetic.trim()) {
      setErr("term and phonetic are required");
      return;
    }
    setBusy(true);
    try {
      await onSave({
        term: term.trim(),
        phonetic: phonetic.trim(),
        ipa: ipa.trim() || null,
        category: (category || null) as PronunciationCategory | null,
        confidence: confidence.trim() ? Number(confidence) : null,
        notes: notes.trim() || null,
      });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cols = showIpa ? 8 : 7;
  return (
    <>
      <tr className="border-t border-border bg-surface-2/30">
        <td className="p-2"></td>
        <td className="p-2">
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            className="input w-full"
            aria-label="Term"
          />
        </td>
        <td className="p-2">
          <input
            value={phonetic}
            onChange={(e) => setPhonetic(e.target.value)}
            className="input w-full font-mono text-xs"
            aria-label="Phonetic respelling"
          />
        </td>
        {showIpa && (
          <td className="p-2">
            <input
              value={ipa}
              onChange={(e) => setIpa(e.target.value)}
              className="input w-full font-mono text-xs"
              aria-label="IPA"
            />
          </td>
        )}
        <td className="p-2">
          <select
            value={category}
            onChange={(e) =>
              setCategory(e.target.value as PronunciationCategory | "")
            }
            className="input w-full text-xs"
          >
            <option value="">—</option>
            {CATEGORIES.filter((c) => c.value !== "all").map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </td>
        <td className="p-2">
          <input
            value={confidence}
            onChange={(e) => setConfidence(e.target.value)}
            className="input w-16 text-xs"
            inputMode="numeric"
            aria-label="Confidence 0-100"
            placeholder="0-100"
          />
        </td>
        <td className="p-2 text-xs text-muted">{row.source ?? "manual"}</td>
        <td className="p-2 text-right whitespace-nowrap">
          <button
            type="button"
            className="btn-primary text-xs px-2 py-1"
            disabled={busy}
            onClick={submit}
          >
            {busy ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            className="btn-ghost text-xs px-2 py-1"
            onClick={onCancel}
          >
            Cancel
          </button>
        </td>
      </tr>
      <tr className="border-t-0 bg-surface-2/30">
        <td className="p-2"></td>
        <td className="p-2" colSpan={cols - 1}>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="input w-full text-xs"
            placeholder={
              scope === "project"
                ? "Notes (rationale, alternatives, scope…)"
                : "Notes"
            }
            rows={2}
          />
          {err && <div className="text-xs text-error mt-1">{err}</div>}
        </td>
      </tr>
    </>
  );
}

// ---------------------------------------------------------------------------
// New entry modal
// ---------------------------------------------------------------------------

function NewEntryModal({
  scope,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  scope: "global" | "project";
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (body: PronunciationCreate) => Promise<void>;
}) {
  const [term, setTerm] = useState("");
  const [phonetic, setPhonetic] = useState("");
  const [ipa, setIpa] = useState("");
  const [category, setCategory] = useState<PronunciationCategory | "">("");
  const [confidence, setConfidence] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalErr(null);
    if (!term.trim() || !phonetic.trim()) {
      setLocalErr("term and phonetic are required");
      return;
    }
    try {
      await onSubmit({
        term: term.trim(),
        phonetic: phonetic.trim(),
        ipa: ipa.trim() || null,
        category: (category || null) as PronunciationCategory | null,
        confidence: confidence.trim() ? Number(confidence) : null,
        notes: notes.trim() || null,
        source: "manual",
      });
    } catch (err) {
      setLocalErr((err as Error).message);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-30 bg-bg/80 backdrop-blur flex items-center justify-center px-4 py-6"
      onClick={onClose}
    >
      <form
        className="card max-w-lg w-full p-5 space-y-3"
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
      >
        <div className="flex items-baseline justify-between">
          <h2 className="font-display text-xl">
            New {scope === "global" ? "global" : "project"} pronunciation
          </h2>
          <button
            type="button"
            className="text-muted hover:text-fg text-xl leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <label className="block text-xs space-y-1">
          <span className="text-muted">Term</span>
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            className="input w-full"
            autoFocus
          />
        </label>
        <label className="block text-xs space-y-1">
          <span className="text-muted">Phonetic respelling</span>
          <input
            value={phonetic}
            onChange={(e) => setPhonetic(e.target.value)}
            className="input w-full font-mono"
            placeholder="e.g., duh-NAIR-iss"
          />
        </label>
        <label className="block text-xs space-y-1">
          <span className="text-muted">IPA (optional)</span>
          <input
            value={ipa}
            onChange={(e) => setIpa(e.target.value)}
            className="input w-full font-mono"
          />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs space-y-1">
            <span className="text-muted">Category</span>
            <select
              value={category}
              onChange={(e) =>
                setCategory(e.target.value as PronunciationCategory | "")
              }
              className="input w-full"
            >
              <option value="">—</option>
              {CATEGORIES.filter((c) => c.value !== "all").map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-muted">Confidence (0-100)</span>
            <input
              value={confidence}
              onChange={(e) => setConfidence(e.target.value)}
              className="input w-full"
              inputMode="numeric"
            />
          </label>
        </div>
        <label className="block text-xs space-y-1">
          <span className="text-muted">Notes</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="input w-full text-sm"
            rows={3}
          />
        </label>
        {(localErr || error) && (
          <div className="text-xs text-error">{localErr ?? error}</div>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            className="btn-ghost"
            onClick={onClose}
            disabled={pending}
          >
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={pending}>
            {pending ? "Saving…" : "Add"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sort helper
// ---------------------------------------------------------------------------

function pickSortVal(r: Pronunciation, k: SortKey): string | number | null {
  switch (k) {
    case "term":
      return r.term.toLowerCase();
    case "phonetic":
      return r.phonetic.toLowerCase();
    case "category":
      return r.category ?? "";
    case "confidence":
      return r.confidence ?? null;
    case "source":
      return (r.source ?? "").toLowerCase();
  }
}
