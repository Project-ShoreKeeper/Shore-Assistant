import { useContext } from "react";

import { HudContext } from "@Shore/contexts/hud-context";

export function useHud() {
  const context = useContext(HudContext);
  if (!context) throw new Error("useHud must be used within HudProvider");
  return context;
}
