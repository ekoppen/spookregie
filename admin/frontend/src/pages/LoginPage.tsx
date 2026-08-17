import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/auth";
import { ApiError } from "../api/client";
import "./LoginPage.css";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(password);
      navigate("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Onjuist wachtwoord.");
      } else {
        setError("Inloggen mislukt, probeer het opnieuw.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  const ledClass = error
    ? "login-eyebrow__led login-eyebrow__led--denied"
    : submitting
      ? "login-eyebrow__led login-eyebrow__led--busy"
      : "login-eyebrow__led";
  const statusText = error ? "SYSTEM — DENIED" : submitting ? "SYSTEM — VERIFYING…" : "SYSTEM — LOCKED";

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="login-card__rivets" aria-hidden="true">
          <span />
          <span />
        </div>
        <p className="login-eyebrow">
          <span className={ledClass} aria-hidden="true" />
          {statusText}
        </p>
        <h1 className="login-heading">Beheerpagina</h1>
        <label className="login-field">
          <span className="login-field__label">Wachtwoord</span>
          <input
            className="login-field__input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Wachtwoord"
            autoFocus
          />
        </label>
        {error && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}
        <button className="login-submit" type="submit" disabled={submitting}>
          Inloggen
        </button>
      </form>
    </div>
  );
}
