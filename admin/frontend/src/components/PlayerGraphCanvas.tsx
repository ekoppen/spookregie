import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { createTrigger, updateTrigger, updateTriggerPosition } from "../api/triggers";
import { updatePlayer, updatePlayerPosition } from "../api/players";
import { updateSource } from "../api/sources";
import { updateOutput } from "../api/outputs";
import { createPlayerBranch } from "../api/branches";
import { createOutputConnection } from "../api/outputConnections";
import TriggerPopover from "./TriggerPopover";
import type { Player, Source, PlayerBranch, Trigger, Output, OutputConnection } from "../types";
import "./PlayerGraphCanvas.css";

const NODE_COLORS = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6", "#95a5a6"];

interface Props {
  players: Player[];
  sources: Source[];
  branches: PlayerBranch[];
  triggers: Trigger[];
  outputs: Output[];
  outputConnections: OutputConnection[];
  onPlayerClick: (playerId: number, step: "input" | "animation" | "output") => void;
  onGraphChanged: () => void;
  onAddPlayer: () => void;
}

type PlayerNodeData = {
  player: Player;
  branches: PlayerBranch[];
  onPlayerClick: Props["onPlayerClick"];
  onAddBranchTrigger: (branchId: number) => void;
  onMakeRoot: (playerId: number) => void;
  onRename: (playerId: number, name: string) => void;
  onSetColor: (playerId: number, color: string) => void;
  [key: string]: unknown;
};

type SourceNodeData = { source: Source; [key: string]: unknown };
type OutputNodeData = { output: Output; [key: string]: unknown };

type TriggerNodeData = {
  trigger: Trigger;
  onTriggerClick: (triggerId: number) => void;
  onRename: (triggerId: number, name: string) => void;
  onSetColor: (triggerId: number, color: string) => void;
  [key: string]: unknown;
};

// @xyflow/react's Node<T> constrains T to Record<string, unknown>; the
// index signatures above satisfy that constraint for our data payloads.
type PlayerNode = Node<PlayerNodeData, "player">;
type SourceNode = Node<SourceNodeData, "source">;
type OutputNode = Node<OutputNodeData, "output">;
type TriggerNode = Node<TriggerNodeData, "trigger">;
type FlowNode = PlayerNode | SourceNode | OutputNode | TriggerNode;

function triggerKindLabel(trigger: Trigger): string {
  if (trigger.kind === "always") return "Altijd";
  if (trigger.kind === "motion") return "Beweging";
  if (trigger.kind === "schedule") return `${trigger.schedule_from ?? "?"}–${trigger.schedule_until ?? "?"}`;
  if (trigger.kind === "ha_sensor") return trigger.ha_entity_id ?? "HA-sensor";
  return "Nog niet ingesteld";
}

function PlayerNodeComponent({ data }: NodeProps<PlayerNode>) {
  const { player, branches, onPlayerClick, onAddBranchTrigger, onMakeRoot, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(player.name);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const clickTimerRef = useRef<number | null>(null);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed && trimmed !== player.name) {
      onRename(player.id, trimmed);
    } else {
      setNameDraft(player.name);
    }
  }

  // ponytail: dblclick fires click+click+dblclick per DOM spec; delay the
  // single-click action so dblclick can cancel it before it opens the wizard.
  function handleNameClick() {
    if (clickTimerRef.current !== null) return;
    clickTimerRef.current = window.setTimeout(() => {
      onPlayerClick(player.id, "input");
      clickTimerRef.current = null;
    }, 250);
  }

  function handleNameDoubleClick() {
    if (clickTimerRef.current !== null) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    setEditingName(true);
  }

  useEffect(() => {
    return () => {
      if (clickTimerRef.current !== null) {
        window.clearTimeout(clickTimerRef.current);
      }
    };
  }, []);

  return (
    <div
      className="player-node"
      data-root={player.is_root}
      style={player.color ? { borderColor: player.color } : undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="player-node__header">
        <button
          type="button"
          className="player-node__root nodrag"
          onClick={() => onMakeRoot(player.id)}
          title="Maak root"
        >
          {player.is_root ? "★" : "☆"}
        </button>
        {editingName ? (
          <input
            className="player-node__name-input nodrag"
            autoFocus
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setNameDraft(player.name);
                setEditingName(false);
              }
            }}
          />
        ) : (
          <span
            className="player-node__name nodrag"
            onClick={handleNameClick}
            onDoubleClick={handleNameDoubleClick}
            title="Klik voor instellingen, dubbelklik om te hernoemen"
          >
            {player.name}
          </span>
        )}
        <button
          type="button"
          className="player-node__color-swatch nodrag"
          style={{ backgroundColor: player.color ?? "transparent" }}
          onClick={() => setColorPickerOpen((open) => !open)}
          title="Kleur"
          aria-label="Kleur kiezen"
        />
        {colorPickerOpen && (
          <div className="player-node__color-palette nodrag">
            {NODE_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className="player-node__color-option"
                style={{ backgroundColor: c }}
                onClick={() => {
                  onSetColor(player.id, c);
                  setColorPickerOpen(false);
                }}
                aria-label={`Kies kleur ${c}`}
              />
            ))}
          </div>
        )}
      </div>
      <div className="player-node__chips">
        <span className="player-node__chip nodrag" onClick={() => onPlayerClick(player.id, "input")}>
          {player.source_mode === "camera" ? "Camera" : "Scare-video"}
        </span>
        {player.source_mode === "camera" && (
          <>
            <span className="player-node__chip nodrag" onClick={() => onPlayerClick(player.id, "animation")}>
              {player.effect}
            </span>
            <span className="player-node__chip nodrag" onClick={() => onPlayerClick(player.id, "output")}>
              Weergave
            </span>
          </>
        )}
      </div>
      {branches.map((branch) => (
        <div className="player-node__branch" key={branch.id}>
          <span className="player-node__branch-name nodrag">{branch.name}</span>
          <button
            type="button"
            className="player-node__branch-add nodrag"
            onClick={() => onAddBranchTrigger(branch.id)}
            title="Nieuwe trigger vanaf deze aftakking"
          >
            +
          </button>
          <Handle type="source" position={Position.Right} id={`branch-${branch.id}`} />
        </div>
      ))}
    </div>
  );
}

function SourceNodeComponent({ data }: NodeProps<SourceNode>) {
  const { source } = data;
  return (
    <div className="source-node">
      <div className="source-node__header">
        <span className="source-node__icon">{source.kind === "camera_stream" ? "📷" : "🖼"}</span>
        <span className="source-node__name">{source.name}</span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function OutputNodeComponent({ data }: NodeProps<OutputNode>) {
  const { output } = data;
  return (
    <div className="output-node">
      <Handle type="target" position={Position.Left} />
      <div className="output-node__header">
        <span className="output-node__icon">🖥</span>
        <span className="output-node__name">{output.name}</span>
      </div>
    </div>
  );
}

function TriggerNodeComponent({ data }: NodeProps<TriggerNode>) {
  const { trigger, onTriggerClick, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(trigger.name ?? "");
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const clickTimerRef = useRef<number | null>(null);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed !== (trigger.name ?? "")) {
      onRename(trigger.id, trimmed);
    }
  }

  // ponytail: same click/dblclick disambiguation as PlayerNodeComponent --
  // dblclick fires click+click+dblclick per DOM spec, so a plain onClick
  // would also fire (and open the popover) on every double-click-to-rename.
  function handleNameClick() {
    if (clickTimerRef.current !== null) return;
    clickTimerRef.current = window.setTimeout(() => {
      onTriggerClick(trigger.id);
      clickTimerRef.current = null;
    }, 250);
  }

  function handleNameDoubleClick() {
    if (clickTimerRef.current !== null) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    setEditingName(true);
  }

  useEffect(() => {
    return () => {
      if (clickTimerRef.current !== null) {
        window.clearTimeout(clickTimerRef.current);
      }
    };
  }, []);

  return (
    <div
      className="trigger-node"
      style={trigger.color ? { borderColor: trigger.color } : undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="trigger-node__header">
        {editingName ? (
          <input
            className="trigger-node__name-input nodrag"
            autoFocus
            value={nameDraft}
            placeholder={triggerKindLabel(trigger)}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setNameDraft(trigger.name ?? "");
                setEditingName(false);
              }
            }}
          />
        ) : (
          <span
            className="trigger-node__name nodrag"
            onClick={handleNameClick}
            onDoubleClick={handleNameDoubleClick}
            title="Klik om de trigger in te stellen, dubbelklik om te hernoemen"
          >
            {trigger.name ?? triggerKindLabel(trigger)}
          </span>
        )}
        <button
          type="button"
          className="trigger-node__color-swatch nodrag"
          style={{ backgroundColor: trigger.color ?? "transparent" }}
          onClick={() => setColorPickerOpen((open) => !open)}
          title="Kleur"
          aria-label="Kleur kiezen"
        />
        {colorPickerOpen && (
          <div className="trigger-node__color-palette nodrag">
            {NODE_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className="trigger-node__color-option"
                style={{ backgroundColor: c }}
                onClick={() => {
                  onSetColor(trigger.id, c);
                  setColorPickerOpen(false);
                }}
                aria-label={`Kies kleur ${c}`}
              />
            ))}
          </div>
        )}
      </div>
      {trigger.name && <span className="trigger-node__kind">{triggerKindLabel(trigger)}</span>}
      <Handle type="source" position={Position.Right} id="out" />
    </div>
  );
}

const nodeTypes = {
  player: PlayerNodeComponent,
  source: SourceNodeComponent,
  output: OutputNodeComponent,
  trigger: TriggerNodeComponent,
};

export default function PlayerGraphCanvas({
  players, sources, branches, triggers, outputs, outputConnections, onPlayerClick, onGraphChanged, onAddPlayer,
}: Props) {
  const [popoverTrigger, setPopoverTrigger] = useState<Trigger | null>(null);

  const branchToPlayer = useMemo(
    () => Object.fromEntries(branches.map((b) => [b.id, b.player_id])),
    [branches],
  );

  const handleAddBranchTrigger = useCallback(
    async (branchId: number) => {
      await createTrigger({ from_branch_id: branchId });
      onGraphChanged();
    },
    [onGraphChanged],
  );

  const handleMakeRoot = useCallback(
    async (playerId: number) => {
      const player = players.find((p) => p.id === playerId);
      if (!player) return;
      const { id: _id, ...draft } = player;
      await updatePlayer(playerId, { ...draft, is_root: true });
      onGraphChanged();
    },
    [players, onGraphChanged],
  );

  const handleRenamePlayer = useCallback(
    async (playerId: number, name: string) => {
      const player = players.find((p) => p.id === playerId);
      if (!player) return;
      const { id: _id, ...draft } = player;
      await updatePlayer(playerId, { ...draft, name });
      onGraphChanged();
    },
    [players, onGraphChanged],
  );

  const handleSetPlayerColor = useCallback(
    async (playerId: number, color: string) => {
      const player = players.find((p) => p.id === playerId);
      if (!player) return;
      const { id: _id, ...draft } = player;
      await updatePlayer(playerId, { ...draft, color });
      onGraphChanged();
    },
    [players, onGraphChanged],
  );

  const handleTriggerClick = useCallback(
    (triggerId: number) => {
      const trigger = triggers.find((t) => t.id === triggerId);
      if (trigger) setPopoverTrigger(trigger);
    },
    [triggers],
  );

  const handleRenameTrigger = useCallback(
    async (triggerId: number, name: string) => {
      const trigger = triggers.find((t) => t.id === triggerId);
      if (!trigger) return;
      const { id: _id, ...draft } = trigger;
      await updateTrigger(triggerId, { ...draft, name: name || null });
      onGraphChanged();
    },
    [triggers, onGraphChanged],
  );

  const handleSetTriggerColor = useCallback(
    async (triggerId: number, color: string) => {
      const trigger = triggers.find((t) => t.id === triggerId);
      if (!trigger) return;
      const { id: _id, ...draft } = trigger;
      await updateTrigger(triggerId, { ...draft, color });
      onGraphChanged();
    },
    [triggers, onGraphChanged],
  );

  const flowNodes: FlowNode[] = useMemo(
    () => [
      ...players.map(
        (player): PlayerNode => ({
          id: `player-${player.id}`,
          type: "player",
          position: { x: player.canvas_x, y: player.canvas_y },
          data: {
            player,
            branches: branches.filter((b) => b.player_id === player.id),
            onPlayerClick,
            onAddBranchTrigger: handleAddBranchTrigger,
            onMakeRoot: handleMakeRoot,
            onRename: handleRenamePlayer,
            onSetColor: handleSetPlayerColor,
          },
        }),
      ),
      ...sources.map(
        (source): SourceNode => ({
          id: `source-${source.id}`,
          type: "source",
          position: { x: source.canvas_x, y: source.canvas_y },
          data: { source },
        }),
      ),
      ...outputs.map(
        (output): OutputNode => ({
          id: `output-${output.id}`,
          type: "output",
          position: { x: output.canvas_x, y: output.canvas_y },
          data: { output },
        }),
      ),
      ...triggers.map(
        (trigger): TriggerNode => ({
          id: `trigger-${trigger.id}`,
          type: "trigger",
          position: { x: trigger.canvas_x, y: trigger.canvas_y },
          data: {
            trigger,
            onTriggerClick: handleTriggerClick,
            onRename: handleRenameTrigger,
            onSetColor: handleSetTriggerColor,
          },
        }),
      ),
    ],
    [
      players, sources, outputs, triggers, branches,
      onPlayerClick, handleAddBranchTrigger, handleMakeRoot, handleRenamePlayer, handleSetPlayerColor,
      handleTriggerClick, handleRenameTrigger, handleSetTriggerColor,
    ],
  );

  const flowEdges: Edge[] = useMemo(() => {
    const result: Edge[] = [];
    for (const player of players) {
      if (player.source_id !== null) {
        result.push({
          id: `source-in-${player.id}`,
          source: `source-${player.source_id}`,
          target: `player-${player.id}`,
        });
      }
    }
    for (const trigger of triggers) {
      const fromPlayerId = branchToPlayer[trigger.from_branch_id];
      if (fromPlayerId !== undefined) {
        result.push({
          id: `branch-in-${trigger.id}`,
          source: `player-${fromPlayerId}`,
          sourceHandle: `branch-${trigger.from_branch_id}`,
          target: `trigger-${trigger.id}`,
        });
      }
      if (trigger.to_player_id !== null) {
        result.push({
          id: `out-${trigger.id}`,
          source: `trigger-${trigger.id}`,
          sourceHandle: "out",
          target: `player-${trigger.to_player_id}`,
          markerEnd: { type: MarkerType.ArrowClosed },
        });
      }
    }
    for (const oc of outputConnections) {
      const fromPlayerId = branchToPlayer[oc.from_branch_id];
      if (fromPlayerId !== undefined) {
        result.push({
          id: `oc-${oc.id}`,
          source: `player-${fromPlayerId}`,
          sourceHandle: `branch-${oc.from_branch_id}`,
          target: `output-${oc.output_id}`,
          markerEnd: { type: MarkerType.ArrowClosed },
        });
      }
    }
    return result;
  }, [players, triggers, outputConnections, branchToPlayer]);

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(flowNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(flowEdges);

  // Houdt de React Flow-state in sync zodra players/sources/etc. van de
  // server opnieuw binnenkomen (na een CRUD-actie elders) -- useNodesState/
  // useEdgesState gebruiken hun argument alleen als initiele waarde
  // (zoals useState), en houden verder hun eigen interne sleep-state bij
  // tussen renders.
  useEffect(() => {
    setNodes(flowNodes);
  }, [flowNodes, setNodes]);

  useEffect(() => {
    setRfEdges(flowEdges);
  }, [flowEdges, setRfEdges]);

  const handleConnect = useCallback(
    async (connection: Connection) => {
      if (connection.source?.startsWith("source-") && connection.target?.startsWith("player-")) {
        const sourceId = parseInt(connection.source.replace("source-", ""), 10);
        const playerId = parseInt(connection.target.replace("player-", ""), 10);
        if (Number.isNaN(sourceId) || Number.isNaN(playerId)) return;
        const player = players.find((p) => p.id === playerId);
        if (!player) return;
        const { id: _id, ...draft } = player;
        await updatePlayer(playerId, { ...draft, source_id: sourceId });
        onGraphChanged();
        return;
      }
      if (connection.source?.startsWith("trigger-") && connection.target?.startsWith("player-")) {
        const triggerId = parseInt(connection.source.replace("trigger-", ""), 10);
        const playerId = parseInt(connection.target.replace("player-", ""), 10);
        if (Number.isNaN(triggerId) || Number.isNaN(playerId)) return;
        const trigger = triggers.find((t) => t.id === triggerId);
        if (!trigger) return;
        const { id: _id, ...draft } = trigger;
        await updateTrigger(triggerId, { ...draft, to_player_id: playerId });
        onGraphChanged();
        return;
      }
      if (
        connection.source?.startsWith("player-") &&
        connection.sourceHandle?.startsWith("branch-") &&
        connection.target?.startsWith("output-")
      ) {
        const branchId = parseInt(connection.sourceHandle.replace("branch-", ""), 10);
        const outputId = parseInt(connection.target.replace("output-", ""), 10);
        if (Number.isNaN(branchId) || Number.isNaN(outputId)) return;
        await createOutputConnection(outputId, branchId);
        onGraphChanged();
      }
    },
    [players, triggers, onGraphChanged],
  );

  const handleNodeDragStop = useCallback(
    async (_event: unknown, node: FlowNode) => {
      if (node.id.startsWith("player-")) {
        await updatePlayerPosition(parseInt(node.id.replace("player-", ""), 10), node.position.x, node.position.y);
      } else if (node.id.startsWith("trigger-")) {
        await updateTriggerPosition(parseInt(node.id.replace("trigger-", ""), 10), node.position.x, node.position.y);
      } else if (node.id.startsWith("source-")) {
        const sourceId = parseInt(node.id.replace("source-", ""), 10);
        const source = sources.find((s) => s.id === sourceId);
        if (source) {
          const { id: _id, ...draft } = source;
          await updateSource(sourceId, { ...draft, canvas_x: node.position.x, canvas_y: node.position.y });
        }
      } else if (node.id.startsWith("output-")) {
        const outputId = parseInt(node.id.replace("output-", ""), 10);
        const output = outputs.find((o) => o.id === outputId);
        if (output) {
          const { id: _id, ...draft } = output;
          await updateOutput(outputId, { ...draft, canvas_x: node.position.x, canvas_y: node.position.y });
        }
      }
      // Elke branch hierboven roept onGraphChanged() aan zodra de save
      // klaar is -- zonder dit blijven players/sources/outputs in de
      // parent op de PRE-drag canvas_x/canvas_y staan, en zou de
      // eerstvolgende hernoem/kleur/kind-save de net-gesleepte positie
      // stilletjes weer terugzetten (zelfde les als eerder al gefixt
      // voor players/triggers -- nu structureel voor alle 4 knooptypes).
      onGraphChanged();
    },
    [onGraphChanged, sources, outputs],
  );

  return (
    <div className="player-graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
        onNodeDragStop={handleNodeDragStop}
        fitView
      >
        <Background />
        <Controls />
      </ReactFlow>
      <button type="button" className="player-graph-canvas__add" onClick={onAddPlayer}>
        + Nieuwe player
      </button>
      {popoverTrigger && (
        <TriggerPopover
          trigger={popoverTrigger}
          onClose={() => setPopoverTrigger(null)}
          onSaved={onGraphChanged}
        />
      )}
    </div>
  );
}
