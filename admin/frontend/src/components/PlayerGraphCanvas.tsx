import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
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
import { createTrigger, updateTrigger, updateTriggerPosition, deleteTrigger } from "../api/triggers";
import { updatePlayer, updatePlayerPosition, deletePlayer } from "../api/players";
import { updateSource, deleteSource, createSource } from "../api/sources";
import { updateOutput, deleteOutput, createOutput } from "../api/outputs";
import { createPlayerBranch } from "../api/branches";
import { createOutputConnection, deleteOutputConnection } from "../api/outputConnections";
import { ApiError } from "../api/client";
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
  audioSourceName: string | null;
  onPlayerClick: Props["onPlayerClick"];
  onAddBranchTrigger: (branchId: number) => void;
  onMakeRoot: (playerId: number) => void;
  onRename: (playerId: number, name: string) => void;
  onSetColor: (playerId: number, color: string) => void;
  onDelete: (playerId: number) => void;
  [key: string]: unknown;
};

type SourceNodeData = { source: Source; onDelete: (sourceId: number) => void; [key: string]: unknown };
type OutputNodeData = { output: Output; onDelete: (outputId: number) => void; [key: string]: unknown };

type TriggerNodeData = {
  trigger: Trigger;
  onTriggerClick: (triggerId: number) => void;
  onRename: (triggerId: number, name: string) => void;
  onSetColor: (triggerId: number, color: string) => void;
  onDelete: (triggerId: number) => void;
  [key: string]: unknown;
};

// Rechtsklik-menu, gedeeld door alle vier de knooptypes -- lokale open/dicht-
// state blijft per node-component (zelfde patroon als het kleur-palet
// hierboven), alleen de popup zelf is gemeenschappelijk. Vast gepositioneerd
// op de muiscoordinaten (niet geankerd aan de node) zodat 'ie nooit buiten
// een kleine node-breedte clipt.
function NodeContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number;
  y: number;
  items: { label: string; onSelect: () => void }[];
  onClose: () => void;
}) {
  useEffect(() => {
    function handleClickAway() {
      onClose();
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("click", handleClickAway);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("click", handleClickAway);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [onClose]);

  // Portal naar document.body: React Flow's pane heeft een CSS transform
  // (voor pan/zoom), en position:fixed op een nakomeling van een
  // getransformeerd element rekent niet meer t.o.v. de echte viewport maar
  // t.o.v. die getransformeerde ouder -- zonder portal staat het menu dus
  // steeds verder van de cursor af naarmate er meer gepand/gezoomd is.
  return createPortal(
    <div
      className="node-context-menu nodrag"
      style={{ position: "fixed", left: x, top: y }}
      onClick={(e) => e.stopPropagation()}
    >
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          className="node-context-menu__item"
          onClick={() => {
            item.onSelect();
            onClose();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>,
    document.body,
  );
}

// @xyflow/react's Node<T> constrains T to Record<string, unknown>; the
// index signatures above satisfy that constraint for our data payloads.
type PlayerNode = Node<PlayerNodeData, "player">;
type SourceNode = Node<SourceNodeData, "source">;
type OutputNode = Node<OutputNodeData, "output">;
type TriggerNode = Node<TriggerNodeData, "trigger">;
type FlowNode = PlayerNode | SourceNode | OutputNode | TriggerNode;

// Geëxporteerd als pure functie (i.p.v. inline in de canvas-event-handler)
// zodat de id-herkenning zelf getest kan worden zonder een volledige
// ReactFlow-render nodig te hebben (edges/handles krijgen in jsdom nooit
// afmetingen, dus renderen niet -- zie PlayerGraphCanvas.test.tsx).
export function parseOutputConnectionEdgeIds(edges: Edge[]): number[] {
  return edges
    .filter((edge) => edge.id.startsWith("oc-"))
    .map((edge) => parseInt(edge.id.replace("oc-", ""), 10))
    .filter((id) => !Number.isNaN(id));
}

// Bepaalt welk player-veld een gesleepte source->player-verbinding moet
// updaten. Als losstaande pure functie (i.p.v. inline in handleConnect)
// zodat de routeringslogica getest kan worden zonder een echte ReactFlow-
// sleepverbinding te hoeven simuleren -- zelfde reden als
// parseOutputConnectionEdgeIds hierboven (edges/handles krijgen in jsdom
// nooit afmetingen, dus renderen niet).
export function resolveSourceConnectionUpdate(source: Source): Partial<Player> {
  return source.kind === "audio" ? { audio_source_id: source.id } : { source_id: source.id };
}

function triggerKindLabel(trigger: Trigger): string {
  if (trigger.kind === "always") return "Altijd";
  if (trigger.kind === "motion") return "Beweging";
  if (trigger.kind === "schedule") return `${trigger.schedule_from ?? "?"}–${trigger.schedule_until ?? "?"}`;
  if (trigger.kind === "ha_sensor") return trigger.ha_entity_id ?? "HA-sensor";
  return "Nog niet ingesteld";
}

function PlayerNodeComponent({ data }: NodeProps<PlayerNode>) {
  const { player, branches, audioSourceName, onPlayerClick, onAddBranchTrigger, onMakeRoot, onRename, onSetColor, onDelete } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(player.name);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const clickTimerRef = useRef<number | null>(null);

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  }

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
      onContextMenu={handleContextMenu}
    >
      <Handle type="target" position={Position.Left} id="video-in" />
      <Handle type="target" position={Position.Top} id="audio-in" />
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
        {audioSourceName && (
          <span className="player-node__chip player-node__chip--audio nodrag" title="Gekoppelde audio-source">
            🔊 {audioSourceName}
          </span>
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
      {contextMenu && (
        <NodeContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          items={[
            { label: "Bewerken", onSelect: () => onPlayerClick(player.id, "input") },
            { label: "Verwijderen", onSelect: () => onDelete(player.id) },
          ]}
        />
      )}
    </div>
  );
}

function sourceIcon(kind: Source["kind"]): string {
  if (kind === "camera_stream") return "📷";
  if (kind === "static_image") return "🖼";
  if (kind === "video_loop") return "🎞";
  return "🔊"; // audio
}

function SourceNodeComponent({ data }: NodeProps<SourceNode>) {
  const { source, onDelete } = data;
  const navigate = useNavigate();
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  }

  return (
    <div className="source-node" onContextMenu={handleContextMenu}>
      <div className="source-node__header">
        <span className="source-node__icon">{sourceIcon(source.kind)}</span>
        <span className="source-node__name">{source.name}</span>
      </div>
      <Handle type="source" position={Position.Right} />
      {contextMenu && (
        <NodeContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          items={[
            { label: "Bewerken", onSelect: () => navigate("/sources") },
            { label: "Verwijderen", onSelect: () => onDelete(source.id) },
          ]}
        />
      )}
    </div>
  );
}

function OutputNodeComponent({ data }: NodeProps<OutputNode>) {
  const { output, onDelete } = data;
  const navigate = useNavigate();
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  }

  return (
    <div className="output-node" onContextMenu={handleContextMenu}>
      <Handle type="target" position={Position.Left} />
      <div className="output-node__header">
        <span className="output-node__icon">🖥</span>
        <span className="output-node__name">{output.name}</span>
      </div>
      {contextMenu && (
        <NodeContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          items={[
            { label: "Bewerken", onSelect: () => navigate("/outputs") },
            { label: "Verwijderen", onSelect: () => onDelete(output.id) },
          ]}
        />
      )}
    </div>
  );
}

function TriggerNodeComponent({ data }: NodeProps<TriggerNode>) {
  const { trigger, onTriggerClick, onRename, onSetColor, onDelete } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(trigger.name ?? "");
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const clickTimerRef = useRef<number | null>(null);

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  }

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
      onContextMenu={handleContextMenu}
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
      {contextMenu && (
        <NodeContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          items={[
            { label: "Bewerken", onSelect: () => onTriggerClick(trigger.id) },
            { label: "Verwijderen", onSelect: () => onDelete(trigger.id) },
          ]}
        />
      )}
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
  const [addTriggerOpen, setAddTriggerOpen] = useState(false);
  const [addTriggerBranchId, setAddTriggerBranchId] = useState<number | "">("");

  const branchToPlayer = useMemo(
    () => Object.fromEntries(branches.map((b) => [b.id, b.player_id])),
    [branches],
  );

  const audioSourceNameById = useMemo(
    () => Object.fromEntries(sources.filter((s) => s.kind === "audio").map((s) => [s.id, s.name])),
    [sources],
  );

  const handleAddBranchTrigger = useCallback(
    async (branchId: number) => {
      await createTrigger({ from_branch_id: branchId });
      onGraphChanged();
    },
    [onGraphChanged],
  );

  // ponytail: elke branch heeft precies één eigenaar-player, en elke player
  // heeft server-side al minstens één branch (auto-aangemaakt bij creatie) --
  // dus zodra er players bestaan, bestaan er ook branches om uit te kiezen.
  const branchOptions = useMemo(
    () =>
      branches.map((branch) => {
        const player = players.find((p) => p.id === branch.player_id);
        return { id: branch.id, label: `${player?.name ?? "?"} → ${branch.name}` };
      }),
    [branches, players],
  );

  const handleCreateTriggerFromPicker = useCallback(async () => {
    if (addTriggerBranchId === "") return;
    await createTrigger({ from_branch_id: addTriggerBranchId });
    setAddTriggerOpen(false);
    setAddTriggerBranchId("");
    onGraphChanged();
  }, [addTriggerBranchId, onGraphChanged]);

  const handleAddSource = useCallback(async () => {
    await createSource({ name: "Nieuwe source", kind: "camera_stream", value: "", canvas_x: 0, canvas_y: 0 });
    onGraphChanged();
  }, [onGraphChanged]);

  const handleAddOutput = useCallback(async () => {
    await createOutput({ name: "Nieuwe output", camera_source: "", canvas_x: 0, canvas_y: 0 });
    onGraphChanged();
  }, [onGraphChanged]);

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

  // Rechtsklik-verwijderen: geen apart bevestigingsscherm op het canvas
  // (net als de bestaande Sources/Outputs-pagina's) -- de backend-guards
  // (nog-in-gebruik) zijn de echte bescherming, hun foutmelding komt via
  // window.alert terecht, zelfde bericht-tekst als ApiError elders al geeft.
  const handleDeletePlayer = useCallback(
    async (playerId: number) => {
      try {
        await deletePlayer(playerId);
        onGraphChanged();
      } catch (err) {
        window.alert(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
      }
    },
    [onGraphChanged],
  );

  const handleDeleteTrigger = useCallback(
    async (triggerId: number) => {
      try {
        await deleteTrigger(triggerId);
        onGraphChanged();
      } catch (err) {
        window.alert(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
      }
    },
    [onGraphChanged],
  );

  const handleDeleteSource = useCallback(
    async (sourceId: number) => {
      try {
        await deleteSource(sourceId);
        onGraphChanged();
      } catch (err) {
        window.alert(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
      }
    },
    [onGraphChanged],
  );

  const handleDeleteOutput = useCallback(
    async (outputId: number) => {
      try {
        await deleteOutput(outputId);
        onGraphChanged();
      } catch (err) {
        window.alert(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
      }
    },
    [onGraphChanged],
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
            audioSourceName: player.audio_source_id !== null ? audioSourceNameById[player.audio_source_id] ?? null : null,
            onPlayerClick,
            onAddBranchTrigger: handleAddBranchTrigger,
            onMakeRoot: handleMakeRoot,
            onRename: handleRenamePlayer,
            onSetColor: handleSetPlayerColor,
            onDelete: handleDeletePlayer,
          },
        }),
      ),
      ...sources.map(
        (source): SourceNode => ({
          id: `source-${source.id}`,
          type: "source",
          position: { x: source.canvas_x, y: source.canvas_y },
          data: { source, onDelete: handleDeleteSource },
        }),
      ),
      ...outputs.map(
        (output): OutputNode => ({
          id: `output-${output.id}`,
          type: "output",
          position: { x: output.canvas_x, y: output.canvas_y },
          data: { output, onDelete: handleDeleteOutput },
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
            onDelete: handleDeleteTrigger,
          },
        }),
      ),
    ],
    [
      players, sources, outputs, triggers, branches, audioSourceNameById,
      onPlayerClick, handleAddBranchTrigger, handleMakeRoot, handleRenamePlayer, handleSetPlayerColor,
      handleTriggerClick, handleRenameTrigger, handleSetTriggerColor,
      handleDeletePlayer, handleDeleteSource, handleDeleteOutput, handleDeleteTrigger,
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
          targetHandle: "video-in",
        });
      }
      if (player.audio_source_id !== null) {
        result.push({
          id: `audio-in-${player.id}`,
          source: `source-${player.audio_source_id}`,
          target: `player-${player.id}`,
          targetHandle: "audio-in",
          style: { strokeDasharray: "4 2" },
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
        const source = sources.find((s) => s.id === sourceId);
        if (!player || !source) return;
        const { id: _id, ...draft } = player;
        await updatePlayer(playerId, { ...draft, ...resolveSourceConnectionUpdate(source) });
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
    [players, sources, triggers, onGraphChanged],
  );

  const handleEdgesDelete = useCallback(
    async (edges: Edge[]) => {
      // onEdgesChange (hieronder) update alleen React Flow's lokale state --
      // een edge verwijderd via de canvas verdwijnt dan visueel tot de
      // volgende refreshGraph()/onGraphChanged(), waarna 'ie terugkomt
      // omdat de backend-rij nooit verwijderd is. Alleen output-
      // connection-edges (id-prefix "oc-") hebben een eigen delete-route;
      // andere edge-typen (source-in-/branch-in-/out-) worden elders al
      // via hun eigen create/update-routes beheerd.
      const outputConnectionIds = parseOutputConnectionEdgeIds(edges);
      if (outputConnectionIds.length === 0) return;
      await Promise.all(outputConnectionIds.map((id) => deleteOutputConnection(id)));
      onGraphChanged();
    },
    [onGraphChanged],
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
        onEdgesDelete={handleEdgesDelete}
        onConnect={handleConnect}
        onNodeDragStop={handleNodeDragStop}
        fitView
      >
        <Background />
        <Controls />
      </ReactFlow>
      <div className="player-graph-canvas__toolbar">
        <button type="button" className="player-graph-canvas__add" onClick={onAddPlayer}>
          + Nieuwe player
        </button>
        <button type="button" className="player-graph-canvas__add" onClick={handleAddSource}>
          + Nieuwe source
        </button>
        <button type="button" className="player-graph-canvas__add" onClick={handleAddOutput}>
          + Nieuwe output
        </button>
        <button
          type="button"
          className="player-graph-canvas__add"
          disabled={branchOptions.length === 0}
          title={branchOptions.length === 0 ? "Maak eerst een player aan" : undefined}
          onClick={() => setAddTriggerOpen((open) => !open)}
        >
          + Nieuwe trigger
        </button>
        {addTriggerOpen && (
          <div className="player-graph-canvas__add-trigger-picker">
            <select
              value={addTriggerBranchId}
              onChange={(e) => setAddTriggerBranchId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">— kies een aftakking —</option>
              {branchOptions.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </select>
            <button type="button" onClick={handleCreateTriggerFromPicker} disabled={addTriggerBranchId === ""}>
              Aanmaken
            </button>
          </div>
        )}
      </div>
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
