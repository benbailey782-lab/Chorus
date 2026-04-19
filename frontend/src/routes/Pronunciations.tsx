import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import PronunciationManager from "../components/pronunciations/PronunciationManager";
import { api } from "../lib/api";

export default function Pronunciations() {
  const { idOrSlug = "" } = useParams();

  const project = useQuery({
    queryKey: ["project", idOrSlug],
    queryFn: () => api.getProject(idOrSlug),
    enabled: !!idOrSlug,
  });

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

  return (
    <div className="space-y-4 pb-6">
      <div>
        <Link
          to={`/project/${idOrSlug}`}
          className="text-sm text-muted hover:text-fg"
        >
          ← {project.data.title}
        </Link>
        <h1 className="text-3xl mt-1">Pronunciations</h1>
        <p className="text-xs text-muted mt-1">
          Project-scoped overrides. These take precedence over the{" "}
          <Link to="/settings/pronunciations" className="text-accent underline">
            global library
          </Link>{" "}
          during generation.
        </p>
      </div>

      <PronunciationManager scope="project" projectIdOrSlug={idOrSlug} />
    </div>
  );
}
