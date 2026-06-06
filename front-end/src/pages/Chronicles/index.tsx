import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { Flex, Box, Text, Callout, Badge, Button } from "@radix-ui/themes";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  listChronicles,
  getChronicle,
  type ChronicleMeta,
  type ChronicleEntry,
} from "@Shore/services/chronicles.service";
import "./chronicles-mobile.css";

const SIDEBAR_WIDTH = 240;

export default function PageChronicles() {
  const { slug } = useParams<{ slug?: string }>();
  const navigate = useNavigate();

  const [entries, setEntries] = useState<ChronicleMeta[] | null>(null);
  const [entry, setEntry] = useState<ChronicleEntry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load sidebar list once
  useEffect(() => {
    let cancelled = false;
    setError(null);
    listChronicles()
      .then((list) => {
        if (cancelled) return;
        setEntries(list);
        // No slug → redirect to newest entry.
        if (!slug && list.length > 0) {
          navigate(`/chronicles/${list[0].slug}`, { replace: true });
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load the active entry whenever slug changes
  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getChronicle(slug)
      .then((e) => {
        if (!cancelled) setEntry(e);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const onGoto = useCallback(
    (target: string) => {
      navigate(`/chronicles/${target}`);
      window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
    },
    [navigate],
  );

  const empty = useMemo(
    () => entries !== null && entries.length === 0,
    [entries],
  );

  return (
    <Flex className="chr-root" style={{ height: "100%", width: "100%", overflow: "hidden" }}>
      {/* ── Sidebar: version list ──────────────────────────────────── */}
      <Flex
        direction="column"
        className="chr-sidebar"
        style={{
          width: SIDEBAR_WIDTH,
          flexShrink: 0,
          borderRight: "1px solid var(--gray-5)",
          backgroundColor: "var(--gray-2)",
          height: "100%",
          overflowY: "auto",
        }}
      >
        <Box className="chr-sidebar-header" px="4" py="3" style={{ borderBottom: "1px solid var(--gray-5)" }}>
          <Text
            size="1"
            color="gray"
            weight="bold"
            style={{ textTransform: "uppercase", letterSpacing: 1 }}
          >
            Chronicles
          </Text>
        </Box>
        {entries === null ? (
          <Box p="3"><Text size="2" color="gray">Loading…</Text></Box>
        ) : empty ? (
          <Box p="3">
            <Text size="2" color="gray" style={{ fontStyle: "italic" }}>
              No chronicles yet. Add a markdown file to <code>docs/chronicles/</code>.
            </Text>
          </Box>
        ) : (
          <Flex direction="column" py="2" className="chr-sidebar-list">
            {entries.map((m) => {
              const isActive = slug === m.slug;
              return (
                <Link
                  key={m.slug}
                  to={`/chronicles/${m.slug}`}
                  className={`chr-nav-link${isActive ? " chr-nav-link--active" : ""}`}
                  style={{
                    textDecoration: "none",
                    padding: "10px 16px",
                    borderLeft: isActive
                      ? "3px solid var(--indigo-9)"
                      : "3px solid transparent",
                    backgroundColor: isActive ? "var(--indigo-3)" : "transparent",
                    color: isActive ? "var(--indigo-11)" : "var(--gray-12)",
                  }}
                >
                  <Flex justify="between" align="center" gap="2">
                    <Text
                      size="2"
                      weight={isActive ? "medium" : "regular"}
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={m.title}
                    >
                      {m.title}
                    </Text>
                    {m.version && (
                      <Badge size="1" color="gray" variant="soft">
                        v{m.version}
                      </Badge>
                    )}
                  </Flex>
                  {m.date && (
                    <Text size="1" color="gray" mt="1" style={{ display: "block" }}>
                      {m.date}
                    </Text>
                  )}
                </Link>
              );
            })}
          </Flex>
        )}
      </Flex>

      {/* ── Content ─────────────────────────────────────────────────── */}
      <Box className="chr-content" style={{ flex: 1, overflowY: "auto", padding: "32px 48px" }}>
        {error && (
          <Callout.Root color="red" mb="3">
            <Callout.Text>{error}</Callout.Text>
          </Callout.Root>
        )}

        {loading && !entry ? (
          <Text size="2" color="gray">Loading…</Text>
        ) : !slug ? (
          <Text size="2" color="gray" style={{ fontStyle: "italic" }}>
            Pick a chronicle from the sidebar.
          </Text>
        ) : entry ? (
          <Box style={{ maxWidth: 800 }}>
            <Flex align="center" gap="3" mb="1" wrap="wrap">
              <Text size="6" weight="bold">{entry.title}</Text>
              {entry.version && (
                <Badge color="indigo" variant="soft" size="2">v{entry.version}</Badge>
              )}
            </Flex>
            {entry.date && (
              <Text size="2" color="gray" mb="4" style={{ display: "block" }}>
                {entry.date}
              </Text>
            )}

            <Box
              style={{
                color: "var(--gray-12)",
                lineHeight: 1.65,
                fontSize: 15,
              }}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h2: ({ children }) => (
                    <h2 style={{
                      fontSize: "1.5em",
                      fontWeight: 700,
                      marginTop: "1.6em",
                      marginBottom: "0.4em",
                      paddingBottom: "0.25em",
                      borderBottom: "1px solid var(--gray-5)",
                    }}>{children}</h2>
                  ),
                  h3: ({ children }) => (
                    <h3 style={{
                      fontSize: "1.2em",
                      fontWeight: 600,
                      marginTop: "1.2em",
                      marginBottom: "0.3em",
                    }}>{children}</h3>
                  ),
                  p: ({ children }) => (
                    <p style={{ margin: "0.6em 0" }}>{children}</p>
                  ),
                  ul: ({ children }) => (
                    <ul style={{ margin: "0.4em 0 0.8em", paddingLeft: "1.4em" }}>{children}</ul>
                  ),
                  li: ({ children }) => (
                    <li style={{ marginBottom: "0.25em" }}>{children}</li>
                  ),
                  a: ({ children, href }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "var(--indigo-11)", textDecoration: "underline" }}
                    >
                      {children}
                    </a>
                  ),
                  code: ({ children, className }) => {
                    const isBlock = !!className;
                    return isBlock ? (
                      <code style={{
                        display: "block",
                        backgroundColor: "var(--gray-2)",
                        border: "1px solid var(--gray-5)",
                        borderRadius: 6,
                        padding: "10px 12px",
                        fontSize: "0.875em",
                        fontFamily: "monospace",
                        whiteSpace: "pre-wrap",
                        overflowX: "auto",
                      }}>{children}</code>
                    ) : (
                      <code style={{
                        backgroundColor: "var(--gray-3)",
                        borderRadius: 4,
                        padding: "1px 5px",
                        fontFamily: "monospace",
                        fontSize: "0.875em",
                      }}>{children}</code>
                    );
                  },
                  pre: ({ children }) => (
                    <pre style={{ margin: "0.6em 0", background: "none", padding: 0 }}>{children}</pre>
                  ),
                  blockquote: ({ children }) => (
                    <blockquote style={{
                      borderLeft: "3px solid var(--indigo-7)",
                      margin: "0.8em 0",
                      padding: "4px 0 4px 14px",
                      color: "var(--gray-11)",
                      backgroundColor: "var(--gray-2)",
                      borderRadius: "0 4px 4px 0",
                    }}>{children}</blockquote>
                  ),
                  hr: () => (
                    <hr style={{ border: "none", borderTop: "1px solid var(--gray-5)", margin: "1.5em 0" }} />
                  ),
                  table: ({ children }) => (
                    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "0.95em", margin: "0.8em 0" }}>{children}</table>
                  ),
                  th: ({ children }) => (
                    <th style={{ border: "1px solid var(--gray-5)", padding: "6px 10px", backgroundColor: "var(--gray-3)", fontWeight: 600, textAlign: "left" }}>{children}</th>
                  ),
                  td: ({ children }) => (
                    <td style={{ border: "1px solid var(--gray-5)", padding: "6px 10px" }}>{children}</td>
                  ),
                }}
              >
                {entry.content}
              </ReactMarkdown>
            </Box>

            {/* Footer pager — prev = older, next = newer */}
            {(entry.prev_slug || entry.next_slug) && (
              <Flex
                justify="between"
                align="center"
                mt="6"
                pt="4"
                style={{ borderTop: "1px solid var(--gray-5)" }}
              >
                {entry.prev_slug ? (
                  <Button
                    variant="soft"
                    color="gray"
                    onClick={() => onGoto(entry.prev_slug!)}
                  >
                    ← Older
                  </Button>
                ) : <span />}
                {entry.next_slug ? (
                  <Button
                    variant="soft"
                    color="gray"
                    onClick={() => onGoto(entry.next_slug!)}
                  >
                    Newer →
                  </Button>
                ) : <span />}
              </Flex>
            )}
          </Box>
        ) : null}
      </Box>
    </Flex>
  );
}
