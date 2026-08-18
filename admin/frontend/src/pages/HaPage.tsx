import { useEffect, useState } from "react";
import { getHaStates, callHaService } from "../api/ha";
import type { HaState } from "../types";
import "./HaPage.css";

export default function HaPage() {
  const [states, setStates] = useState<HaState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    getHaStates()
      .then((result) => {
        setStates(result);
        setError(null);
      })
      .catch(() => setError("HA-status kon niet worden geladen."));
  }, []);

  const lights = states.filter((s) => s.entity_id.startsWith("light."));

  async function toggle(light: HaState) {
    const turningOn = light.state !== "on";
    setPending(light.entity_id);
    try {
      await callHaService("light", turningOn ? "turn_on" : "turn_off", {
        entity_id: light.entity_id,
      });
      setStates((prev) =>
        prev.map((s) =>
          s.entity_id === light.entity_id ? { ...s, state: turningOn ? "on" : "off" } : s,
        ),
      );
      setError(null);
    } catch {
      setError(`Schakelen van ${light.entity_id} is mislukt.`);
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="ha-page">
      <header className="ha-header">
        <p className="ha-eyebrow">
          <span className="ha-eyebrow__led" aria-hidden="true" />
          Home Assistant
        </p>
        <h1 className="ha-heading">Lichtschakelaars</h1>
      </header>

      {error && (
        <p className="ha-error" role="alert">
          {error}
        </p>
      )}

      <section className="ha-panel">
        <p className="ha-panel__eyebrow">Circuits</p>
        {lights.length === 0 ? (
          <p className="ha-empty">
            Geen licht-entiteiten gevonden. Dit kan betekenen dat er geen WLED-lampen zijn
            geconfigureerd, óf dat Home Assistant niet bereikbaar is — dat onderscheid maakt
            deze pagina niet.
          </p>
        ) : (
          <ul className="ha-breaker-row">
            {lights.map((light) => {
              const isOn = light.state === "on";
              const isPending = pending === light.entity_id;
              return (
                <li className="ha-breaker" key={light.entity_id}>
                  <button
                    type="button"
                    className="ha-breaker__switch"
                    role="switch"
                    aria-checked={isOn}
                    aria-label={`${light.entity_id} ${isOn ? "aan" : "uit"}`}
                    disabled={isPending}
                    onClick={() => toggle(light)}
                  >
                    <span className="ha-breaker__led" data-on={isOn} aria-hidden="true" />
                    <span className="ha-breaker__toggle" data-on={isOn} aria-hidden="true" />
                  </button>
                  <span className="ha-breaker__label">{light.entity_id}</span>
                  <span className="ha-breaker__state">
                    {isPending ? "bezig…" : isOn ? "aan" : "uit"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
