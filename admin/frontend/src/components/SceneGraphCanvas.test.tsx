// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SceneGraphCanvas from "./SceneGraphCanvas";
import type { Scene } from "../types";

vi.mock("../api/triggers", () => ({
  createTrigger: vi.fn(),
  updateTrigger: vi.fn(),
  deleteTrigger: vi.fn(),
  updateTriggerPosition: vi.fn(),
}));
vi.mock("../api/scenes", () => ({
  updateScene: vi.fn(),
  updateScenePosition: vi.fn(),
}));

const SCENE: Scene = {
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
  output_id: null,
  color: null,
};

describe("SceneGraphCanvas -- klikken op een stap-chip", () => {
  it("roept onSceneClick met de juiste stap aan bij klikken op de effect-chip", async () => {
    const onSceneClick = vi.fn();
    render(
      <SceneGraphCanvas
        scenes={[SCENE]}
        triggers={[]}
        onSceneClick={onSceneClick}
        onGraphChanged={vi.fn()}
        onAddScene={vi.fn()}
      />,
    );

    const chip = await screen.findByText("xray");
    await userEvent.click(chip);

    expect(onSceneClick).toHaveBeenCalledWith(1, "animation");
  });

  it("roept onSceneClick met 'output' aan bij klikken op de Weergave-chip", async () => {
    const onSceneClick = vi.fn();
    render(
      <SceneGraphCanvas
        scenes={[SCENE]}
        triggers={[]}
        onSceneClick={onSceneClick}
        onGraphChanged={vi.fn()}
        onAddScene={vi.fn()}
      />,
    );

    const chip = await screen.findByText("Weergave");
    await userEvent.click(chip);

    expect(onSceneClick).toHaveBeenCalledWith(1, "output");
  });
});
