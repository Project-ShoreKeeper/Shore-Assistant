import { useEffect, useState } from "react";
import {
  Flex, Box, Text, Tabs, IconButton, Tooltip, Badge,
} from "@radix-ui/themes";
import ProfileTab from "./ProfileTab";
import EpisodicTab from "./EpisodicTab";
import AuditTab from "./AuditTab";
import { useNavigate } from "react-router-dom";

type TabKey = "profile" | "episodic" | "audit";

const VALID_TABS: TabKey[] = ["profile", "episodic", "audit"];

function hashToTab(): TabKey {
  const raw = window.location.hash.replace(/^#/, "").split("/")[0];
  return (VALID_TABS as string[]).includes(raw) ? (raw as TabKey) : "profile";
}

export default function PageMemory() {
  const [tab, setTab] = useState<TabKey>(() => hashToTab());
  const [refreshTick, setRefreshTick] = useState(0);
  const [auditStale, setAuditStale] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const onHash = () => setTab(hashToTab());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (window.location.hash.replace(/^#/, "").split("/")[0] !== tab) {
      navigate({ hash: `#${tab}` }, { replace: false });
    }
  }, [tab, navigate]);

  const refresh = () => setRefreshTick((n) => n + 1);
  const onProfileMutate = () => setAuditStale(true);
  const handleTabChange = (v: string) => {
    setTab(v as TabKey);
    if (v === "audit") setAuditStale(false);
  };

  return (
    <Flex
      direction="column"
      style={{
        height: "100%",
        width: "100%",
        backgroundColor: "var(--color-background)",
        overflow: "hidden",
      }}
    >
      <Flex
        align="center"
        justify="between"
        px="5"
        py="3"
        style={{ borderBottom: "1px solid var(--gray-5)", flexShrink: 0 }}
      >
        <Flex align="center" gap="3">
          <Text size="5" weight="bold">Memory</Text>
          <Text size="1" color="gray">
            Profile · Episodic · Audit
          </Text>
        </Flex>
        <Tooltip content="Refresh current tab">
          <IconButton
            size="2"
            variant="ghost"
            color="gray"
            onClick={refresh}
            aria-label="Refresh"
          >
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Flex>

      <Tabs.Root
        value={tab}
        onValueChange={handleTabChange}
        style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}
      >
        <Tabs.List style={{ flexShrink: 0, paddingLeft: 20 }}>
          <Tabs.Trigger value="profile">Profile</Tabs.Trigger>
          <Tabs.Trigger value="episodic">Episodic</Tabs.Trigger>
          <Tabs.Trigger value="audit">
            <Flex align="center" gap="2">
              Audit
              {auditStale && (
                <Badge size="1" color="orange" variant="solid">new</Badge>
              )}
            </Flex>
          </Tabs.Trigger>
        </Tabs.List>

        <Box style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
          {tab === "profile" && (
            <Tabs.Content value="profile" style={{ height: "100%" }}>
              <ProfileTab
                refreshTick={refreshTick}
                onMutate={onProfileMutate}
              />
            </Tabs.Content>
          )}
          {tab === "episodic" && (
            <Tabs.Content value="episodic" style={{ height: "100%" }}>
              <EpisodicTab refreshTick={refreshTick} />
            </Tabs.Content>
          )}
          {tab === "audit" && (
            <Tabs.Content value="audit" style={{ height: "100%" }}>
              <AuditTab refreshTick={refreshTick} onRestore={onProfileMutate} />
            </Tabs.Content>
          )}
        </Box>
      </Tabs.Root>
    </Flex>
  );
}

function RefreshIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M3 12C3 7.03 7.03 3 12 3C14.5 3 16.77 4.02 18.41 5.66M21 12C21 16.97 16.97 21 12 21C9.5 21 7.23 19.98 5.59 18.34M19 3V8H14M5 21V16H10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
