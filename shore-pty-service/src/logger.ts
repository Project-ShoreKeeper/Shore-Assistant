import pino from "pino";

export const logger = pino({
  level: process.env.PTY_LOG_LEVEL ?? "info",
  transport: { target: "pino-pretty", options: { translateTime: true } },
});
