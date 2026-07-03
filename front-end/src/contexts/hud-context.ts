import { createContext } from "react";

export interface HudContextValue {
  enabled: boolean;
  error: string | null;
  setEnabled: (enabled: boolean) => Promise<void>;
  navigationTarget: HudNavigationTarget | null;
  clearNavigationTarget: (requestId: string) => void;
}

export interface HudNavigationTarget {
  requestId: string;
  destination: "chat" | "settings" | "terminal";
  messageId?: string;
}

export const HudContext = createContext<HudContextValue | null>(null);
