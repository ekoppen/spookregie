import "./NodeStatusCard.css";

interface Props {
  name: string;
  status: "online" | "offline";
}

export default function NodeStatusCard({ name, status }: Props) {
  const isOnline = status === "online";
  return (
    <div className="node-card" data-status={status}>
      <span className="node-card__number" aria-hidden="true" />
      <span className={`node-card__led ${isOnline ? "node-card__led--on" : "node-card__led--off"}`} aria-hidden="true" />
      <span className="node-card__name">{name}</span>
      <span className="node-card__status">{status === "online" ? "online" : "offline"}</span>
      <span className={`node-card__rocker ${isOnline ? "node-card__rocker--on" : "node-card__rocker--off"}`} aria-hidden="true" />
    </div>
  );
}
