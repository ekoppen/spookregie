// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import OutputPreviewPanel from "./OutputPreviewPanel";
import { getSettings } from "../api/settings";
import { startMirrorProcess, stopMirrorProcess, getMirrorProcessStatus } from "../api/mirrorProcess";
import type { AppSettings } from "../types";

vi.mock("../api/settings", () => ({ getSettings: vi.fn() }));
vi.mock("../api/mirrorProcess", () => ({
  startMirrorProcess: vi.fn(),
  stopMirrorProcess: vi.fn(),
  getMirrorProcessStatus: vi.fn(),
}));

const SETTINGS_WITH_STREAM: AppSettings = {
  mqtt_host: "broker",
  mqtt_port: 1883,
  mqtt_user: "",
  ha_url: "",
  mirror_stream_url: "http://mirror-node.local:8091/stream",
  mqtt_topic_prefix: "",
  scare_escalation_time: "",
  mqtt_pass_set: false,
  ha_token_set: false,
};

beforeEach(() => {
  vi.mocked(getSettings).mockResolvedValue(SETTINGS_WITH_STREAM);
  vi.mocked(getMirrorProcessStatus).mockResolvedValue({ running: false, pid: null });
});

function renderPanel(onClose = vi.fn()) {
  return render(
    <MemoryRouter>
      <OutputPreviewPanel onClose={onClose} />
    </MemoryRouter>,
  );
}

describe("OutputPreviewPanel", () => {
  it("toont een Start-knop en geen stream-afbeelding als het proces niet draait", async () => {
    renderPanel();

    expect(await screen.findByRole("button", { name: "Start" })).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("start het proces en toont de stream-afbeelding zodra het draait", async () => {
    vi.mocked(startMirrorProcess).mockResolvedValue({ running: true, pid: 123 });
    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Start" }));

    const img = await screen.findByRole("img");
    expect(img).toHaveAttribute("src", "http://mirror-node.local:8091/stream");
  });

  it("toont een hint naar Instellingen als de stream-URL nog niet is ingesteld, ook als het proces draait", async () => {
    vi.mocked(getSettings).mockResolvedValue({ ...SETTINGS_WITH_STREAM, mirror_stream_url: "" });
    vi.mocked(getMirrorProcessStatus).mockResolvedValue({ running: true, pid: 123 });
    renderPanel();

    expect(await screen.findByText(/Instellingen/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("stopt het proces via de Stop-knop", async () => {
    vi.mocked(getMirrorProcessStatus).mockResolvedValue({ running: true, pid: 123 });
    vi.mocked(stopMirrorProcess).mockResolvedValue({ running: false, pid: null });
    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));

    await waitFor(() => expect(stopMirrorProcess).toHaveBeenCalled());
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("roept onClose aan bij het sluiten", async () => {
    const onClose = vi.fn();
    renderPanel(onClose);

    await userEvent.click(await screen.findByRole("button", { name: "Sluiten" }));

    expect(onClose).toHaveBeenCalled();
  });
});
