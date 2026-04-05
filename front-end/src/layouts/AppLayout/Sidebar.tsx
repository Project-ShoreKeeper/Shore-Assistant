import { Flex, Text, Box } from "@radix-ui/themes";
import { Link, useLocation } from "react-router-dom";

export default function Sidebar() {
  const location = useLocation();

  const navItems = [
    { label: "Home (VAD Test)", path: "/" },
    { label: "Chatbot", path: "/chat" },
  ];

  return (
    <Flex
      direction="column"
      p="4"
      style={{
        width: "250px",
        height: "100%",
        borderRight: "1px solid var(--gray-5)",
        backgroundColor: "var(--gray-2)",
      }}
    >
      <Box mb="6">
        <Text weight="bold" size="5" color="indigo">
          Shore STT
        </Text>
      </Box>

      <Flex direction="column" gap="2">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.path}
              style={{
                textDecoration: "none",
                color: isActive ? "var(--indigo-9)" : "var(--gray-11)",
                backgroundColor: isActive ? "var(--indigo-3)" : "transparent",
                padding: "8px 12px",
                borderRadius: "var(--radius-2)",
                fontWeight: isActive ? "500" : "normal",
                transition: "all 0.2s ease",
              }}
            >
              {item.label}
            </Link>
          );
        })}
      </Flex>
    </Flex>
  );
}
