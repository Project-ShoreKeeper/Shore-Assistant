import { Flex, Box } from "@radix-ui/themes";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import Header from "./Header";
import Footer from "./Footer";

export default function AppLayout() {
  const location = useLocation();
  const isChatPage = location.pathname === "/chat";

  return (
    <Flex style={{ height: "100vh", width: "100vw", overflow: "hidden" }}>
      <Sidebar />
      <Flex
        direction="column"
        style={{ flex: 1, overflow: "hidden", minWidth: 0 }}
      >
        <Header />
        <Box
          style={{
            flex: 1,
            overflowY: isChatPage ? "hidden" : "auto",
            backgroundColor: "var(--gray-1)",
          }}
        >
          <Outlet />
        </Box>
        {!isChatPage && <Footer />}
      </Flex>
    </Flex>
  );
}
