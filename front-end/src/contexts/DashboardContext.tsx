import { createContext, useContext, useEffect, useState } from "react";
import { useDashboardPoll } from "@Shore/hooks/useDashboardPoll";

const CPU_BARS = 28;

type PollValue = ReturnType<typeof useDashboardPoll>;
type DashboardContextValue = PollValue & {
  localCpuHistory: number[];
  gpuUtilHistory: number[];
};

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const poll = useDashboardPoll();
  const [localCpuHistory, setLocalCpuHistory] = useState<number[]>([]);
  const [gpuUtilHistory, setGpuUtilHistory] = useState<number[]>([]);

  useEffect(() => {
    if (poll.data?.hardware.cpu_pct != null) {
      setLocalCpuHistory(prev => [...prev.slice(-(CPU_BARS - 1)), poll.data!.hardware.cpu_pct!]);
    }
    const util = poll.data?.hardware.gpu[0]?.util_pct;
    if (util != null) {
      setGpuUtilHistory(prev => [...prev.slice(-(CPU_BARS - 1)), util]);
    }
  }, [poll.data]);

  return (
    <DashboardContext.Provider value={{ ...poll, localCpuHistory, gpuUtilHistory }}>
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboardContext(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboardContext must be used within DashboardProvider");
  return ctx;
}
