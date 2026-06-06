import { Flex, Text, Box, IconButton, Tooltip, Separator, Button } from "@radix-ui/themes";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useCollapsedSidebar } from "../../hooks/useCollapsedSidebar";
import { useAuth } from "@Shore/contexts/AuthContext";

const EXPANDED_WIDTH = 232;
const COLLAPSED_WIDTH = 56;
const STORAGE_KEY = "shore.sidebar.left.collapsed";
const APP_VERSION = "1.0.0";

// ── Icons ─────────────────────────────────────────────────────────────

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

function DashboardIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="3" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
      <rect x="13" y="3" width="8" height="5" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
      <rect x="13" y="10" width="8" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
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

function MemoryIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <ellipse cx="12" cy="6" rx="8" ry="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4 6V12C4 13.66 7.58 15 12 15C16.42 15 20 13.66 20 12V6" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4 12V18C4 19.66 7.58 21 12 21C16.42 21 20 19.66 20 18V12" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function ChroniclesIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M4 4H16C17.66 4 19 5.34 19 7V20H7C5.34 20 4 18.66 4 17V4Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M4 17C4 15.34 5.34 14 7 14H19" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 8H15M8 11H13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

// ── Types ─────────────────────────────────────────────────────────────

type NavItem = {
  label: string;
  path: string;
  icon: React.ReactNode;
  /** Match the active state by prefix (e.g. "/chronicles" also matches "/chronicles/v0.1.0"). */
  matchPrefix?: boolean;
};

type NavGroup = {
  title: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    title: "Workspace",
    items: [
      { label: "Dashboard", path: "/", icon: <DashboardIcon /> },
      { label: "Assistant", path: "/chat", icon: <ChatBubbleIcon /> },
    ],
  },
  {
    title: "Memory",
    items: [
      { label: "Memory", path: "/memory", icon: <MemoryIcon /> },
    ],
  },
  {
    title: "Docs",
    items: [
      { label: "Chronicles", path: "/chronicles", icon: <ChroniclesIcon />, matchPrefix: true },
    ],
  },
];

// ── Component ─────────────────────────────────────────────────────────

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, toggle] = useCollapsedSidebar(STORAGE_KEY);
  const { user, logout } = useAuth();

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const renderItem = (item: NavItem) => {
    const isActive = item.matchPrefix
      ? location.pathname === item.path || location.pathname.startsWith(item.path + "/")
      : location.pathname === item.path;
    const link = (
      <Link
        key={item.path}
        to={item.path}
        aria-label={item.label}
        style={{
          textDecoration: "none",
          color: isActive ? "var(--indigo-11)" : "var(--gray-11)",
          backgroundColor: isActive ? "var(--indigo-3)" : "transparent",
          padding: collapsed ? "8px 0" : "8px 12px",
          borderRadius: "var(--radius-2)",
          fontWeight: isActive ? 500 : 400,
          transition: "background-color 0.15s ease, color 0.15s ease",
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "flex-start",
          gap: 10,
          fontSize: 14,
        }}
      >
        <Box style={{ display: "flex", alignItems: "center", color: isActive ? "var(--indigo-10)" : "var(--gray-10)" }}>
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
  };

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
        flexShrink: 0,
      }}
    >
      {/* Header: brand + collapse toggle */}
      <Flex
        align="center"
        justify={collapsed ? "center" : "between"}
        p={collapsed ? "2" : "3"}
        style={{ flexShrink: 0, minHeight: 52 }}
      >
        {!collapsed && (
          <Flex align="center" gap="2">
            <Box
              style={{
                width: 24,
                height: 24,
                borderRadius: 6,
                background: "linear-gradient(135deg, var(--indigo-9), var(--cyan-9))",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "white",
                fontWeight: 700,
                fontSize: 12,
                flexShrink: 0,
              }}
            >
              S
            </Box>
            <Text weight="bold" size="3" style={{ color: "var(--gray-12)" }}>
              Shore
            </Text>
          </Flex>
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

      {/* Nav groups */}
      <Flex
        direction="column"
        gap="3"
        px={collapsed ? "2" : "2"}
        mt="2"
        style={{ flex: 1, overflowY: "auto" }}
      >
        {NAV_GROUPS.map((group, gi) => (
          <Box key={group.title}>
            {!collapsed && (
              <Text
                size="1"
                color="gray"
                weight="bold"
                style={{
                  textTransform: "uppercase",
                  letterSpacing: 1,
                  padding: "0 12px 6px",
                  display: "block",
                  color: "var(--gray-10)",
                }}
              >
                {group.title}
              </Text>
            )}
            {collapsed && gi > 0 && (
              <Separator size="2" my="2" style={{ backgroundColor: "var(--gray-5)" }} />
            )}
            <Flex direction="column" gap="1">
              {group.items.map(renderItem)}
            </Flex>
          </Box>
        ))}
      </Flex>

      {/* Footer: signed-in user + version */}
      <Box
        px={collapsed ? "1" : "3"}
        py="2"
        style={{
          flexShrink: 0,
          borderTop: "1px solid var(--gray-5)",
        }}
      >
        {user && (
          collapsed ? (
            <Tooltip content={`Sign out (${user.email})`} side="right">
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                onClick={handleLogout}
                aria-label="Sign out"
                style={{ width: "100%" }}
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M6 3H3v10h3M10 5l3 3-3 3M13 8H6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </IconButton>
            </Tooltip>
          ) : (
            <Flex direction="column" gap="1" mb="2">
              <Text size="1" color="gray" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {user.email}
              </Text>
              <Button
                size="1"
                variant="soft"
                color="gray"
                onClick={handleLogout}
                style={{ width: "100%" }}
              >
                Sign out
              </Button>
            </Flex>
          )
        )}
        <Text size="1" color="gray" style={{ fontFamily: "monospace", textAlign: "center", display: "block" }}>
          {collapsed ? "v1" : `Shore Assistant v${APP_VERSION}`}
        </Text>
      </Box>
    </Flex>
  );
}
