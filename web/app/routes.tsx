import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { LiveWall } from "./pages/live";
import { CameraDetail } from "./pages/camera-detail";
import { EventFeed } from "./pages/events";
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
            <Route path="/live" element={<LiveWall />} />
            <Route path="/live/:id" element={<CameraDetail />} />
            <Route path="/events" element={<EventFeed />} />
            <Route path="/studio" element={<UseCaseStudio />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/artifacts" element={<ArtifactsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
