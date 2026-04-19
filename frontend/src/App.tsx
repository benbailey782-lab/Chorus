import { Link, Route, Routes } from "react-router-dom";

import BottomNav from "./components/BottomNav";
import ToastContainer from "./components/Toast";
import Casting from "./routes/Casting";
import ChapterReview from "./routes/ChapterReview";
import Library from "./routes/Library";
import PlayerStub from "./routes/PlayerStub";
import Project from "./routes/Project";
import Settings from "./routes/Settings";
import VoiceEditor from "./routes/VoiceEditor";
import VoiceLibrary from "./routes/VoiceLibrary";
import { ToastProvider } from "./lib/toast";

export default function App() {
  return (
    <ToastProvider>
      <AppShell />
      <ToastContainer />
    </ToastProvider>
  );
}

function AppShell() {
  return (
    <div className="min-h-full flex flex-col">
      {/* Header is compact on mobile so the useful stuff is above the fold
          at 375px. Nav is at the bottom on mobile, inline here on ≥md. */}
      <header className="sticky top-0 z-10 border-b border-border bg-bg/90 backdrop-blur">
        <div
          className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between gap-3"
          style={{ paddingTop: "calc(0.75rem + env(safe-area-inset-top, 0px))" }}
        >
          <Link
            to="/"
            className="font-display text-2xl tracking-tight hover:text-accent"
          >
            Chorus
          </Link>
          <div className="hidden md:block">
            <BottomNav />
          </div>
        </div>
      </header>

      <main
        className="flex-1 max-w-5xl w-full mx-auto px-4 py-4 md:py-6"
        style={{ paddingBottom: "calc(5rem + env(safe-area-inset-bottom, 0px))" }}
      >
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/project/:idOrSlug" element={<Project />} />
          <Route path="/project/:idOrSlug/cast" element={<Casting />} />
          <Route
            path="/project/:idOrSlug/chapters/:chapterId"
            element={<ChapterReview />}
          />
          <Route path="/voices" element={<VoiceLibrary />} />
          <Route path="/voices/new" element={<VoiceEditor />} />
          <Route path="/voices/:id/edit" element={<VoiceEditor />} />
          <Route path="/player" element={<PlayerStub />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>

      {/* Mobile bottom nav — hidden on ≥md where it lives in the header. */}
      <div className="md:hidden">
        <BottomNav />
      </div>
    </div>
  );
}
