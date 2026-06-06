import { Box, Button, Flex, Heading, Text } from "@radix-ui/themes";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@Shore/contexts/AuthContext";

export default function PageLogin() {
  const { user, loading, login } = useAuth();
  const navigate = useNavigate();

  // Already signed in → bounce home.
  useEffect(() => {
    if (!loading && user) navigate("/", { replace: true });
  }, [loading, user, navigate]);

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
          width: 380,
          maxWidth: "92vw",
        }}
      >
        <Heading size="6" mb="2">Shore</Heading>
        <Text size="2" color="gray" mb="5" style={{ display: "block" }}>
          Sign in to continue.
        </Text>
        <Button size="3" onClick={login} style={{ width: "100%" }}>
          Sign in with Google
        </Button>
        <Text size="1" color="gray" mt="4" style={{ display: "block" }}>
          Only allowlisted Google accounts can sign in.
        </Text>
      </Box>
    </Flex>
  );
}
