import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import LoginPage from "./pages/LoginPage";

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
          path="/*"
          element={
            <ProtectedRoute>
              <div>Beheerpagina — wordt verder opgebouwd in latere taken.</div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
