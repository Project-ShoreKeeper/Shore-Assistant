import React, { useEffect, useState } from "react";
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
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { useAssistant, type ChatMessage } from "../../hooks/useAssistant";
import ToolActionCard from "../../components/ToolActionCard";
import SettingsPanel from "./SettingsPanel";

/** Wrap bare URLs in markdown link syntax with truncated display text. */
function linkifyUrls(text: string): string {
  return text.replace(
    /(?<!\[.*?)(?<!\()(https?:\/\/[^\s<>)\]]+)/g,
    (url) => {
      const display = url.length > 50 ? url.slice(0, 50) + "..." : url;
      return `[${display}](${url})`;
    }
  );
}

function PageChat() {
  const {
    isVADLoaded,
    isRecording,
    isSpeaking,
    volumeRef,
    wsStatus,
    isConnected,
    messages,
    isAssistantThinking,
    language,
    setLanguage,
    thinkingEnabled,
    setThinkingEnabled,
    startRecording,
    stopRecording,
    sendTextMessage,
    cancelGeneration,
    clearMessages,
  } = useAssistant();

  const [inputText, setInputText] = useState("");
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(new Set());
  const [selectedDeviceId, setSelectedDeviceId] = useState<
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
  }, [messages, isSpeaking, isAssistantThinking]);

  const handleSendText = () => {
    if (!inputText.trim() || !isConnected) return;
    sendTextMessage(inputText);
    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendText();
    }
  };

  const renderMessage = (msg: ChatMessage) => {
    const isUser = msg.role === "user";
    const isEmpty = !msg.text || msg.text.trim() === "";
    const hasThinking = !!msg.thinkingText;
    const isProcessing = msg.isStreaming;

    // Skip empty finalized user messages (silence)
    if (isUser && !isProcessing && isEmpty && !msg.audioUrl) return null;

    const isThinkingExpanded = expandedThinking.has(msg.id);
    const toggleThinking = () => {
      setExpandedThinking((prev) => {
        const next = new Set(prev);
        if (next.has(msg.id)) {
          next.delete(msg.id);
        } else {
          next.add(msg.id);
        }
        return next;
      });
    };

    return (
      <Flex
        key={msg.id}
        justify={isUser ? "end" : "start"}
        mb="4"
        gap="2"
      >
        {/* Assistant avatar (left) */}
        {!isUser && (
          <Avatar
            fallback="SK"
            size="2"
            radius="full"
            color="cyan"
            style={{ flexShrink: 0 }}
          />
        )}

        <Flex
          direction="column"
          align={isUser ? "end" : "start"}
          style={{ maxWidth: "75%" }}
        >
          <Box
            p="3"
            style={{
              backgroundColor: isUser ? "var(--indigo-9)" : "var(--gray-3)",
              color: isUser ? "white" : "var(--gray-12)",
              borderRadius: "20px",
              ...(isUser
                ? { borderBottomRightRadius: "4px" }
                : { borderBottomLeftRadius: "4px" }),
              boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
            }}
          >
            {/* Audio player for voice messages */}
            {isUser && msg.audioUrl && (
              <Box mb={msg.text ? "2" : "0"}>
                <audio
                  src={msg.audioUrl}
                  controls
                  style={{
                    height: "32px",
                    width: "100%",
                    maxWidth: "220px",
                    filter: isUser
                      ? "invert(1) hue-rotate(180deg) brightness(1.5)"
                      : "none",
                  }}
                />
              </Box>
            )}

            {/* Tool action cards */}
            {!isUser && msg.agentActions && msg.agentActions.length > 0 && (
              <Box mb={msg.text ? "2" : "0"} style={{ maxWidth: "100%", minWidth: "280px" }}>
                {msg.agentActions
                  .filter((a) => a.action === "tool_call")
                  .map((a) => (
                    <ToolActionCard
                      key={a.id}
                      tool={a.tool || "unknown"}
                      args={a.args}
                      result={a.result}
                      status={a.status}
                    />
                  ))}
              </Box>
            )}

            {/* Thinking block */}
            {!isUser && hasThinking && (
              <Box
                mb={msg.text ? "2" : "0"}
                style={{
                  borderRadius: "8px",
                  border: "1px solid var(--gray-4)",
                  overflow: "hidden",
                }}
              >
                {/* Thinking header - clickable to expand/collapse */}
                <Box
                  p="2"
                  style={{
                    backgroundColor: "var(--gray-2)",
                    cursor: msg.isThinkingPhase ? "default" : "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    userSelect: "none",
                  }}
                  onClick={msg.isThinkingPhase ? undefined : toggleThinking}
                >
                  {msg.isThinkingPhase && (
                    <span
                      style={{
                        display: "inline-block",
                        width: "6px",
                        height: "6px",
                        borderRadius: "50%",
                        backgroundColor: "var(--amber-9)",
                        animation: "pulse 1s infinite",
                      }}
                    />
                  )}
                  <Text
                    size="1"
                    weight="bold"
                    style={{
                      color: msg.isThinkingPhase
                        ? "var(--amber-11)"
                        : "var(--gray-9)",
                      textTransform: "uppercase",
                      letterSpacing: "0.5px",
                    }}
                  >
                    {msg.isThinkingPhase ? "Thinking..." : "Thought"}
                  </Text>
                  {!msg.isThinkingPhase && (
                    <Text
                      size="1"
                      style={{
                        color: "var(--gray-8)",
                        marginLeft: "auto",
                      }}
                    >
                      {isThinkingExpanded ? "▲" : "▼"}
                    </Text>
                  )}
                </Box>

                {/* Thinking content - always shown during thinking, toggleable after */}
                {(msg.isThinkingPhase || isThinkingExpanded) && (
                  <Box
                    p="2"
                    style={{
                      maxHeight: "200px",
                      overflowY: "auto",
                      backgroundColor: "var(--gray-1)",
                    }}
                  >
                    <Text
                      size="1"
                      style={{
                        whiteSpace: "pre-wrap",
                        color: "var(--gray-10)",
                        fontStyle: "italic",
                        lineHeight: "1.5",
                      }}
                    >
                      {msg.thinkingText}
                      {msg.isThinkingPhase && (
                        <span
                          style={{
                            display: "inline-block",
                            width: "2px",
                            height: "12px",
                            backgroundColor: "var(--amber-9)",
                            marginLeft: "2px",
                            animation: "pulse 0.8s infinite",
                            verticalAlign: "text-bottom",
                          }}
                        />
                      )}
                    </Text>
                  </Box>
                )}
              </Box>
            )}

            {/* Message text */}
            {isProcessing && isEmpty && !hasThinking ? (
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
                    backgroundColor: isUser ? "white" : "var(--indigo-9)",
                    animation: "pulse 1s infinite",
                  }}
                />
                {isUser ? "Recognizing..." : "Thinking..."}
              </Text>
            ) : (
              msg.text && (
                isUser ? (
                  <Text size="2" style={{ whiteSpace: "pre-wrap" }}>
                    {msg.text}
                  </Text>
                ) : (
                  <Box style={{ fontSize: "var(--font-size-2)", lineHeight: "1.6" }}>
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                      components={{
                        p: ({ children }) => (
                          <p style={{ margin: "0 0 0.5em 0" }}>{children}</p>
                        ),
                        ul: ({ children }) => (
                          <ul style={{ margin: "0.25em 0", paddingLeft: "1.4em" }}>{children}</ul>
                        ),
                        ol: ({ children }) => (
                          <ol style={{ margin: "0.25em 0", paddingLeft: "1.4em" }}>{children}</ol>
                        ),
                        li: ({ children }) => (
                          <li style={{ marginBottom: "0.1em" }}>{children}</li>
                        ),
                        code: ({ children, className }) => {
                          const isBlock = !!className;
                          return isBlock ? (
                            <code
                              style={{
                                display: "block",
                                backgroundColor: "var(--gray-2)",
                                border: "1px solid var(--gray-5)",
                                borderRadius: "6px",
                                padding: "8px 10px",
                                fontSize: "0.85em",
                                fontFamily: "monospace",
                                whiteSpace: "pre-wrap",
                                overflowX: "auto",
                                marginBlock: "0.4em",
                              }}
                            >
                              {children}
                            </code>
                          ) : (
                            <code
                              style={{
                                backgroundColor: "var(--gray-4)",
                                borderRadius: "4px",
                                padding: "1px 5px",
                                fontSize: "0.875em",
                                fontFamily: "monospace",
                              }}
                            >
                              {children}
                            </code>
                          );
                        },
                        pre: ({ children }) => (
                          <pre style={{ margin: "0.4em 0", background: "none", padding: 0 }}>{children}</pre>
                        ),
                        blockquote: ({ children }) => (
                          <blockquote
                            style={{
                              borderLeft: "3px solid var(--gray-6)",
                              margin: "0.4em 0",
                              paddingLeft: "0.8em",
                              color: "var(--gray-10)",
                              fontStyle: "italic",
                            }}
                          >
                            {children}
                          </blockquote>
                        ),
                        h1: ({ children }) => <h1 style={{ fontSize: "1.2em", fontWeight: 700, margin: "0.4em 0 0.2em" }}>{children}</h1>,
                        h2: ({ children }) => <h2 style={{ fontSize: "1.1em", fontWeight: 600, margin: "0.4em 0 0.2em" }}>{children}</h2>,
                        h3: ({ children }) => <h3 style={{ fontSize: "1em", fontWeight: 600, margin: "0.3em 0 0.15em" }}>{children}</h3>,
                        a: ({ children, href }) => (
                          <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: "var(--indigo-10)", textDecoration: "underline" }}>
                            {children}
                          </a>
                        ),
                        hr: () => <hr style={{ border: "none", borderTop: "1px solid var(--gray-5)", margin: "0.5em 0" }} />,
                        table: ({ children }) => (
                          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "0.9em", margin: "0.4em 0" }}>{children}</table>
                        ),
                        th: ({ children }) => (
                          <th style={{ border: "1px solid var(--gray-5)", padding: "4px 8px", backgroundColor: "var(--gray-3)", fontWeight: 600 }}>{children}</th>
                        ),
                        td: ({ children }) => (
                          <td style={{ border: "1px solid var(--gray-5)", padding: "4px 8px" }}>{children}</td>
                        ),
                      }}
                    >
                      {linkifyUrls(msg.text)}
                    </ReactMarkdown>
                    {/* Streaming cursor */}
                    {isProcessing && !msg.isThinkingPhase && (
                      <span
                        style={{
                          display: "inline-block",
                          width: "2px",
                          height: "14px",
                          backgroundColor: "var(--indigo-9)",
                          marginLeft: "2px",
                          animation: "pulse 0.8s infinite",
                          verticalAlign: "text-bottom",
                        }}
                      />
                    )}
                  </Box>
                )
              )
            )}
          </Box>

          {/* Timestamp */}
          <Text size="1" color="gray" mt="1">
            {msg.timestamp.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </Text>
        </Flex>

        {/* User avatar (right) */}
        {isUser && (
          <Avatar
            fallback="ME"
            size="2"
            radius="full"
            color="indigo"
            style={{ flexShrink: 0 }}
          />
        )}
      </Flex>
    );
  };

  return (
    <Flex style={{ height: "100%", width: "100%" }}>
      {/* Left column: Chat interface */}
      <Flex direction="column" style={{ flex: 1, position: "relative" }}>
        {/* Chat body */}
        <ScrollArea
          type="auto"
          scrollbars="vertical"
          style={{ flex: 1, padding: "24px 16px" }}
        >
          <Flex direction="column" justify="end" style={{ minHeight: "100%" }}>
            {messages.length === 0 && !isSpeaking && (
              <Flex
                align="center"
                justify="center"
                p="6"
                direction="column"
                gap="3"
                style={{ opacity: 0.6 }}
              >
                <Text size="8">Shore</Text>
                <Text color="gray">AI Assistant ready.</Text>
                <Text size="2" color="gray">
                  Type a message or press the microphone to talk.
                </Text>
                {!isConnected && (
                  <Badge color="orange" variant="soft" size="1">
                    Backend not connected -- start the server first
                  </Badge>
                )}
              </Flex>
            )}

            {messages.map(renderMessage)}

            {/* Speaking indicator */}
            {isSpeaking && (
              <Flex justify="end" mb="4" gap="2">
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
                        *
                      </span>
                      Recording...
                    </Text>
                  </Box>
                </Flex>
                <Avatar
                  fallback="ME"
                  size="2"
                  radius="full"
                  color="indigo"
                  style={{ flexShrink: 0 }}
                />
              </Flex>
            )}

            {/* Agent action log rendered inline inside chat bubbles now */}
          </Flex>
        </ScrollArea>

        {/* Input area */}
        <Box
          p="3"
          style={{
            borderTop: "1px solid var(--gray-5)",
            backgroundColor: "var(--color-panel-solid)",
          }}
        >
          <Flex gap="3" align="center">
            <TextField.Root
              placeholder="Type a message..."
              size="3"
              style={{ flex: 1, borderRadius: "20px" }}
              value={inputText}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setInputText(e.target.value)
              }
              onKeyDown={handleKeyDown}
              disabled={!isConnected}
            />

            {/* Microphone button */}
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
              disabled={!isVADLoaded}
              style={{
                width: "44px",
                height: "44px",
                cursor: isVADLoaded ? "pointer" : "wait",
                transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
                boxShadow: isRecording ? "0 0 15px var(--red-9)" : "none",
              }}
              title={isRecording ? "Stop mic" : "Start mic"}
            >
              <span style={{ fontSize: "20px" }}>
                {isRecording ? "||" : "Mic"}
              </span>
            </IconButton>

            {/* Send / Cancel button */}
            {isAssistantThinking ? (
              <IconButton
                size="3"
                color="red"
                variant="soft"
                radius="full"
                style={{ width: "44px", height: "44px", cursor: "pointer" }}
                onClick={cancelGeneration}
                title="Cancel generation"
              >
                <span style={{ fontSize: "18px" }}>X</span>
              </IconButton>
            ) : (
              <IconButton
                size="3"
                color="indigo"
                variant="solid"
                radius="full"
                style={{ width: "44px", height: "44px", cursor: "pointer" }}
                onClick={handleSendText}
                disabled={!inputText.trim() || !isConnected}
              >
                <span style={{ fontSize: "18px", paddingLeft: "2px" }}>
                  &gt;
                </span>
              </IconButton>
            )}
          </Flex>

          {/* Loading indicator */}
          {!isVADLoaded && (
            <Text
              size="1"
              color="orange"
              mt="2"
              style={{ display: "block", textAlign: "center" }}
            >
              Loading VAD model...
            </Text>
          )}
        </Box>
      </Flex>

      {/* Right column: Settings */}
      <SettingsPanel
        isLoaded={isVADLoaded}
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
        isAssistantThinking={isAssistantThinking}
        thinkingEnabled={thinkingEnabled}
        onThinkingEnabledChange={setThinkingEnabled}
        onClearMessages={clearMessages}
        messageCount={messages.length}
      />
    </Flex>
  );
}

export default PageChat;
