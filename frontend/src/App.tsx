import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import Casting from "./routes/Casting";
import ChapterReview from "./routes/ChapterReview";
import Library from "./routes/Library";
import Player from "./routes/Player";
import PlayerTab from "./routes/PlayerTab";
import Project from "./routes/Project";
import Pronunciations from "./routes/Pronunciations";
import Settings from "./routes/Settings";
import SettingsPronunciations from "./routes/SettingsPronunciations";
import VoiceEditor from "./routes/VoiceEditor";
import VoiceLibrary from "./routes/VoiceLibrary";
import { ToastProvider } from "./lib/toast";

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Library />} />
          <Route path="/project/:idOrSlug" element={<Project />} />
          <Route path="/project/:idOrSlug/cast" element={<Casting />} />
          <Route
            path="/project/:idOrSlug/chapters/:chapterId"
            element={<ChapterReview />}
          />
          <Route
            path="/project/:idOrSlug/pronunciations"
            element={<Pronunciations />}
          />
          <Route path="/voices" element={<VoiceLibrary />} />
          <Route path="/voices/new" element={<VoiceEditor />} />
          <Route path="/voices/:id/edit" element={<VoiceEditor />} />
          <Route path="/player" element={<PlayerTab />} />
          <Route path="/play/:idOrSlug" element={<Player />} />
          <Route path="/settings" element={<Settings />} />
          <Route
            path="/settings/pronunciations"
            element={<SettingsPronunciations />}
          />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
