import { Box, Button, Flex, Heading, Text } from "@radix-ui/themes";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@Shore/contexts/AuthContext";

export default function PageForbidden() {
  const navigate = useNavigate();
  const { user } = useAuth();

  return (
    <Flex
      align="center"
      justify="center"
      style={{ minHeight: "100vh", background: "var(--gray-2)" }}
    >
      <Box
        p="6"
        style={{
          background: "var(--color-panel-solid)",
          border: "1px solid var(--gray-5)",
          borderRadius: 12,
          width: 400,
          maxWidth: "92vw",
        }}
      >
        <Heading size="6" mb="2">403 — Forbidden</Heading>
        <Text size="2" color="gray" mb="4" style={{ display: "block" }}>
          You're signed in as <Text weight="medium">{user?.email}</Text> but
          this page is admin-only.
        </Text>
        <Flex gap="2">
          <Button onClick={() => navigate("/")}>Go home</Button>
          <Button variant="soft" onClick={() => navigate(-1)}>Back</Button>
        </Flex>
      </Box>
    </Flex>
  );
}
