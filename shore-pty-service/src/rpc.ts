export enum ErrorCode {
  ParseError = -32700,
  InvalidRequest = -32600,
  MethodNotFound = -32601,
  InvalidParams = -32602,
  InternalError = -32603,
  ShellNotFound = -32001,
  SessionNotFound = -32002,
  SessionAlreadyExists = -32003,
  SpawnFailed = -32004,
  WriteToDeadSession = -32005,
}

export type ParsedMessage =
  | { kind: "request"; id: number | string; method: string; params: Record<string, unknown> }
  | { kind: "invalid"; reason: string };

export function parseMessage(raw: string): ParsedMessage {
  let obj: any;
  try {
    obj = JSON.parse(raw);
  } catch (e) {
    return { kind: "invalid", reason: "parse error" };
  }
  if (obj?.jsonrpc !== "2.0") return { kind: "invalid", reason: "bad jsonrpc version" };
  if (typeof obj.method !== "string") return { kind: "invalid", reason: "missing method" };
  if (obj.id === undefined || obj.id === null) {
    return { kind: "invalid", reason: "missing id (notifications not accepted)" };
  }
  const params = obj.params && typeof obj.params === "object" ? obj.params : {};
  return { kind: "request", id: obj.id, method: obj.method, params };
}

export function encodeResponse(id: number | string, result: unknown): string {
  return JSON.stringify({ jsonrpc: "2.0", id, result });
}

export function encodeError(id: number | string | null, code: number, message: string, data?: unknown): string {
  const err: any = { code, message };
  if (data !== undefined) err.data = data;
  return JSON.stringify({ jsonrpc: "2.0", id, error: err });
}

export function encodeNotification(method: string, params: Record<string, unknown>): string {
  return JSON.stringify({ jsonrpc: "2.0", method, params });
}
