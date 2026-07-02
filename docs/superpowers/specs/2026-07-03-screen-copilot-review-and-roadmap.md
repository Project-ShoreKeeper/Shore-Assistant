# Screen Co-pilot — Đánh giá & Hướng phát triển

**Ngày:** 2026-07-03
**Phạm vi:** Kiến trúc capture phía client (`getDisplayMedia` → thumbnail push → gate diff/cooldown → full-frame qua `screenshot_bridge`), thay thế capture server-side bằng `mss`.

Liên quan: [2026-06-27-screen-copilot-design.md](2026-06-27-screen-copilot-design.md), [2026-07-02-tauri-desktop-client-design.md](2026-07-02-tauri-desktop-client-design.md)

## Đánh giá tổng quan

Kiến trúc mới (capture phía client, đẩy thumbnail 64px mỗi 4s về backend để gate, chỉ kéo full-frame khi trigger) là hướng đi đúng và được thực thi khá sạch.

### Điểm làm tốt

- **Tách biệt testable**: `norm_abs_diff`, `should_trigger`, `summarize_copilot_run` là hàm thuần, không I/O — unit test được cập nhật theo.
- **Xử lý deadlock đúng**: `copilot_frame` chạy trong task riêng vì nó chờ `screenshot_bridge` mà response chỉ có thể được resolve bởi chính receive loop — ràng buộc được ghi rõ ở cả hai phía.
- **Băng thông hợp lý**: thumbnail 64px mỗi 4 giây gần như miễn phí; full-frame chỉ đi qua mạng khi thực sự trigger.
- **Validate đầu vào**: `screenshot_response` được kiểm tra MIME, decode base64 và giới hạn `MAX_IMAGE_BYTES` tại receive loop trước khi resolve Future.
- **Fail-safe phía client**: share bị tắt từ UI trình duyệt → track `ended` → tự gửi `copilot_stop`; capture lỗi trong loop cũng tự dừng.
- **Guard tái nhập ổn**: cờ `_triggering` được set trước bất kỳ `await` nào trong `handle_frame`, nên hai frame liên tiếp không thể cùng vượt gate.

## Vấn đề cần lưu ý (xếp theo mức độ)

### 1. Background-tab throttling — vấn đề lớn nhất về tính khả dụng

Use case chính của co-pilot là user làm việc ở *cửa sổ khác* trong khi tab Shore chạy nền. Nhưng `setInterval` trong tab ẩn bị Chrome throttle (tối thiểu 1s, sau ~5 phút "intensive throttling" ép xuống 1 lần/phút). Frame loop gần như đứng hình đúng lúc cần hoạt động nhất.

**Cách né:** chuyển timer vào Web Worker (worker không bị intensive throttling), hoặc dùng `MediaStreamTrackProcessor` đọc frame off-main-thread.

### 2. `getDisplayMedia` cần user gesture

Khi agent gọi tool `capture_screen` mà chưa có share đang mở, handler `request_screenshot` gọi `ensureScreenStream()` → `getDisplayMedia` từ một WS message handler — trình duyệt reject vì thiếu transient activation. Thực tế tool chỉ hoạt động khi user đã share từ trước (ví dụ đang trong phiên co-pilot).

**Đề xuất:** hiển thị UI "Shore muốn xem màn hình — [Chia sẻ]" khi request đến mà chưa có stream, thay vì fail im lặng.

### 3. Rò rỉ trạng thái share khi backend tự dừng phiên

Khi nhận `copilot_state {active: false}` từ backend, frontend chỉ dừng frame loop chứ **không gọi `stopScreenStream()`** — indicator "đang chia sẻ màn hình" của trình duyệt vẫn sáng trong khi user tưởng co-pilot đã tắt. Vấn đề về niềm tin/quyền riêng tư: nên dừng stream, hoặc ít nhất hiện badge rõ trong UI rằng stream còn mở cho on-demand capture.

### 4. Trigger ngay frame đầu tiên

`_last_thumb=None` → diff = 1.0, `_last_action_ts=0.0` → qua cooldown → phân tích ngay khi vừa bật phiên. Nếu là chủ ý ("phân tích ngay khi bật") thì nên ghi chú; nếu không, seed baseline từ frame đầu.

### 5. Idle gate mất hẳn, thay thế còn mỏng

Client không thấy idle OS-level nên gate luôn mở — co-pilot có thể nhảy vào giữa lúc user đang gõ dở. Cooldown 45s chỉ giảm tần suất chứ không giảm "sai thời điểm".

**Đề xuất:** xấp xỉ idle bằng chính thumbnail — chỉ trigger khi màn hình *đã thay đổi so với lần hành động trước* VÀ *ổn định qua 2–3 tick gần nhất* (user dừng tay, đang đọc/bí). Tín hiệu "cần giúp" này tốt hơn cả idle probe cũ, và vẫn là hàm thuần test được.

### 6. Các điểm nhỏ phía backend/frontend

- `asyncio.create_task(copilot_service.handle_frame(...))` không giữ reference — task có thể bị GC giữa chừng. Giữ vào một set và discard khi xong.
- Thumbnail `copilot_frame` được PIL decode **không giới hạn kích thước** (khác `screenshot_response` đã có cap) — nên chặn byte-size trước khi decode.
- `window_title` giờ luôn là `"unknown"` — placeholder trong prompt thành vô nghĩa. Ít nhất lấy `track.getSettings().displaySurface` (monitor/window/tab), và Capture Handle API khi share tab.
- Permission bị từ chối lúc bật co-pilot chỉ có `console.error` — nên có toast cho user.

## Hướng phát triển & tối ưu

### Ngắn hạn (ưu tiên cao)

1. **Web Worker cho frame loop** — sống sót qua background-tab throttling; không có thì tính năng gần như chỉ demo được khi tab Shore đang focus.
2. **Gate "ổn định N tick"** thay cho idle probe (mục 5) — chi phí thấp, cải thiện chất lượng trigger rõ rệt.
3. **UI consent cho `request_screenshot`** khi chưa có stream (mục 2) + toast khi từ chối quyền.
4. **Vá các điểm nhỏ**: giữ task reference, cap byte thumbnail, dừng/hiển thị stream khi phiên tắt.

### Trung hạn

5. **Diff phía client**: client tự tính diff giữa hai thumbnail và chỉ gửi frame khi vượt ngưỡng (backend giữ cooldown + quyết định cuối). Giảm traffic, bỏ decode PIL trên event loop; server vẫn kiểm soát tham số gate qua `copilot_state`.
6. **Khoanh vùng thay đổi**: từ diff thumbnail, xác định vùng thay đổi và gửi kèm crop vùng đó ở độ phân giải cao hơn cho vision model — model nhìn đúng chỗ user đang thao tác.
7. **Phục hồi phiên co-pilot qua WS reconnect** — hiện disconnect → `detach()` là mất phiên, user phải bật lại tay.
8. **Tool result streaming cho `copilot_message`** (đã có trong backlog) — hiện user chỉ thấy kết quả sau khi cả turn kết thúc.

### Dài hạn — điểm chiến lược

**Tauri desktop client** (đã có spec 2026-07-02) giải quyết tận gốc cả ba giới hạn lớn của kiến trúc browser:

- Không bị tab throttling.
- Lấy lại idle probe OS-level (khôi phục gate mà `COPILOT_IDLE_THRESHOLD_SECONDS` hiện là no-op).
- Đọc được focused window title thật cho prompt.

Thiết kế `screenshot_bridge` hiện tại (request/response theo `request_id` qua WS) đã đủ trừu tượng để Tauri client cắm vào mà backend không cần đổi gì — **giữ nguyên contract này** khi phát triển tiếp.
