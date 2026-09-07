import { statusColors } from "../theme";
import type { TraiteStatut } from "../api/types";

export default function StatusBadge({ statut }: { statut: TraiteStatut }) {
  const palette = statusColors[statut] ?? statusColors["À traiter"];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: 11,
        color: palette.fg,
        background: palette.bg,
        border: `1px solid ${palette.border}`,
      }}
    >
      {statut}
    </span>
  );
}
