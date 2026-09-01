// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import PlayerGraphCanvas, { parseOutputConnectionEdgeIds } from "./PlayerGraphCanvas";
import type { Player, Trigger, Source, Output } from "../types";
import type { Edge } from "@xyflow/react";
import { deletePlayer } from "../api/players";
import { deleteTrigger, createTrigger } from "../api/triggers";
import { deleteSource, createSource } from "../api/sources";
import { deleteOutput, createOutput } from "../api/outputs";

vi.mock("../api/triggers", () => ({
  createTrigger: vi.fn(),
  updateTrigger: vi.fn(),
  deleteTrigger: vi.fn(),
  updateTriggerPosition: vi.fn(),
}));
vi.mock("../api/players", () => ({
  updatePlayer: vi.fn(),
  updatePlayerPosition: vi.fn(),
  deletePlayer: vi.fn(),
}));
vi.mock("../api/sources", () => ({ updateSource: vi.fn(), deleteSource: vi.fn(), createSource: vi.fn() }));
vi.mock("../api/outputs", () => ({ updateOutput: vi.fn(), deleteOutput: vi.fn(), createOutput: vi.fn() }));
vi.mock("../api/branches", () => ({ createPlayerBranch: vi.fn() }));
vi.mock("../api/outputConnections", () => ({
  createOutputConnection: vi.fn(),
  deleteOutputConnection: vi.fn(),
}));

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
  audio_source_id: null,
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

describe("PlayerGraphCanvas -- rechtsklik-menu", () => {
  it("toont Bewerken/Verwijderen bij rechtsklik op een player, en Verwijderen roept deletePlayer aan", async () => {
    const onGraphChanged = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[PLAYER]}
        sources={[]}
        branches={[]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={vi.fn()}
        onGraphChanged={onGraphChanged}
        onAddPlayer={vi.fn()}
      />,
    );

    fireEvent.contextMenu(await screen.findByText("Basis"));
    const deleteItem = await screen.findByText("Verwijderen");
    await userEvent.click(deleteItem);

    expect(deletePlayer).toHaveBeenCalledWith(1);
    expect(onGraphChanged).toHaveBeenCalled();
  });

  it("Bewerken in het player-rechtsklik-menu opent dezelfde editor als een linksklik", async () => {
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

    fireEvent.contextMenu(await screen.findByText("Basis"));
    await userEvent.click(await screen.findByText("Bewerken"));

    expect(onPlayerClick).toHaveBeenCalledWith(1, "input");
  });

  it("Verwijderen op een trigger roept deleteTrigger aan", async () => {
    const TRIGGER: Trigger = {
      id: 5,
      from_branch_id: 1,
      to_player_id: null,
      kind: "motion",
      schedule_from: null,
      schedule_until: null,
      ha_entity_id: null,
      priority: 0,
      canvas_x: 0,
      canvas_y: 0,
      name: "Mijn trigger",
      color: null,
    };
    const onGraphChanged = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[]}
        sources={[]}
        branches={[]}
        triggers={[TRIGGER]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={vi.fn()}
        onGraphChanged={onGraphChanged}
        onAddPlayer={vi.fn()}
      />,
    );

    fireEvent.contextMenu(await screen.findByText("Mijn trigger"));
    await userEvent.click(await screen.findByText("Verwijderen"));

    expect(deleteTrigger).toHaveBeenCalledWith(5);
    expect(onGraphChanged).toHaveBeenCalled();
  });

  it("Bewerken op een source navigeert naar /sources, Verwijderen roept deleteSource aan", async () => {
    const SOURCE: Source = { id: 2, name: "Spiegel camera", kind: "camera_stream", value: "rtsp://x", canvas_x: 0, canvas_y: 0 };
    const onGraphChanged = vi.fn();
    render(
      <MemoryRouter>
        <PlayerGraphCanvas
          players={[]}
          sources={[SOURCE]}
          branches={[]}
          triggers={[]}
          outputs={[]}
          outputConnections={[]}
          onPlayerClick={vi.fn()}
          onGraphChanged={onGraphChanged}
          onAddPlayer={vi.fn()}
        />
      </MemoryRouter>,
    );

    fireEvent.contextMenu(await screen.findByText("Spiegel camera"));
    await userEvent.click(await screen.findByText("Verwijderen"));

    expect(deleteSource).toHaveBeenCalledWith(2);
    expect(onGraphChanged).toHaveBeenCalled();
  });

  it("Verwijderen op een output roept deleteOutput aan", async () => {
    const OUTPUT: Output = { id: 3, name: "Spiegel", camera_source: "", canvas_x: 0, canvas_y: 0 };
    const onGraphChanged = vi.fn();
    render(
      <MemoryRouter>
        <PlayerGraphCanvas
          players={[]}
          sources={[]}
          branches={[]}
          triggers={[]}
          outputs={[OUTPUT]}
          outputConnections={[]}
          onPlayerClick={vi.fn()}
          onGraphChanged={onGraphChanged}
          onAddPlayer={vi.fn()}
        />
      </MemoryRouter>,
    );

    fireEvent.contextMenu(await screen.findByText("Spiegel"));
    await userEvent.click(await screen.findByText("Verwijderen"));

    expect(deleteOutput).toHaveBeenCalledWith(3);
    expect(onGraphChanged).toHaveBeenCalled();
  });
});

describe("PlayerGraphCanvas -- toolbar-knoppen om Source/Output/Trigger toe te voegen", () => {
  it("+ Nieuwe source roept createSource aan met standaardwaarden", async () => {
    const onGraphChanged = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[]}
        sources={[]}
        branches={[]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={vi.fn()}
        onGraphChanged={onGraphChanged}
        onAddPlayer={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("+ Nieuwe source"));

    expect(createSource).toHaveBeenCalledWith({
      name: "Nieuwe source",
      kind: "camera_stream",
      value: "",
      canvas_x: 0,
      canvas_y: 0,
    });
    expect(onGraphChanged).toHaveBeenCalled();
  });

  it("+ Nieuwe output roept createOutput aan met standaardwaarden", async () => {
    const onGraphChanged = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[]}
        sources={[]}
        branches={[]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={vi.fn()}
        onGraphChanged={onGraphChanged}
        onAddPlayer={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("+ Nieuwe output"));

    expect(createOutput).toHaveBeenCalledWith({ name: "Nieuwe output", camera_source: "", canvas_x: 0, canvas_y: 0 });
    expect(onGraphChanged).toHaveBeenCalled();
  });

  it("+ Nieuwe trigger is uitgeschakeld zonder players/branches", async () => {
    render(
      <PlayerGraphCanvas
        players={[]}
        sources={[]}
        branches={[]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={vi.fn()}
        onGraphChanged={vi.fn()}
        onAddPlayer={vi.fn()}
      />,
    );

    expect(screen.getByText("+ Nieuwe trigger")).toBeDisabled();
  });

  it("+ Nieuwe trigger opent een keuzemenu en maakt de trigger aan vanaf de gekozen aftakking", async () => {
    const onGraphChanged = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[PLAYER]}
        sources={[]}
        branches={[{ id: 101, player_id: 1, name: "Uitgang 1" }]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={vi.fn()}
        onGraphChanged={onGraphChanged}
        onAddPlayer={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("+ Nieuwe trigger"));
    await userEvent.selectOptions(await screen.findByRole("combobox"), "101");
    await userEvent.click(screen.getByText("Aanmaken"));

    expect(createTrigger).toHaveBeenCalledWith({ from_branch_id: 101 });
    expect(onGraphChanged).toHaveBeenCalled();
  });
});

describe("parseOutputConnectionEdgeIds -- herkenning van output-connection-edges", () => {
  it("haalt alleen de id's van oc-edges eruit, andere edge-typen genegeerd", () => {
    const edges = [
      { id: "oc-9" },
      { id: "source-in-1" },
      { id: "branch-in-3" },
      { id: "out-3" },
      { id: "oc-12" },
    ] as Edge[];

    expect(parseOutputConnectionEdgeIds(edges)).toEqual([9, 12]);
  });

  it("geeft een lege lijst terug als er geen oc-edges bij zitten", () => {
    const edges = [{ id: "source-in-1" }, { id: "out-3" }] as Edge[];

    expect(parseOutputConnectionEdgeIds(edges)).toEqual([]);
  });
});
