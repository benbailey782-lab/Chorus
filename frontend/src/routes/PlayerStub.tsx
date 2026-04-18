import { Link } from "react-router-dom";

export default function PlayerStub() {
  return (
    <div className="card p-6 text-center space-y-3">
      <h1 className="text-2xl font-display">Player</h1>
      <p className="text-muted text-sm">
        The global audiobook player arrives in Phase 6 (Assembly + Ambient + Player).
        For now, open a project from the Library to see its chapters.
      </p>
      <div>
        <Link to="/" className="btn-primary">Back to Library</Link>
      </div>
    </div>
  );
}
