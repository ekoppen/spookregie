import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// ponytail: minimale class-based ErrorBoundary -- React heeft geen hook-
// variant. Vangt render-fouten ergens in de boom (bv. een misvormd
// MQTT-veld dat niet gegokt werd) en toont een herstelpad i.p.v. een wit
// scherm.
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Onafgevangen fout in de UI:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: "2rem", color: "#e8e3d8", background: "#0b0b0f", minHeight: "100vh" }}>
          <p>Er is iets misgegaan — herlaad de pagina.</p>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
