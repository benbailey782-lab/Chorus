import { Link } from "react-router-dom";

import PronunciationManager from "../components/pronunciations/PronunciationManager";

export default function SettingsPronunciations() {
  return (
    <div className="space-y-4 pb-6">
      <div>
        <Link to="/settings" className="text-sm text-muted hover:text-fg">
          ← Settings
        </Link>
        <h1 className="text-3xl mt-1">Pronunciations (Global)</h1>
        <p className="text-xs text-muted mt-1">
          Shared pronunciation overrides across every project. Per-project
          entries override globals for that project.
        </p>
      </div>

      <PronunciationManager scope="global" />
    </div>
  );
}
