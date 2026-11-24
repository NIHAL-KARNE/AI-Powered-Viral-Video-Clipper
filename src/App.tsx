import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import Dashboard from "./pages/Dashboard";
import NewProject from "./pages/NewProject";
import Videos from "./pages/Videos";
import ProjectPage from "./pages/ProjectPage";
import ClipsLibrary from "./pages/ClipsLibrary";
import EditorPage from "./pages/EditorPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewProject />} />
          <Route path="/videos" element={<Videos />} />
          <Route path="/project/:id" element={<ProjectPage />} />
          <Route path="/clips" element={<ClipsLibrary />} />
          <Route path="/editor/:id" element={<EditorPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}
