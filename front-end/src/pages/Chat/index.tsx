import React, { useEffect } from "react";
import {
  Flex,
  Box,
  Text,
  TextField,
  IconButton,
  ScrollArea,
  Avatar,
  Badge,
} from "@radix-ui/themes";
import { useSTT, type STTTranscript } from "../../hooks/useSTT";
import SettingsPanel from "./SettingsPanel";

function PageChat() {
  const {
    isLoaded,
    isRecording,
    isSpeaking,
    transcripts,
    volumeRef,
    wsStatus,
    isConnected,
    language,
    setLanguage,
    modelSize,
    setModelSize,
    startRecording,
    stopRecording,
  } = useSTT();

  const [selectedDeviceId, setSelectedDeviceId] = React.useState<
    string | undefined
  >(undefined);

  // Scroll to bottom on new messages
  useEffect(() => {
    const viewport = document.querySelector(".rt-ScrollAreaViewport");
    if (viewport) {
      setTimeout(() => {
        viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
      }, 50);
    }
  }, [transcripts, isSpeaking]);

  const renderBubble = (t: STTTranscript) => {
    const isProcessing = !t.isFinal;
    const isEmpty = !t.text || t.text.trim() === "";
    const isSkipped = t.isFinal && isEmpty;

    // Không hiển thị các đoạn bị skip (silence / empty)
    if (isSkipped) return null;

    return (
      <Flex key={t.id} justify="end" mb="4">
        <Flex
          direction="column"
          align="end"
          style={{ maxWidth: "75%" }}
        >
          <Box
            p="3"
            style={{
              backgroundColor: "var(--indigo-9)",
              color: "white",
              borderRadius: "20px",
              borderBottomRightRadius: "4px",
              boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
            }}
          >
            {/* Audio player */}
            {t.audioUrl && (
              <Box mb={t.text ? "2" : "0"}>
                <audio
                  src={t.audioUrl}
                  controls
                  style={{
                    height: "32px",
                    width: "100%",
                    maxWidth: "220px",
                    filter:
                      "invert(1) hue-rotate(180deg) brightness(1.5)",
                  }}
                />
              </Box>
            )}

            {/* Transcript text or processing indicator */}
            {isProcessing ? (
              <Text
                size="2"
                style={{
                  fontStyle: "italic",
                  opacity: 0.85,
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <span
                  style={{
                    display: "inline-block",
                    width: "6px",
                    height: "6px",
                    borderRadius: "50%",
                    backgroundColor: "white",
                    animation: "pulse 1s infinite",
                  }}
                />
                Đang nhận dạng...
              </Text>
            ) : (
              <Text size="2" style={{ whiteSpace: "pre-wrap" }}>
                {t.text}
              </Text>
            )}
          </Box>

          {/* Metadata footer */}
          <Flex gap="2" align="center" mt="1" wrap="wrap">
            <Text size="1" color="gray">
              {t.timestamp.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </Text>

            {t.isFinal && t.language && (
              <Badge
                size="1"
                variant="surface"
                color="gray"
                style={{ fontSize: "10px" }}
              >
                {t.language.toUpperCase()}
                {t.languageProb !== undefined &&
                  ` ${(t.languageProb * 100).toFixed(0)}%`}
              </Badge>
            )}

            {t.isFinal && t.processingTime !== undefined && (
              <Text size="1" color="gray" style={{ fontSize: "10px" }}>
                ⚡ {t.processingTime.toFixed(2)}s
              </Text>
            )}

            {isProcessing && (
              <Text
                size="1"
                color="indigo"
                style={{ animation: "pulse 1.5s infinite" }}
              >
                Đang dịch...
              </Text>
            )}
          </Flex>
        </Flex>

        <Avatar fallback="ME" size="2" radius="full" ml="2" color="indigo" />
      </Flex>
    );
  };

  return (
    <Flex style={{ height: "100%", width: "100%" }}>
      {/* Cột Trái: Giao diện Chat */}
      <Flex direction="column" style={{ flex: 1, position: "relative" }}>
        {/* Vùng Body */}
        <ScrollArea
          type="auto"
          scrollbars="vertical"
          style={{ flex: 1, padding: "24px 16px" }}
        >
          <Flex direction="column" justify="end" style={{ minHeight: "100%" }}>
            {transcripts.length === 0 && !isSpeaking && (
              <Flex
                align="center"
                justify="center"
                p="6"
                direction="column"
                gap="3"
                style={{ opacity: 0.6 }}
              >
                <Text size="8">💬</Text>
                <Text color="gray">Khu vực Chat trống.</Text>
                <Text size="2" color="gray">
                  Bấm phím Microphone bên dưới để rảnh tay nói chuyện!
                </Text>
                {!isConnected && (
                  <Badge color="orange" variant="soft" size="1">
                    ⚠ Backend chưa kết nối — Hãy chạy server trước
                  </Badge>
                )}
              </Flex>
            )}

            {transcripts.map(renderBubble)}

            {/* Bong bóng báo đang thu âm */}
            {isSpeaking && (
              <Flex justify="end" mb="4">
                <Flex
                  direction="column"
                  align="end"
                  style={{ maxWidth: "70%" }}
                >
                  <Box
                    p="3"
                    style={{
                      backgroundColor: "var(--indigo-9)",
                      color: "white",
                      borderRadius: "20px",
                      borderBottomRightRadius: "4px",
                    }}
                  >
                    <Text
                      size="2"
                      style={{
                        display: "flex",
                        gap: "8px",
                        alignItems: "center",
                      }}
                    >
                      <span
                        style={{
                          fontSize: "16px",
                          animation: "pulse 1s infinite",
                        }}
                      >
                        🎙️
                      </span>{" "}
                      Đang ghi âm đoạn hội thoại...
                    </Text>
                  </Box>
                </Flex>
                <Avatar
                  fallback="ME"
                  size="2"
                  radius="full"
                  ml="2"
                  color="indigo"
                />
              </Flex>
            )}
          </Flex>
        </ScrollArea>

        {/* Vùng Input ở đáy */}
        <Box
          p="3"
          style={{
            borderTop: "1px solid var(--gray-5)",
            backgroundColor: "var(--color-panel-solid)",
          }}
        >
          <Flex gap="3" align="center">
            <TextField.Root
              placeholder="Bạn có muốn gõ bàn phím không? (Tạm ẩn lúc VAD)..."
              size="3"
              style={{ flex: 1, borderRadius: "20px" }}
              disabled
            />

            {/* Nút Microphone */}
            <IconButton
              size="3"
              color={isRecording ? "red" : "indigo"}
              variant={isRecording ? "solid" : "soft"}
              radius="full"
              onClick={() =>
                isRecording
                  ? stopRecording()
                  : startRecording(selectedDeviceId)
              }
              disabled={!isLoaded}
              style={{
                width: "44px",
                height: "44px",
                cursor: isLoaded ? "pointer" : "wait",
                transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
                boxShadow: isRecording ? "0 0 15px var(--red-9)" : "none",
              }}
              title={isRecording ? "Dừng Microphone" : "Bật Míc"}
            >
              <span style={{ fontSize: "20px" }}>
                {isRecording ? "⏹️" : "🎤"}
              </span>
            </IconButton>

            {/* Nút Gửi */}
            <IconButton
              size="3"
              color="indigo"
              variant="solid"
              radius="full"
              style={{ width: "44px", height: "44px", cursor: "pointer" }}
              disabled
            >
              <span style={{ fontSize: "18px", paddingLeft: "2px" }}>✈️</span>
            </IconButton>
          </Flex>

          {/* Trạng thái Loading */}
          {!isLoaded && (
            <Text
              size="1"
              color="orange"
              mt="2"
              style={{ display: "block", textAlign: "center" }}
            >
              Đang khởi động cụm Module VAD AI dưới nền...
            </Text>
          )}
        </Box>
      </Flex>

      {/* Cột Phải: Settings Panel */}
      <SettingsPanel
        isLoaded={isLoaded}
        isRecording={isRecording}
        volumeRef={volumeRef}
        selectedDeviceId={selectedDeviceId || "default"}
        onDeviceChange={(id) => {
          const finalId = id === "default" ? undefined : id;
          setSelectedDeviceId(finalId);
          if (isRecording) {
            stopRecording();
            setTimeout(() => {
              startRecording(finalId);
            }, 200);
          }
        }}
        wsStatus={wsStatus}
        isConnected={isConnected}
        language={language}
        onLanguageChange={setLanguage}
        modelSize={modelSize}
        onModelSizeChange={setModelSize}
      />
    </Flex>
  );
}

export default PageChat;
