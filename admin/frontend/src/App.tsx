import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import LoginPage from "./pages/LoginPage";
import Layout from "./components/Layout";
import DashboardPage from "./pages/DashboardPage";
import MirrorScareVideoPage from "./pages/MirrorScareVideoPage";
import ScarePage from "./pages/ScarePage";
import HaPage from "./pages/HaPage";
import LogsPage from "./pages/LogsPage";
import SettingsPage from "./pages/SettingsPage";
import OutputsPage from "./pages/OutputsPage";
import SourcesPage from "./pages/SourcesPage";
import DevicesPage from "./pages/DevicesPage";
import MediaPage from "./pages/MediaPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, checking } = useAuth();
  if (checking) return <p>Laden…</p>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<DashboardPage />} />
          <Route path="/mirror-scare" element={<MirrorScareVideoPage />} />
          <Route path="/scare" element={<ScarePage />} />
          <Route path="/ha" element={<HaPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/outputs" element={<OutputsPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/media" element={<MediaPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
