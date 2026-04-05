import { Flex, Text, Button, Avatar } from "@radix-ui/themes";

export default function Header() {
  return (
    <Flex
      align="center"
      justify="between"
      p="3"
      style={{
        borderBottom: "1px solid var(--gray-5)",
        backgroundColor: "var(--color-panel-solid)",
      }}
    >
      <Text weight="bold" size="4">
        Dashboard
      </Text>
      <Flex gap="3" align="center">
        <Button variant="ghost">Cài đặt</Button>
        <Avatar fallback="SK" size="2" radius="full" color="indigo" />
      </Flex>
    </Flex>
  );
}
