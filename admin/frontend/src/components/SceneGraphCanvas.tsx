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
import { updateScene, updateScenePosition } from "../api/scenes";
import TriggerPopover from "./TriggerPopover";
import type { Scene, Trigger } from "../types";
import "./SceneGraphCanvas.css";

const NODE_COLORS = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6", "#95a5a6"];

interface Props {
  scenes: Scene[];
  triggers: Trigger[];
  onSceneClick: (sceneId: number, step: "input" | "animation" | "output") => void;
  onGraphChanged: () => void;
  onAddScene: () => void;
}

type SceneNodeData = {
  scene: Scene;
  onSceneClick: Props["onSceneClick"];
  onAddOutput: (fromSceneId: number) => void;
  onMakeRoot: (sceneId: number) => void;
  onRename: (sceneId: number, name: string) => void;
  onSetColor: (sceneId: number, color: string) => void;
  [key: string]: unknown;
};

type TriggerNodeData = {
  trigger: Trigger;
  onTriggerClick: (triggerId: number) => void;
  onRename: (triggerId: number, name: string) => void;
  onSetColor: (triggerId: number, color: string) => void;
  [key: string]: unknown;
};

// @xyflow/react's Node<T> constrains T to Record<string, unknown>; the
// index signatures above satisfy that constraint for our data payloads.
type SceneNode = Node<SceneNodeData, "scene">;
type TriggerNode = Node<TriggerNodeData, "trigger">;
type FlowNode = SceneNode | TriggerNode;

function triggerKindLabel(trigger: Trigger): string {
  if (trigger.kind === "always") return "Altijd";
  if (trigger.kind === "motion") return "Beweging";
  if (trigger.kind === "schedule") return `${trigger.schedule_from ?? "?"}–${trigger.schedule_until ?? "?"}`;
  if (trigger.kind === "ha_sensor") return trigger.ha_entity_id ?? "HA-sensor";
  return "Nog niet ingesteld";
}

function SceneNodeComponent({ data }: NodeProps<SceneNode>) {
  const { scene, onSceneClick, onAddOutput, onMakeRoot, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(scene.name);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const clickTimerRef = useRef<number | null>(null);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed && trimmed !== scene.name) {
      onRename(scene.id, trimmed);
    } else {
      setNameDraft(scene.name);
    }
  }

  // ponytail: dblclick fires click+click+dblclick per DOM spec; delay the
  // single-click action so dblclick can cancel it before it opens the wizard.
  function handleNameClick() {
    if (clickTimerRef.current !== null) return;
    clickTimerRef.current = window.setTimeout(() => {
      onSceneClick(scene.id, "input");
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
      className="scene-node"
      data-root={scene.is_root}
      style={scene.color ? { borderColor: scene.color } : undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="scene-node__header">
        <button
          type="button"
          className="scene-node__root nodrag"
          onClick={() => onMakeRoot(scene.id)}
          title="Maak root"
        >
          {scene.is_root ? "★" : "☆"}
        </button>
        {editingName ? (
          <input
            className="scene-node__name-input nodrag"
            autoFocus
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setNameDraft(scene.name);
                setEditingName(false);
              }
            }}
          />
        ) : (
          <span
            className="scene-node__name nodrag"
            onClick={handleNameClick}
            onDoubleClick={handleNameDoubleClick}
            title="Klik voor instellingen, dubbelklik om te hernoemen"
          >
            {scene.name}
          </span>
        )}
        <button
          type="button"
          className="scene-node__color-swatch nodrag"
          style={{ backgroundColor: scene.color ?? "transparent" }}
          onClick={() => setColorPickerOpen((open) => !open)}
          title="Kleur"
          aria-label="Kleur kiezen"
        />
        {colorPickerOpen && (
          <div className="scene-node__color-palette nodrag">
            {NODE_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className="scene-node__color-option"
                style={{ backgroundColor: c }}
                onClick={() => {
                  onSetColor(scene.id, c);
                  setColorPickerOpen(false);
                }}
                aria-label={`Kies kleur ${c}`}
              />
            ))}
          </div>
        )}
      </div>
      <div className="scene-node__chips">
        <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "input")}>
          {scene.source_mode === "camera" ? "Camera" : "Scare-video"}
        </span>
        {scene.source_mode === "camera" && (
          <>
            <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "animation")}>
              {scene.effect}
            </span>
            <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "output")}>
              Weergave
            </span>
          </>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
      <button type="button" className="scene-node__add-output nodrag" onClick={() => onAddOutput(scene.id)}>
        + output
      </button>
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

  // ponytail: same click/dblclick disambiguation as SceneNodeComponent --
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

const nodeTypes = { scene: SceneNodeComponent, trigger: TriggerNodeComponent };

export default function SceneGraphCanvas({ scenes, triggers, onSceneClick, onGraphChanged, onAddScene }: Props) {
  const [popoverTrigger, setPopoverTrigger] = useState<Trigger | null>(null);

  const handleAddOutput = useCallback(
    async (fromSceneId: number) => {
      await createTrigger({ from_scene_id: fromSceneId });
      onGraphChanged();
    },
    [onGraphChanged],
  );

  const handleMakeRoot = useCallback(
    async (sceneId: number) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, is_root: true });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
  );

  const handleRenameScene = useCallback(
    async (sceneId: number, name: string) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, name });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
  );

  const handleSetSceneColor = useCallback(
    async (sceneId: number, color: string) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, color });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
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
      ...scenes.map(
        (scene): SceneNode => ({
          id: `scene-${scene.id}`,
          type: "scene",
          position: { x: scene.canvas_x, y: scene.canvas_y },
          data: {
            scene,
            onSceneClick,
            onAddOutput: handleAddOutput,
            onMakeRoot: handleMakeRoot,
            onRename: handleRenameScene,
            onSetColor: handleSetSceneColor,
          },
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
      scenes,
      triggers,
      onSceneClick,
      handleAddOutput,
      handleMakeRoot,
      handleRenameScene,
      handleSetSceneColor,
      handleTriggerClick,
      handleRenameTrigger,
      handleSetTriggerColor,
    ],
  );

  const flowEdges: Edge[] = useMemo(() => {
    const result: Edge[] = [];
    for (const trigger of triggers) {
      result.push({
        id: `in-${trigger.id}`,
        source: `scene-${trigger.from_scene_id}`,
        target: `trigger-${trigger.id}`,
      });
      if (trigger.to_scene_id !== null) {
        result.push({
          id: `out-${trigger.id}`,
          source: `trigger-${trigger.id}`,
          sourceHandle: "out",
          target: `scene-${trigger.to_scene_id}`,
          markerEnd: { type: MarkerType.ArrowClosed },
        });
      }
    }
    return result;
  }, [triggers]);

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(flowNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(flowEdges);

  // Houdt de React Flow-state in sync zodra scenes/triggers van de server
  // opnieuw binnenkomen (na een CRUD-actie elders) -- useNodesState/
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
      if (!connection.source?.startsWith("trigger-") || !connection.target?.startsWith("scene-")) return;
      const triggerId = parseInt(connection.source.replace("trigger-", ""), 10);
      const sceneId = parseInt(connection.target.replace("scene-", ""), 10);
      if (Number.isNaN(triggerId) || Number.isNaN(sceneId)) return;
      const trigger = triggers.find((t) => t.id === triggerId);
      if (!trigger) return;
      const { id: _id, ...draft } = trigger;
      await updateTrigger(triggerId, { ...draft, to_scene_id: sceneId });
      onGraphChanged();
    },
    [triggers, onGraphChanged],
  );

  const handleNodeDragStop = useCallback(
    async (_event: unknown, node: FlowNode) => {
      if (node.id.startsWith("scene-")) {
        await updateScenePosition(parseInt(node.id.replace("scene-", ""), 10), node.position.x, node.position.y);
      } else {
        await updateTriggerPosition(parseInt(node.id.replace("trigger-", ""), 10), node.position.x, node.position.y);
      }
      // Zonder dit blijven scenes/triggers in de parent op de PRE-drag
      // canvas_x/canvas_y staan -- elke andere save in dit bestand bouwt
      // z'n PUT-payload door het bestaande scene/trigger-object te
      // spreiden, dus de eerstvolgende hernoem/kleur/kind-save zou de
      // net-gesleepte positie stilletjes weer terugzetten.
      onGraphChanged();
    },
    [onGraphChanged],
  );

  return (
    <div className="scene-graph-canvas">
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
      <button type="button" className="scene-graph-canvas__add" onClick={onAddScene}>
        + Nieuwe scene
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
