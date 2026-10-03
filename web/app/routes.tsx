import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { LivePage } from "./pages/live";
import { CamerasPage } from "./pages/cameras";
import { ModelsPage } from "./pages/models";
import { EventsPage } from "./pages/events";
import { ReviewPage } from "./pages/review";
import { UseCaseStudio } from "./pages/use-case-studio";
import { MetricsPage } from "./pages/metrics";
import { ArtifactsPage } from "./pages/artifacts";
import { NavBar } from "../components/nav-bar";

export function AppRoutes() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-background text-foreground flex flex-col">
        <NavBar />
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<Navigate to="/live" replace />} />
            <Route path="/live" element={<LivePage />} />
            <Route path="/live/:id" element={<LivePage />} />
            <Route path="/cameras" element={<CamerasPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/studio" element={<UseCaseStudio />} />
            <Route path="/events" element={<EventsPage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/artifacts" element={<ArtifactsPage />} />
            <Route path="*" element={<Navigate to="/live" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
