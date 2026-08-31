// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlayerGraphCanvas from "./PlayerGraphCanvas";
import type { Player } from "../types";

vi.mock("../api/triggers", () => ({
  createTrigger: vi.fn(),
  updateTrigger: vi.fn(),
  deleteTrigger: vi.fn(),
  updateTriggerPosition: vi.fn(),
}));
vi.mock("../api/players", () => ({
  updatePlayer: vi.fn(),
  updatePlayerPosition: vi.fn(),
}));
vi.mock("../api/sources", () => ({ updateSource: vi.fn() }));
vi.mock("../api/outputs", () => ({ updateOutput: vi.fn() }));
vi.mock("../api/branches", () => ({ createPlayerBranch: vi.fn() }));
vi.mock("../api/outputConnections", () => ({ createOutputConnection: vi.fn() }));

const PLAYER: Player = {
  id: 1,
  name: "Basis",
  enabled: true,
  source_mode: "camera",
  effect: "xray",
  params: {},
  overlay_hash: null,
  scale: 1.0,
  position: [0.5, 0.5],
  canvas_size: null,
  source_scale: 1.0,
  source_position: [0.5, 0.5],
  is_root: true,
  canvas_x: 0,
  canvas_y: 0,
  color: null,
  source_id: null,
  playback_mode: "once",
  repeat_while_ha_entity_id: null,
};

describe("PlayerGraphCanvas -- klikken op een stap-chip", () => {
  it("roept onPlayerClick met de juiste stap aan bij klikken op de effect-chip", async () => {
    const onPlayerClick = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[PLAYER]}
        sources={[]}
        branches={[]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={onPlayerClick}
        onGraphChanged={vi.fn()}
        onAddPlayer={vi.fn()}
      />,
    );

    const chip = await screen.findByText("xray");
    await userEvent.click(chip);

    expect(onPlayerClick).toHaveBeenCalledWith(1, "animation");
  });

  it("roept onPlayerClick met 'output' aan bij klikken op de Weergave-chip", async () => {
    const onPlayerClick = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[PLAYER]}
        sources={[]}
        branches={[]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={onPlayerClick}
        onGraphChanged={vi.fn()}
        onAddPlayer={vi.fn()}
      />,
    );

    const chip = await screen.findByText("Weergave");
    await userEvent.click(chip);

    expect(onPlayerClick).toHaveBeenCalledWith(1, "output");
  });
});

describe("PlayerGraphCanvas -- branch-dots", () => {
  it("toont één aftakking-rij per branch van een player", async () => {
    render(
      <PlayerGraphCanvas
        players={[PLAYER]}
        sources={[]}
        branches={[{ id: 101, player_id: 1, name: "Uitgang 1" }, { id: 102, player_id: 1, name: "Extra" }]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={vi.fn()}
        onGraphChanged={vi.fn()}
        onAddPlayer={vi.fn()}
      />,
    );

    expect(await screen.findByText("Uitgang 1")).toBeInTheDocument();
    expect(await screen.findByText("Extra")).toBeInTheDocument();
  });
});
