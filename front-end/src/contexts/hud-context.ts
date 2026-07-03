import { createContext } from "react";

export interface HudContextValue {
  enabled: boolean;
  error: string | null;
  setEnabled: (enabled: boolean) => Promise<void>;
}

export const HudContext = createContext<HudContextValue | null>(null);
