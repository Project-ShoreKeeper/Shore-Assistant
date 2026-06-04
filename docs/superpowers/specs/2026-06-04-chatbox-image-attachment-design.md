# Chatbox Image Attachment Design

**Date:** 2026-06-04
**Status:** Draft — awaiting user review

## Problem

The chat UI is text-only. Images can reach the multimodal LLM today only through two tools (`capture_screen`, `analyze_screen`), both of which screenshot the *server* display. There is no way for a user to drop a screenshot from their own machine into the chat and ask the assistant about it.

## Goal

Let the user attach one or more images to a chat message and have the assistant reason about them inline with the rest of the agent loop (tools still callable, streaming + TTS still work, conversation history still grows naturally).

Scope is intentionally narrow:

- One round-trip attachment lifecycle. No image library, no editing, no per-image annotations.
- Images live in the LLM context only for the turn they are sent. Subsequent turns see a text placeholder.
- No frontend image cache survives reload. After reload, prior user bubbles show the placeholder.

## Non-Goals

- Server-side persistence of image bytes (data URLs are not stored on disk).
- Reusing past images by reference / scrolling back to "send this image again".
- OCR or any pre-processing on the server beyond what llama-server already does.
- Audio / video / non-image file attachments.
- Drag-out (dragging an attached thumbnail back out to disk).

## Approach

Send images inline as base64 data URLs inside the existing `user_message` WS JSON. The backend builds two representations of the user turn: a multimodal `live_message` that goes to llama-server this turn, and a text-only `memory_message` that is the only thing persisted to conversation history. The agent loop is unchanged except for receiving the prebuilt `live_message`.

llama-server's `/v1/chat/completions` already accepts OpenAI-style `content: [{type:"text"}, {type:"image_url"}]` arrays when an mmproj is loaded — we rely on that and do not add a new vision codepath.

Considered alternatives:

- **One-shot bypass to `generate_with_image`** — simpler but loses tool calls and history coherence for the turn that needs vision the most.
- **Hybrid fast-path** — needs an intent classifier; inconsistent UX; rejected.
- **Separate binary frame for image bytes** — saves ~33% on transport but adds correlation logic. At realistic chat-screenshot sizes (~150-400 KB JPEG) the savings don't justify the complexity.

## Frontend

### State

`pages/Chat/index.tsx` gains:

```ts
type ImageAttachment = {
  id: string;
  dataUrl: string;   // data:image/jpeg;base64,...
  width: number;
  height: number;
  sizeKb: number;
};
const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([]);
```

### Attach paths

- **Paste** — `onPaste` on the input element scans `e.clipboardData.items` for `image/*`, runs each through the resize pipeline, appends to `imageAttachments`.
- **Drag & drop** — `onDragOver` + `onDrop` on the chat panel root, with a subtle border-highlight overlay while a drag is active. Accepted MIME: `image/png`, `image/jpeg`, `image/webp`, `image/gif` (gifs flatten to first frame via canvas).

No attach button (paste + drop are sufficient for the target user).

### Resize pipeline (client-side)

Match `back-end/app/tools/screen_tools.py:_capture_screen_b64`:

- Decode to an `HTMLImageElement`.
- If `max(w,h) > 1280`, scale down with bilinear (`canvas.drawImage`).
- Encode as JPEG quality 0.85.
- Result: data URL + dimensions + sizeKb.

### Limits (frontend, mirrored by backend)

- `MAX_IMAGES = 6` per message. Additional paste/drop ignored once at cap.
- Reject any source file whose decoded size exceeds `MAX_IMAGE_BYTES` (6 MB).
- Reject unsupported MIME types with a toast.

### Input row UI

Above the existing `TextField`, render a horizontal row of 64×64 rounded thumbnails when `imageAttachments.length > 0`. Each thumbnail has an X overlay (top-right) to remove. Row scrolls horizontally if it overflows.

### Send behaviour

`useAssistant`'s `sendTextMessage` becomes `sendUserMessage(text, images?)`. Enter still sends. Empty text is allowed when at least one image is attached. On send:

- Build the WS message (see [Wire protocol](#wire-protocol)).
- Append a local `ChatMessage` with `role: "user"`, `content: text`, `images: imageAttachments` so the bubble renders thumbnails immediately.
- Clear `imageAttachments`.

### Chat bubble rendering

`ChatMessage` user shape extends:

```ts
type UserMessage = {
  role: "user";
  content: string;
  images?: { dataUrl: string; width: number; height: number }[];
  ...
};
```

When `images` is present, render a small grid above the text (rounded thumbnails, max 3 per row). Clicking a thumbnail opens it full-size in a Radix `Dialog`. After reload, rehydrated user bubbles do not have `images` (no persisted dataUrls), and the bubble's `content` already contains the `[Attached N image(s): WxH, …]` placeholder — no broken thumbnail icon.

## Wire Protocol

The existing `user_message` JSON gains one optional field:

```jsonc
{
  "type": "user_message",
  "text": "what does this error mean?",
  "source": "keyboard",
  "images": [
    { "data_url": "data:image/jpeg;base64,…", "width": 1024, "height": 768 }
  ]
}
```

Omit `images` entirely (or send `[]`) when no attachments — text-only flow is byte-identical to today's.

No new binary frame type. No new message type. No new endpoint.

## Backend

### `chat_ws.py` — `_start_agent` extension

Signature:

```python
async def _start_agent(user_text, source, images=None):
```

Current flow appends the user turn to `conversation_history` at `chat_ws.py:191` *before* dispatching the agent, and appends the assistant reply at `chat_ws.py:265` after `llm_complete`. The image change preserves both append sites; only the *shape* of what gets stored vs. what gets sent to llama-server differs.

If `images` is non-empty:

1. Validate (see [Validation](#validation)). On failure, send `{"type":"status","message":"…"}` to the client and return without dispatching.
2. Build `memory_message` (this is what goes on `conversation_history` and to `memory_service`):
   ```python
   placeholder = f"[Attached {len(images)} image(s): " + ", ".join(
       f"{i['width']}x{i['height']}" for i in images) + "]"
   memory_message = {"role": "user",
                     "content": (user_text + "\n\n" + placeholder).strip()}
   ```
3. Build `live_message` (this is the version llama-server sees this turn):
   ```python
   live_message = {"role": "user", "content": [
       {"type": "text", "text": user_text or " "},
       *[{"type": "image_url", "image_url": {"url": img["data_url"]}}
         for img in images],
   ]}
   ```
4. Append `memory_message` to `conversation_history` and `memory_service` (replacing the current `{"role":"user","content":user_text}` write at line 191).
5. Dispatch `agent_service.run(user_text, conversation_history, ...,
   live_user_message=live_message)`.
6. Assistant reply append at line 265 is unchanged.

If `images` is empty/None, the existing text-only path runs unchanged — `memory_message` is built from `user_text` only, `live_user_message=None`.

### `agent_service.run` signature change

```python
async def run(self, user_text, conversation_history,
              thinking=False, no_tools=False,
              live_user_message=None):
```

Behaviour:

- `tool_retriever.retrieve(user_text)` — embedding model is text-only, runs on `user_text`. Tools that match the *text* prompt are retrieved regardless of attached images.
- If `live_user_message` is given, *replace the last entry* of the locally-built `messages` list (which is a copy of `conversation_history`) with `live_user_message`. The text-only `memory_message` was already appended to `conversation_history` by `chat_ws.py` before dispatch; this swap means llama-server sees the multimodal version for this turn only, and `conversation_history` itself is never mutated to hold image bytes.
- If `live_user_message` is `None`, the messages list is used as-is — identical to today.
- Tool loop, streaming, sentence boundaries, retries — unchanged.

### `llm_service.stream_chat_sentences` — content-array guard

Current filter at `agent_service.py:85`:

```python
messages = [m for m in conversation_history if m["content"].strip()]
```

This assumes `content` is a `str`. Change to:

```python
messages = [
    m for m in conversation_history
    if (m["content"] if isinstance(m["content"], list)
        else m["content"].strip())
]
```

Multimodal content arrays survive the filter; existing text-only behaviour is preserved.

### Validation

In `chat_ws.py`, before dispatch:

| Check | Reject reason |
|---|---|
| `len(images) > MAX_IMAGES_PER_MESSAGE` | "Too many images (max N)." |
| Each `data_url` matches `^data:image/(png|jpeg|webp);base64,` | "Unsupported image format." |
| Decoded byte length ≤ `MAX_IMAGE_BYTES` | "Image too large." |
| `MULTIMODAL_ENABLED` is False but images attached | "Vision not enabled on this server." |

Any failure → one `status` message back, agent task never starts, no partial send.

### Config additions (`core/config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `MULTIMODAL_ENABLED` | `True` | Master gate for the feature. Set False when running with a text-only model. |
| `MAX_IMAGES_PER_MESSAGE` | `6` | Per-message cap, mirrored by frontend. |
| `MAX_IMAGE_BYTES` | `6 * 1024 * 1024` | Per-image decoded-byte limit (~6 MB). |

## Memory & History

- `conversation_history` (in-memory) stores only `memory_message`s — never the multimodal content array. This keeps every subsequent turn's prompt small.
- `memory_service` writes the same text-only form to `data/memory/default.json`. No image bytes ever touch disk.
- The chat-history rehydration path (see `2026-06-03-chat-history-rehydration-design.md`) needs no changes; it delivers text-only `[Attached …]` placeholders and the assistant's reply, which is exactly what older turns should look like.

## Error Handling

- **Frontend invalid file**: toast, attachment row unchanged.
- **Frontend over cap**: toast on the rejected paste/drop, existing attachments retained.
- **Backend validation fail**: `status` message displayed in the chat as a system note; user's input + attachments are NOT cleared (so they can retry after fixing).
- **llama-server multimodal error** (e.g. mmproj missing): assistant turn fails with the normal error path; memory entries are not written for that turn.

## Testing

### Backend unit tests

- `tests/test_chat_ws_images.py` (new)
  - 1-image message dispatches to agent with multimodal `content`.
  - 7-image payload returns a status-error and never reaches the agent.
  - Malformed data-URL (`data:image/bmp;...`) is rejected.
  - `MULTIMODAL_ENABLED=False` + images → rejection.
- `tests/test_agent_service.py` (add or extend)
  - When `live_user_message` is passed, the agent uses it as the final messages entry.
  - `tool_retriever.retrieve` is still called with `user_text` (not the content array).
- `tests/test_llm_service.py` (extend existing)
  - Messages with list-shaped `content` survive the filter step.

### Manual verification before claiming done

- Paste a screenshot + empty text → assistant describes the image.
- Paste a screenshot + "what does this code do?" → assistant answers using the image.
- Image + "search the web for this library" → agent calls `search_web` in the same turn the image was sent.
- Reload the page → prior user bubble shows `[Attached 1 image: WxH]`, no broken thumbnail icon, assistant context intact.
- Attach 7 images via fast paste loop → 7th is silently dropped, toast shown.

### Out of scope for tests

- Frontend has no test setup in this project; UI changes are covered by manual smoke only.
