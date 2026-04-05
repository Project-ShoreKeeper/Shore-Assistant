import { Flex, Text } from "@radix-ui/themes";

export default function Footer() {
  return (
    <Flex
      align="center"
      justify="center"
      p="2"
      style={{
        borderTop: "1px solid var(--gray-5)",
        backgroundColor: "var(--gray-1)",
      }}
    >
      <Text size="1" color="gray">
        Copyright © {new Date().getFullYear()} Project ShoreKeeper. All rights
        reserved.
      </Text>
    </Flex>
  );
}
