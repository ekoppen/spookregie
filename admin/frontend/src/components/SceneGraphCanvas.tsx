import { useCallback, useEffect, useMemo, useState } from "react";
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
import {
  createSceneEdge,
  updateSceneEdge,
} from "../api/sceneEdges";
import { updateScene, updateScenePosition } from "../api/scenes";
import EdgeTriggerPopover from "./EdgeTriggerPopover";
import type { Scene, SceneEdge } from "../types";
import "./SceneGraphCanvas.css";

const NODE_COLORS = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6", "#95a5a6"];

interface Props {
  scenes: Scene[];
  edges: SceneEdge[];
  onSceneClick: (sceneId: number, step: "input" | "animation" | "output") => void;
  onGraphChanged: () => void;
  onAddScene: () => void;
}

type SceneNodeData = {
  scene: Scene;
  outputs: SceneEdge[];
  onSceneClick: Props["onSceneClick"];
  onAddOutput: (fromSceneId: number) => void;
  onMakeRoot: (sceneId: number) => void;
  onRename: (sceneId: number, name: string) => void;
  onSetColor: (sceneId: number, color: string) => void;
  [key: string]: unknown;
};

// @xyflow/react's Node<T> constrains T to Record<string, unknown>; the
// index signature above satisfies that constraint for our data payload.
type SceneNode = Node<SceneNodeData, "scene">;

function triggerLabel(edge: SceneEdge): string {
  if (edge.trigger_type === "always") return "Altijd";
  if (edge.trigger_type === "motion") return "Beweging";
  if (edge.trigger_type === "schedule") return `${edge.trigger_from ?? "?"}–${edge.trigger_until ?? "?"}`;
  return "Nog niet ingesteld";
}

function SceneNodeComponent({ data }: NodeProps<SceneNode>) {
  const { scene, outputs, onSceneClick, onAddOutput, onMakeRoot, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(scene.name);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed && trimmed !== scene.name) {
      onRename(scene.id, trimmed);
    } else {
      setNameDraft(scene.name);
    }
  }

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
            onClick={() => onSceneClick(scene.id, "input")}
            onDoubleClick={() => setEditingName(true)}
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
      <div className="scene-node__outputs">
        {outputs.map((edge, i) => (
          <div key={edge.id} className="scene-node__output" style={{ top: `${40 + i * 24}px` }}>
            <span className="scene-node__output-label">
              {edge.to_scene_id === null ? "leeg" : triggerLabel(edge)}
            </span>
            <Handle
              type="source"
              position={Position.Right}
              id={`output-${edge.id}`}
            />
          </div>
        ))}
      </div>
      <button type="button" className="scene-node__add-output nodrag" onClick={() => onAddOutput(scene.id)}>
        + output
      </button>
    </div>
  );
}

const nodeTypes = { scene: SceneNodeComponent };

export default function SceneGraphCanvas({ scenes, edges, onSceneClick, onGraphChanged, onAddScene }: Props) {
  const [popoverEdge, setPopoverEdge] = useState<SceneEdge | null>(null);

  const handleAddOutput = useCallback(
    async (fromSceneId: number) => {
      await createSceneEdge({ from_scene_id: fromSceneId });
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

  const handleRename = useCallback(
    async (sceneId: number, name: string) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, name });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
  );

  const handleSetColor = useCallback(
    async (sceneId: number, color: string) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, color });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
  );

  const flowNodes: SceneNode[] = useMemo(
    () =>
      scenes.map((scene) => ({
        id: String(scene.id),
        type: "scene",
        position: { x: scene.canvas_x, y: scene.canvas_y },
        data: {
          scene,
          outputs: edges.filter((e) => e.from_scene_id === scene.id),
          onSceneClick,
          onAddOutput: handleAddOutput,
          onMakeRoot: handleMakeRoot,
          onRename: handleRename,
          onSetColor: handleSetColor,
        },
      })),
    [scenes, edges, onSceneClick, handleAddOutput, handleMakeRoot, handleRename, handleSetColor],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      edges
        .filter((e) => e.to_scene_id !== null)
        .map((e) => ({
          id: String(e.id),
          source: String(e.from_scene_id),
          sourceHandle: `output-${e.id}`,
          target: String(e.to_scene_id),
          label: triggerLabel(e),
          markerEnd: { type: MarkerType.ArrowClosed },
          data: { edge: e },
        })),
    [edges],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(flowEdges);

  // Houdt de React Flow-state in sync zodra scenes/edges van de server
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
      if (!connection.sourceHandle || !connection.target) return;
      const edgeId = parseInt(connection.sourceHandle.replace("output-", ""), 10);
      if (Number.isNaN(edgeId)) return;
      const edge = edges.find((e) => e.id === edgeId);
      if (!edge) return;
      await updateSceneEdge(edgeId, {
        from_scene_id: edge.from_scene_id,
        to_scene_id: parseInt(connection.target, 10),
        trigger_type: edge.trigger_type,
        trigger_from: edge.trigger_from,
        trigger_until: edge.trigger_until,
        priority: edge.priority,
      });
      onGraphChanged();
    },
    [edges, onGraphChanged],
  );

  const handleNodeDragStop = useCallback(
    async (_event: unknown, node: SceneNode) => {
      await updateScenePosition(parseInt(node.id, 10), node.position.x, node.position.y);
    },
    [],
  );

  const handleEdgeClick = useCallback(
    (_event: unknown, edge: Edge) => {
      const real = edges.find((e) => String(e.id) === edge.id);
      if (real) setPopoverEdge(real);
    },
    [edges],
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
        onEdgeClick={handleEdgeClick}
        fitView
      >
        <Background />
        <Controls />
      </ReactFlow>
      <button type="button" className="scene-graph-canvas__add" onClick={onAddScene}>
        + Nieuwe scene
      </button>
      {popoverEdge && (
        <EdgeTriggerPopover
          edge={popoverEdge}
          onClose={() => setPopoverEdge(null)}
          onSaved={onGraphChanged}
        />
      )}
    </div>
  );
}
