import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../lib/api";

export default function Settings() {
  const vbStatus = useQuery({
    queryKey: ["voicebox-status"],
    queryFn: api.voiceboxStatus,
    staleTime: 30_000,
  });

  return (
    <div className="space-y-5 pb-6">
      <h1 className="text-3xl">Settings</h1>

      <section className="card p-4 space-y-2">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-display">Voicebox</h2>
          <span
            className={`chip text-[10px] uppercase ${
              vbStatus.data?.enabled && vbStatus.data.reachable
                ? "text-success border-success/40"
                : "text-muted"
            }`}
          >
            {vbStatus.data?.enabled
              ? vbStatus.data.reachable
                ? "online"
                : "unreachable"
              : "off"}
          </span>
        </div>
        <dl className="text-sm text-muted space-y-1">
          <div className="flex justify-between gap-3">
            <dt>Enabled</dt>
            <dd className="text-fg font-mono">
              {vbStatus.data ? String(vbStatus.data.enabled) : "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Base URL</dt>
            <dd className="text-fg font-mono truncate ml-2">
              {vbStatus.data?.base_url ?? "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Status</dt>
            <dd className="text-fg">
              {vbStatus.data?.reachable === null
                ? "n/a (disabled)"
                : vbStatus.data?.reachable
                  ? "reachable"
                  : "unreachable"}
            </dd>
          </div>
        </dl>
        {vbStatus.data && <p className="text-xs text-muted">{vbStatus.data.note}</p>}
        <p className="text-xs text-muted">
          Voicebox is configured via the <code className="font-mono">VOICEBOX_ENABLED</code>{" "}
          and <code className="font-mono">VOICEBOX_BASE_URL</code> env vars. Restart the
          backend after changing either.
        </p>
      </section>

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
