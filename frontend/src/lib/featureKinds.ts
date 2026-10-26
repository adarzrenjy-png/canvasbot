// Icons and plain-English explanations for each kind of feature.
import {
  Box,
  CircleDot,
  Combine,
  FlipHorizontal2,
  Grid3x3,
  Layers,
  type LucideIcon,
  PenLine,
  RotateCw,
  Rows3,
  Shapes,
  Spline,
  Square,
  Triangle,
  Waypoints,
} from "lucide-react";

export const ICONS: Record<string, LucideIcon> = {
  sketch: PenLine,
  extrude: Box,
  revolve: RotateCw,
  loft: Layers,
  sweep: Waypoints,
  fillet: Spline,
  chamfer: Triangle,
  hole: CircleDot,
  shell: Square,
  pattern: Grid3x3,
  mirror: FlipHorizontal2,
  boolean: Combine,
  rib: Rows3,
  other: Shapes,
};

export const KIND_TIPS: Record<string, string> = {
  extrude: "Extrude: pushes a flat profile out into a solid.",
  fillet: "Fillet: rounds a sharp edge. Inside fillets spread stress and make parts stronger.",
  chamfer: "Chamfer: cuts a sharp edge at an angle.",
  hole: "Hole: a round cut, usually for a bolt or shaft.",
  shell: "Shell: hollows a solid, leaving walls of a set thickness.",
  pattern: "Pattern: repeats a feature in a row or circle.",
  revolve: "Revolve: spins a profile around an axis.",
};
