import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "../api/client";

export function useAuth() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    apiFetch("/api/nodes")
      .then(() => setIsAuthenticated(true))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          setIsAuthenticated(false);
        }
      })
      .finally(() => setChecking(false));
  }, []);

  return { isAuthenticated, checking };
}
