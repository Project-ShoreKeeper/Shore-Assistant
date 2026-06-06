import { Flex, Box } from "@radix-ui/themes";
import { Outlet, useLocation, Link } from "react-router-dom";
import Sidebar from "./Sidebar";
import Footer from "./Footer";
import { MemoryHealthBanner } from "./MemoryHealthBanner";
import { AssistantProvider } from "@Shore/contexts/AssistantContext";
import { DashboardProvider } from "@Shore/contexts/DashboardContext";

// ── Bottom nav icons ──────────────────────────────────────────────────

function BnDashboard() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="3" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
      <rect x="13" y="3" width="8" height="5" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
      <rect x="13" y="10" width="8" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function BnChat() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M21 12C21 16.4 16.97 20 12 20C10.65 20 9.37 19.74 8.22 19.27L4 20L5.07 16.4C4.39 15.07 4 13.58 4 12C4 7.6 8.03 4 12 4C16.97 4 21 7.6 21 12Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

function BnMemory() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <ellipse cx="12" cy="6" rx="8" ry="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4 6V12C4 13.66 7.58 15 12 15C16.42 15 20 13.66 20 12V6" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4 12V18C4 19.66 7.58 21 12 21C16.42 21 20 19.66 20 18V12" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function BnChronicles() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M4 4H16C17.66 4 19 5.34 19 7V20H7C5.34 20 4 18.66 4 17V4Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M4 17C4 15.34 5.34 14 7 14H19" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 8H15M8 11H13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

const BOTTOM_NAV_ITEMS = [
  { label: "Dashboard", path: "/", icon: <BnDashboard /> },
  { label: "Assistant", path: "/chat", icon: <BnChat /> },
  { label: "Memory", path: "/memory", icon: <BnMemory /> },
  { label: "Chronicles", path: "/chronicles", icon: <BnChronicles />, matchPrefix: true },
];

function BottomNav() {
  const location = useLocation();
  return (
    <nav
      className="bottom-nav"
      style={{
        display: "none",
        flexShrink: 0,
        minHeight: 52,
        paddingBottom: "env(safe-area-inset-bottom)",
        borderTop: "1px solid var(--gray-5)",
        backgroundColor: "var(--gray-2)",
      }}
    >
      {BOTTOM_NAV_ITEMS.map(item => {
        const isActive = item.matchPrefix
          ? location.pathname === item.path || location.pathname.startsWith(item.path + "/")
          : location.pathname === item.path;
        return (
          <Link
            key={item.path}
            to={item.path}
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 3,
              textDecoration: "none",
              color: isActive ? "var(--indigo-11)" : "var(--gray-10)",
            }}
          >
            {item.icon}
            <span style={{ fontSize: 10, fontWeight: isActive ? 600 : 400, fontFamily: "Inter, sans-serif" }}>
              {item.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

export default function AppLayout() {
  const location = useLocation();
  const isChatPage = location.pathname === "/chat";

  return (
    <AssistantProvider>
    <DashboardProvider>
    <Flex style={{ height: "100dvh", width: "100vw", overflow: "hidden" }}>
      <div className="sidebar-wrapper" style={{ display: "flex", flexShrink: 0 }}>
        <Sidebar />
      </div>
      <Flex
        direction="column"
        style={{ flex: 1, overflow: "hidden", minWidth: 0 }}
      >
        <MemoryHealthBanner />
        <Box
          className="layout-main-content"
          style={{
            flex: 1,
            overflowY: isChatPage ? "hidden" : "auto",
            backgroundColor: "var(--gray-1)",
          }}
        >
          <Outlet />
        </Box>
        {!isChatPage && <Footer />}
        <BottomNav />
      </Flex>
    </Flex>
    </DashboardProvider>
    </AssistantProvider>
  );
}
