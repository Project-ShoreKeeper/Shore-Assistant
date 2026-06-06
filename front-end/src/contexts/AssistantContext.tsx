import { createContext, useContext } from "react";
import { useAssistant } from "@Shore/hooks/useAssistant";

type AssistantContextValue = ReturnType<typeof useAssistant>;

const AssistantContext = createContext<AssistantContextValue | null>(null);

export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const value = useAssistant();
  return (
    <AssistantContext.Provider value={value}>
      {children}
    </AssistantContext.Provider>
  );
}

export function useAssistantContext(): AssistantContextValue {
  const ctx = useContext(AssistantContext);
  if (!ctx) throw new Error("useAssistantContext must be used within AssistantProvider");
  return ctx;
}
