// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DevicesPage from "./DevicesPage";
import { listDevices } from "../api/devices";
import { listOutputs } from "../api/outputs";
import { getNodes } from "../api/nodes";
import { createSource } from "../api/sources";
import type { Device } from "../types";

vi.mock("../api/devices", () => ({
  listDevices: vi.fn(),
  updateDevice: vi.fn(),
  deleteDevice: vi.fn(),
}));
vi.mock("../api/outputs", () => ({ listOutputs: vi.fn() }));
vi.mock("../api/nodes", () => ({ getNodes: vi.fn() }));
vi.mock("../api/sources", () => ({ createSource: vi.fn() }));

const MIRROR_DEVICE: Device = {
  id: 1,
  device_uuid: "mirror-uuid",
  name: "Hallo1",
  platform: "linux",
  git_sha: "abc1234",
  last_seen_at: "2026-09-01 20:00:00",
  output_id: null,
  is_mirror: true,
  is_camera: false,
  camera_stream_url: null,
};

const CAMERA_DEVICE: Device = {
  id: 2,
  device_uuid: "camera-uuid",
  name: "MacBook camera",
  platform: "darwin",
  git_sha: "def5678",
  last_seen_at: "2026-09-01 20:05:00",
  output_id: null,
  is_mirror: false,
  is_camera: true,
  camera_stream_url: "http://192.168.1.50:8080/stream",
};

beforeEach(() => {
  vi.mocked(listOutputs).mockResolvedValue([]);
  vi.mocked(getNodes).mockResolvedValue({});
});

describe("DevicesPage -- conditionele rol-weergave", () => {
  it("toont de output-picker voor een mirror-apparaat, geen camera-rij", async () => {
    vi.mocked(listDevices).mockResolvedValue([MIRROR_DEVICE]);
    render(<DevicesPage />);

    expect(await screen.findByDisplayValue("Hallo1")).toBeInTheDocument();
    expect(screen.getByText("Geen output")).toBeInTheDocument();
    expect(screen.queryByText("Maak hiervan een source")).not.toBeInTheDocument();
  });

  it("toont de stream-URL en een 'Maak hiervan een source'-knop voor een camera-apparaat, geen output-picker", async () => {
    vi.mocked(listDevices).mockResolvedValue([CAMERA_DEVICE]);
    render(<DevicesPage />);

    expect(await screen.findByDisplayValue("MacBook camera")).toBeInTheDocument();
    expect(screen.getByText("http://192.168.1.50:8080/stream")).toBeInTheDocument();
    expect(screen.getByText("Maak hiervan een source")).toBeInTheDocument();
    expect(screen.queryByText("Geen output")).not.toBeInTheDocument();
  });

  it("'Maak hiervan een source' roept createSource aan met de stream-URL", async () => {
    vi.mocked(listDevices).mockResolvedValue([CAMERA_DEVICE]);
    vi.mocked(createSource).mockResolvedValue({
      id: 9,
      name: "MacBook camera camera",
      kind: "camera_stream",
      value: "http://192.168.1.50:8080/stream",
      canvas_x: 0,
      canvas_y: 0,
    });
    render(<DevicesPage />);

    await userEvent.click(await screen.findByText("Maak hiervan een source"));

    await waitFor(() =>
      expect(createSource).toHaveBeenCalledWith({
        name: "MacBook camera camera",
        kind: "camera_stream",
        value: "http://192.168.1.50:8080/stream",
        canvas_x: 0,
        canvas_y: 0,
      }),
    );
  });
});
