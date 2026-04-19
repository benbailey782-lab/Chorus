import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import type { VoiceboxTestConnectionResponse } from "../lib/api";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok"; result: VoiceboxTestConnectionResponse }
  | { kind: "fail"; error: string };

export default function Settings() {
  const qc = useQueryClient();
  const { toast } = useToast();

  // Canonical health query — the same one Chapter Review etc. use, so the
  // chip in the corner of the Voicebox section reflects live state.
  const vbHealth = useQuery({
    queryKey: ["voicebox-health"],
    queryFn: api.voiceboxHealth,
    staleTime: 30_000,
  });

  // URL input state. Seeded from the health query once it lands; if the
  // user has already typed something we don't clobber it.
  const [urlInput, setUrlInput] = useState<string>("");
  const [enabledToggle, setEnabledToggle] = useState<boolean>(false);
  const [seeded, setSeeded] = useState<boolean>(false);
  const [testState, setTestState] = useState<TestState>({ kind: "idle" });

  useEffect(() => {
    if (seeded) return;
    if (!vbHealth.data) return;
    setUrlInput(vbHealth.data.base_url ?? "");
    setEnabledToggle(!!vbHealth.data.enabled);
    setSeeded(true);
  }, [vbHealth.data, seeded]);

  const testMutation = useMutation({
    mutationFn: (url: string) => api.testVoiceboxConnection(url),
    onMutate: () => {
      setTestState({ kind: "testing" });
    },
    onSuccess: (result) => {
      if (result.reachable) {
        setTestState({ kind: "ok", result });
      } else {
        setTestState({
          kind: "fail",
          error: result.error ?? "Unreachable",
        });
      }
    },
    onError: (err: unknown) => {
      setTestState({
        kind: "fail",
        error: err instanceof Error ? err.message : String(err),
      });
    },
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateVoiceboxConfig({
        base_url: urlInput.trim(),
        enabled: enabledToggle,
      }),
    onSuccess: () => {
      toast({ kind: "success", message: "Voicebox settings saved." });
      qc.invalidateQueries({ queryKey: ["voicebox-health"] });
      qc.invalidateQueries({ queryKey: ["voicebox-status"] });
    },
    onError: (err: unknown) => {
      const detail = err instanceof Error ? err.message : String(err);
      toast({
        kind: "error",
        message: `Couldn't save Voicebox settings: ${detail}`,
      });
    },
  });

  const trimmedUrl = urlInput.trim();
  const canEnable = trimmedUrl.length > 0 && testState.kind === "ok";
  // Keep the toggle honest: if the user clears the URL or never passed a
  // test, force the toggle back off locally (save would 400 anyway).
  useEffect(() => {
    if (!canEnable && enabledToggle) setEnabledToggle(false);
  }, [canEnable, enabledToggle]);

  const health = vbHealth.data;
  const headerChipClass = health?.enabled && health.reachable
    ? "text-success border-success/40"
    : health?.configured
      ? "text-muted"
      : "text-muted";
  const headerChipText = !health
    ? "—"
    : !health.configured
      ? "not configured"
      : !health.enabled
        ? "off"
        : health.reachable
          ? "online"
          : "unreachable";

  return (
    <div className="space-y-5 pb-6">
      <h1 className="text-3xl">Settings</h1>

      {/* -------- Voicebox (top — TTS is critical) ----------------------- */}
      <section className="card p-4 space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-display">Voicebox</h2>
          <span className={`chip text-[10px] uppercase ${headerChipClass}`}>
            {headerChipText}
          </span>
        </div>

        <p className="text-sm text-muted">
          Voicebox runs separately on your Mac and handles text-to-speech.
          Configure its URL here — Voicebox prints its own URL in its UI
          when it launches (the port is assigned at runtime).
        </p>

        {/* URL row */}
        <div className="space-y-1">
          <label className="text-xs uppercase tracking-wide text-muted">
            URL
          </label>
          <input
            type="url"
            className="input w-full"
            placeholder="http://localhost:17493"
            value={urlInput}
            onChange={(e) => {
              setUrlInput(e.target.value);
              // Any URL edit invalidates the prior test result — force a
              // re-test before enable becomes valid again.
              if (testState.kind !== "idle") setTestState({ kind: "idle" });
            }}
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-surface"
            disabled={!trimmedUrl || testMutation.isPending}
            onClick={() => testMutation.mutate(trimmedUrl)}
          >
            {testMutation.isPending ? "Testing…" : "Test connection"}
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? "Saving…" : "Save"}
          </button>
        </div>

        {/* Test result block */}
        <TestResultBlock state={testState} />

        {/* Enable toggle */}
        <div className="pt-2 border-t border-border/40 space-y-1">
          <label className="flex items-center gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={enabledToggle}
              disabled={!canEnable}
              onChange={(e) => setEnabledToggle(e.target.checked)}
            />
            <span className="text-sm">Enable Voicebox</span>
          </label>
          {!canEnable && (
            <p className="text-xs text-muted">
              {trimmedUrl.length === 0
                ? "Enter a URL first."
                : "Test the connection successfully before enabling."}
            </p>
          )}

          {/* Effective state summary */}
          {health && (
            <p className="text-xs text-muted pt-1">
              Currently:{" "}
              {!health.configured
                ? "no URL configured"
                : !health.enabled
                  ? `URL saved (${health.base_url}), disabled`
                  : health.reachable
                    ? `enabled, reachable at ${health.base_url}${
                        health.version ? ` (v${health.version})` : ""
                      }`
                    : `enabled but unreachable at ${health.base_url}`}
              .
            </p>
          )}
        </div>
      </section>

      {/* -------- Pronunciations ---------------------------------------- */}
      <section className="card p-4 space-y-2">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-lg font-display">Pronunciations (Global)</h2>
          <Link
            to="/settings/pronunciations"
            className="btn-surface text-xs"
          >
            Open
          </Link>
        </div>
        <p className="text-sm text-muted">
          Shared pronunciation overrides applied to every project. Project-
          scoped entries take precedence at generation time.
        </p>
      </section>

      {/* -------- Other settings ---------------------------------------- */}
      <section className="card p-4 space-y-2">
        <h2 className="text-lg font-display">Other settings</h2>
        <p className="text-sm text-muted">
          API keys, default engine, and export paths land here in Phase 7.
          For now, edit <code className="font-mono">.env</code> directly.
        </p>
      </section>
    </div>
  );
}

function TestResultBlock({ state }: { state: TestState }) {
  if (state.kind === "idle") {
    return <p className="text-xs text-muted">Not tested yet.</p>;
  }
  if (state.kind === "testing") {
    return <p className="text-xs text-muted">Testing connection…</p>;
  }
  if (state.kind === "fail") {
    return (
      <p className="text-xs text-error">
        <span aria-hidden>✕</span> {state.error}
      </p>
    );
  }
  const r = state.result;
  const parts = [
    `Reachable`,
    r.version ? `version ${r.version}` : null,
    `GPU: ${r.gpu_available ? "yes" : "no"}`,
    `Model loaded: ${r.model_loaded ? "yes" : "no"}`,
    r.models_loaded > 0
      ? `${r.models_loaded} model${r.models_loaded === 1 ? "" : "s"}`
      : null,
    r.profile_count > 0
      ? `${r.profile_count} profile${r.profile_count === 1 ? "" : "s"}`
      : null,
  ].filter(Boolean);
  return (
    <p className="text-xs text-success">
      <span aria-hidden>✓</span> {parts.join(" · ")}
    </p>
  );
}
