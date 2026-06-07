/**
 * Start/Stop button overlay for a dashboard service card.
 *
 * - Renders nothing if `control` is null (service not in registry).
 * - Stop click → confirm dialog → POST /api/services/{name}/stop.
 * - Start click → POST directly, no confirm.
 * - After dispatch, calls `expedite()` on the dashboard poll so the snapshot
 *   refreshes quickly and reflects `transitioning=true`.
 */
import { useState } from "react";
import { Button, Dialog, Flex, Text } from "@radix-ui/themes";

import type { ServiceControl } from "@Shore/services/dashboard.service";
import { servicesApi, ServicesApiError } from "@Shore/services/services-api.service";

interface Props {
  control: ServiceControl;
  /** Triggers the dashboard poll to refresh immediately + accelerate. */
  expedite: () => void;
  /** Optional override for the human-readable service label in messages. */
  displayName?: string;
}

export default function ServiceControlButton({ control, expedite, displayName }: Props) {
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const isRunning = control.running;
  const isTransitioning = control.transitioning || busy;
  const label = displayName ?? control.name;

  const handleStart = async () => {
    setBusy(true);
    setLocalError(null);
    try {
      await servicesApi.start(control.name);
      expedite();
    } catch (e) {
      setLocalError(e instanceof ServicesApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setBusy(true);
    setLocalError(null);
    try {
      await servicesApi.stop(control.name);
      expedite();
    } catch (e) {
      setLocalError(e instanceof ServicesApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Compact style — chips visually balance the StatusBadge on the right.
  const baseStyle: React.CSSProperties = {
    fontFamily: "Inter, sans-serif",
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.3,
    padding: "2px 8px",
    borderRadius: 9999,
    border: "1px solid",
    background: "transparent",
    cursor: isTransitioning ? "default" : "pointer",
    whiteSpace: "nowrap",
    height: 20,
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
  };

  if (isTransitioning) {
    return (
      <span style={{
        ...baseStyle,
        borderColor: "var(--md-outline-variant)",
        color: "var(--md-on-surface-variant)",
        cursor: "default",
      }}>
        {isRunning ? "STOPPING…" : "STARTING…"}
      </span>
    );
  }

  if (!isRunning) {
    return (
      <>
        <button
          onClick={handleStart}
          title={localError ? `Last error: ${localError}` : `Start ${label}`}
          style={{
            ...baseStyle,
            borderColor: localError ? "#ba1a1a" : "#006d4b",
            color: localError ? "#ba1a1a" : "#006d4b",
          }}
        >
          START
        </button>
      </>
    );
  }

  return (
    <Dialog.Root>
      <Dialog.Trigger>
        <button
          title={localError ? `Last error: ${localError}` : `Stop ${label}`}
          style={{
            ...baseStyle,
            borderColor: localError ? "#ba1a1a" : "#ba1a1a",
            color: "#ba1a1a",
          }}
        >
          STOP
        </button>
      </Dialog.Trigger>
      <Dialog.Content style={{ maxWidth: 420 }}>
        <Dialog.Title>Stop &ldquo;{label}&rdquo;?</Dialog.Title>
        <Dialog.Description size="2" mb="4">
          {control.kind === "process"
            ? "This will terminate the process and release any VRAM it holds. Active chats may fail until you start it again."
            : control.kind === "docker"
              ? "This will stop the Docker container. Any dependent feature (chat, memory) will degrade until you start it again."
              : control.kind === "remote"
                ? "This will ask the remote supervisor to stop the service. STT, TTS, and embedding features will degrade until you start it again."
                : "This will disable the feature."}
        </Dialog.Description>
        <Flex gap="3" justify="end">
          <Dialog.Close>
            <Button variant="soft" color="gray">Cancel</Button>
          </Dialog.Close>
          <Dialog.Close>
            <Button color="red" onClick={handleStop}>Stop service</Button>
          </Dialog.Close>
        </Flex>
        {localError && (
          <Text size="1" color="red" mt="3" as="div">
            {localError}
          </Text>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
