import { Flex, Text, Box, IconButton, Tooltip } from "@radix-ui/themes";
import { Link, useLocation } from "react-router-dom";
import { useCollapsedSidebar } from "../../hooks/useCollapsedSidebar";

const EXPANDED_WIDTH = 250;
const COLLAPSED_WIDTH = 48;
const STORAGE_KEY = "shore.sidebar.left.collapsed";

function ChevronLeft() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ChevronRight() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M6 4L10 8L6 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SpeakerIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M4 9V15H8L13 19V5L8 9H4Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M16 8C17.2 9 18 10.4 18 12C18 13.6 17.2 15 16 16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function ChatBubbleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M21 12C21 16.4 16.97 20 12 20C10.65 20 9.37 19.74 8.22 19.27L4 20L5.07 16.4C4.39 15.07 4 13.58 4 12C4 7.6 8.03 4 12 4C16.97 4 21 7.6 21 12Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

type NavItem = {
  label: string;
  path: string;
  icon: React.ReactNode;
};

const NAV_ITEMS: NavItem[] = [
  { label: "VAD Test", path: "/", icon: <SpeakerIcon /> },
  { label: "Assistant", path: "/chat", icon: <ChatBubbleIcon /> },
];

export default function Sidebar() {
  const location = useLocation();
  const [collapsed, toggle] = useCollapsedSidebar(STORAGE_KEY);

  return (
    <Flex
      direction="column"
      style={{
        width: collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH,
        height: "100%",
        borderRight: "1px solid var(--gray-5)",
        backgroundColor: "var(--gray-2)",
        transition: "width 200ms ease",
        overflow: "hidden",
      }}
    >
      {/* Header row: brand + toggle */}
      <Flex
        align="center"
        justify={collapsed ? "center" : "between"}
        p={collapsed ? "2" : "4"}
        style={{ flexShrink: 0 }}
      >
        {!collapsed && (
          <Text weight="bold" size="4" color="indigo" style={{ whiteSpace: "nowrap" }}>
            Shore Assistant
          </Text>
        )}
        <Tooltip content={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            onClick={toggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <ChevronRight /> : <ChevronLeft />}
          </IconButton>
        </Tooltip>
      </Flex>

      {/* Nav */}
      <Flex
        direction="column"
        gap="1"
        px={collapsed ? "2" : "3"}
        mt={collapsed ? "1" : "2"}
      >
        {NAV_ITEMS.map((item) => {
          const isActive = location.pathname === item.path;
          const link = (
            <Link
              key={item.path}
              to={item.path}
              aria-label={item.label}
              style={{
                textDecoration: "none",
                color: isActive ? "var(--indigo-9)" : "var(--gray-11)",
                backgroundColor: isActive ? "var(--indigo-3)" : "transparent",
                padding: collapsed ? "8px 0" : "8px 12px",
                borderRadius: "var(--radius-2)",
                fontWeight: isActive ? 500 : 400,
                transition: "background-color 0.15s ease, color 0.15s ease",
                display: "flex",
                alignItems: "center",
                justifyContent: collapsed ? "center" : "flex-start",
                gap: "10px",
              }}
            >
              <Box style={{ display: "flex", alignItems: "center" }}>
                {item.icon}
              </Box>
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
          return collapsed ? (
            <Tooltip key={item.path} content={item.label} side="right">
              {link}
            </Tooltip>
          ) : (
            link
          );
        })}
      </Flex>
    </Flex>
  );
}
