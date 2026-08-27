import { useEffect, useState } from "react";
import { getSettings, putSettings } from "../api/settings";
import type { AppSettings } from "../types";
import "./SettingsPage.css";

interface FormState {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass: string;
  ha_url: string;
  ha_token: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
}

const EMPTY_FORM: FormState = {
  mqtt_host: "",
  mqtt_port: 1883,
  mqtt_user: "",
  mqtt_pass: "",
  ha_url: "",
  ha_token: "",
  mirror_stream_url: "",
  mqtt_topic_prefix: "",
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings()
      .then((result) => {
        setSettings(result);
        setForm({
          mqtt_host: result.mqtt_host,
          mqtt_port: result.mqtt_port,
          mqtt_user: result.mqtt_user,
          mqtt_pass: "",
          ha_url: result.ha_url,
          ha_token: "",
          mirror_stream_url: result.mirror_stream_url,
          mqtt_topic_prefix: result.mqtt_topic_prefix,
        });
        setError(null);
      })
      .catch(() => setError("Instellingen konden niet worden geladen."));
  }, []);

  function update(patch: Partial<FormState>) {
    setForm((prev) => ({ ...prev, ...patch }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await putSettings({
        mqtt_host: form.mqtt_host,
        mqtt_port: form.mqtt_port,
        mqtt_user: form.mqtt_user,
        ...(form.mqtt_pass ? { mqtt_pass: form.mqtt_pass } : {}),
        ha_url: form.ha_url,
        ...(form.ha_token ? { ha_token: form.ha_token } : {}),
        mirror_stream_url: form.mirror_stream_url,
        mqtt_topic_prefix: form.mqtt_topic_prefix,
      });
      const refreshed = await getSettings();
      setSettings(refreshed);
      setForm((prev) => ({ ...prev, mqtt_pass: "", ha_token: "" }));
      setError(null);
      setNotice("Instellingen opgeslagen.");
      window.setTimeout(() => setNotice(null), 3000);
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-page">
      <header className="settings-header">
        <p className="settings-eyebrow">
          <span className="settings-eyebrow__led" aria-hidden="true" />
          Systeem
        </p>
        <h1 className="settings-heading">Instellingen</h1>
      </header>

      {error && (
        <p className="settings-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="settings-notice" role="status">
          {notice}
        </p>
      )}

      {!settings ? (
        <p className="settings-loading">Laden…</p>
      ) : (
        <>
          <section className="settings-panel">
            <p className="settings-panel__eyebrow">MQTT-broker</p>
            <div className="settings-grid">
              <label className="settings-field">
                <span className="settings-field__label">Host</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mqtt_host}
                  onChange={(e) => update({ mqtt_host: e.target.value })}
                />
              </label>
              <label className="settings-field">
                <span className="settings-field__label">Poort</span>
                <input
                  className="settings-field__input"
                  type="number"
                  value={form.mqtt_port}
                  onChange={(e) => update({ mqtt_port: parseInt(e.target.value, 10) || 0 })}
                />
              </label>
              <label className="settings-field">
                <span className="settings-field__label">Gebruikersnaam</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mqtt_user}
                  onChange={(e) => update({ mqtt_user: e.target.value })}
                />
              </label>
              <label className="settings-field">
                <span className="settings-field__label">Wachtwoord</span>
                <input
                  className="settings-field__input"
                  type="password"
                  value={form.mqtt_pass}
                  placeholder={
                    settings.mqtt_pass_set ? "•••• (ingesteld, laat leeg om te behouden)" : "niet ingesteld"
                  }
                  onChange={(e) => update({ mqtt_pass: e.target.value })}
                />
              </label>
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">Topic-prefix (optioneel)</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mqtt_topic_prefix}
                  placeholder="bijv. spookregie of test"
                  onChange={(e) => update({ mqtt_topic_prefix: e.target.value })}
                />
              </label>
            </div>
            <p className="settings-field__label" style={{ marginTop: "0.75rem" }}>
              Laat leeg voor geen namespace. Nodes halen deze waarde pas op bij
              hun eerstvolgende herstart — een lopende node picked een
              wijziging hier niet live op.
            </p>
          </section>

          <section className="settings-panel">
            <p className="settings-panel__eyebrow">Home Assistant</p>
            <div className="settings-grid">
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">URL</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.ha_url}
                  placeholder="http://homeassistant.local:8123"
                  onChange={(e) => update({ ha_url: e.target.value })}
                />
              </label>
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">Token</span>
                <input
                  className="settings-field__input"
                  type="password"
                  value={form.ha_token}
                  placeholder={
                    settings.ha_token_set ? "•••• (ingesteld, laat leeg om te behouden)" : "niet ingesteld"
                  }
                  onChange={(e) => update({ ha_token: e.target.value })}
                />
              </label>
            </div>
          </section>

          <section className="settings-panel">
            <p className="settings-panel__eyebrow">Spiegel-node</p>
            <div className="settings-grid">
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">Live-preview-stream-URL</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mirror_stream_url}
                  placeholder="http://mirror-node.local:8091/stream"
                  onChange={(e) => update({ mirror_stream_url: e.target.value })}
                />
              </label>
            </div>
          </section>

          <div className="settings-actions">
            <button className="settings-save" type="button" onClick={handleSave} disabled={saving}>
              {saving ? "Bezig…" : "Opslaan"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
