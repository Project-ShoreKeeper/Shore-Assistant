# TÀI LIỆU ĐẶC TẢ YÊU CẦU PHẦN MỀM
**(Software Requirements Specification – SRS)**

* **Tên dự án:** Shore Assistant (Hệ thống Trợ lý AI cá nhân tương tác giọng nói)
* **Mã dự án:** SHORE-ASSISTANT
* **Phiên bản:** 2.0
* **Ngày:** 06/08/2026
* **Trạng thái:** Bản chính thức (Phản ánh kiến trúc Microservices thực tế)

---

## Mục lục
1. [Giới thiệu](#1-giới-thiệu)
   * 1.1 [Mục đích](#11-mục-đích)
   * 1.2 [Phạm vi hệ thống](#12-phạm-vi-hệ-thống)
   * 1.3 [Định nghĩa và từ viết tắt](#13-định-nghĩa-và-từ-viết-tắt)
   * 1.4 [Tài liệu tham khảo](#14-tài-liệu-tham-khảo)
2. [Mô tả tổng quan](#2-mô-tả-tổng-quan)
   * 2.1 [Bối cảnh & Kiến trúc tổng quan](#21-bối-cảnh--kiến-trúc-tổng-quan)
   * 2.2 [Chi tiết các phân hệ thành phần](#22-chi-tiết-các-phân-hệ-thành-phần)
   * 2.3 [Đặc điểm người dùng](#23-đặc-điểm-người-dùng)
   * 2.4 [Ràng buộc kỹ thuật & Hạ tầng](#24-ràng-buộc-kỹ-thuật--hạ-tầng)
   * 2.5 [Giả định và phụ thuộc](#25-giả-định-và-phụ-thuộc)
3. [Yêu cầu cụ thể](#3-yêu-cầu-cụ-thể)
   * 3.1 [Yêu cầu chức năng (Functional Requirements - FR)](#31-yêu-cầu-chức-năng-functional-requirements---fr)
   * 3.2 [Yêu cầu phi chức năng (Non-Functional Requirements - NFR)](#32-yêu-cầu-phi-chức-năng-non-functional-requirements---nfr)
   * 3.3 [Yêu cầu giao diện bên ngoài (External Interface Requirements)](#33-yêu-cầu-giao-diện-bên-ngoài-external-interface-requirements)
4. [Phụ lục](#4-phụ-lục)
   * 4.1 [Kịch bản sử dụng thực tế (Use Cases)](#41-kịch-bản-sử-dụng-thực-tế-use-cases)
   * 4.2 [Lịch sử thay đổi tài liệu](#42-lịch-sử-thay-đổi-tài-liệu)

---

## 1. Giới thiệu

### 1.1 Mục đích
Tài liệu SRS này đặc tả đầy đủ các yêu cầu chức năng, phi chức năng và kiến trúc kỹ thuật của hệ thống **Shore Assistant** — một trợ lý ảo cá nhân ưu tiên giao tiếp qua giọng nói (Voice-First AI Assistant). Tài liệu được chuẩn hóa để làm căn cứ phát triển, kiểm thử, vận hành và mở rộng hệ thống.

### 1.2 Phạm vi hệ thống
* **Bản chất hệ thống:** Hệ thống trợ lý AI cá nhân tích hợp đa phân hệ (Multi-service/Microservices Architecture), phục vụ tương tác hai chiều bằng giọng nói và văn bản, có khả năng tự động điều phối công cụ và dịch vụ.
* **Môi trường triển khai:** 
  * **Client:** Trình duyệt web (React + Vite) tích hợp xử lý âm thanh thời gian thực.
  * **Backend Orchestrator:** Dịch vụ trung tâm viết bằng FastAPI (Python).
  * **AI ML Microservice (`shore-ai-service`):** Container Docker chạy trên hạ tầng GPU phụ trách STT, TTS, Embeddings qua gRPC.
  * **PTY Host Microservice (`shore-pty-service`):** Microservice Node.js quản lý phiên Terminal tương tác.
  * **Memory Infrastructure:** Cụm Redis, PostgreSQL và Qdrant Vector DB.
* **Không bao gồm trong phạm vi (Out of Scope):** 
  * Quản trị tổ chức đa người dùng (Multi-tenant Enterprise ERP/CRM).
  * Điều khiển tự động hóa giao diện máy tính cấp thấp (Computer-Use / GUI Desktop Automation / EvoCUA).

### 1.3 Định nghĩa và từ viết tắt
* **VAD (Voice Activity Detection):** Thuật toán phát hiện tiếng nói con người (Silero VAD ONNX chạy trực tiếp trên trình duyệt).
* **STT (Speech-to-Text):** Chuyển đổi giọng nói thành văn bản ( Whisper model).
* **TTS (Text-to-Speech):** Chuyển đổi văn bản thành giọng nói dạng dòng âm thanh PCM (Kokoro model).
* **PCM (Pulse-Code Modulation):** Dạng dữ liệu âm thanh thô truyền qua dòng dữ liệu (Audio Stream).
* **gRPC:** Giao thức truyền thông hiệu năng cao dựa trên HTTP/2 và Protocol Buffers.
* **PTY (Pseudo-Terminal):** Thiết bị đầu cuối ảo cho phép thực thi dòng lệnh hệ điều hành.
* **Hybrid Memory:** Kiến trúc bộ nhớ hỗn hợp gồm 3 tầng: Ngắn hạn (Redis), Hồ sơ cá nhân (Postgres) và Tri thức sự kiện (Qdrant Episodic Memory).
* **LOCOMO Worker:** Tiến trình chạy ngầm tự động trích xuất thông tin quan trọng từ hội thoại đưa vào bộ nhớ dài hạn.
* **n8n:** Nền tảng tự động hóa quy trình theo luồng công việc (Workflow Automation).

### 1.4 Tài liệu tham khảo
* IEEE Std 830-1998 – *Recommended Practice for Software Requirements Specifications*.
* OpenAPI 3.0 & gRPC Protocol Buffer v3 Specifications.

---

## 2. Mô tả tổng quan

### 2.1 Bối cảnh & Kiến trúc tổng quan

Shore Assistant hoạt động theo mô hình **Orchestrator Architecture** phân tách bạch giữa luồng điều phối tác vụ và luồng tính toán AI nặng:

```
[Browser Client (React + Silero VAD)]
       │
       ▼ (WebSocket /ws/chat PCM Streaming & REST APIs)
[FastAPI Backend Orchestrator] ◄────► [Hybrid Memory: Redis + Postgres + Qdrant]
   │          │          │
   │ gRPC     │ WS       │ HTTP/API
   ▼          ▼          ▼
[shore-ai-service]  [shore-pty-service]   [External Services & Cloud Sub-agents]
 (Whisper, Kokoro,    (node-pty executor)   (n8n Workflows, Claude, Gemini, GPT)
  all-MiniLM)
```

### 2.2 Chi tiết các phân hệ thành phần

1. **Giao diện người dùng (Browser Client):**
   * Xây dựng trên React, TypeScript và Vite.
   * Tích hợp **Silero VAD** chạy ONNX trực tiếp ở trình duyệt (16kHz / 512-sample chunks) để phát hiện giọng nói người dùng tự động mà không gửi audio thừa về server.
   * Tích hợp **AudioContext PCM Player** phát âm thanh phản hồi từ server với độ trễ cực thấp.
2. **Backend Orchestrator (FastAPI Backend):**
   * Điều phối toàn bộ luồng xử lý hằng ngày: Tiếp nhận hội thoại (`/ws/chat`), quản lý phiên (`/api/auth`), Dashboard giám sát (`/api/dashboard`), điều khiển dịch vụ (`/api/services`).
   * **LLM Agent Loop:** Sử dụng mô hình LLM tương thích chuẩn OpenAI (`llama-server`) hỗ trợ Native Tool Calling với cơ chế giới hạn vòng lặp an toàn (tối đa 50 round).
   * **Tool Retriever:** Sử dụng kỹ thuật tìm kiếm tương đồng vector (Cosine Similarity via Embeddings) để truy xuất động các công cụ phù hợp theo yêu cầu người dùng.
   * **Scheduler & Notifications:** Sử dụng APScheduler ghi nhận tác vụ một lần và lặp lại, đẩy thông báo chủ động (Proactive Push) qua `ConnectionManager` tới client.
3. **Phân hệ tính toán AI (`shore-ai-service` & `shore-ai-supervisor`):**
   * Triển khai dạng Docker Container trên GPU, cung cấp giao tiếp gRPC:
     * `STT.Transcribe`: Nhận diện giọng nói tiếng Việt/Anh bằng Whisper.
     * `TTS.Synthesize`: Tổng hợp giọng nói đọc phản hồi bằng Kokoro (Stream dữ liệu PCM Int16).
     * `Embed.Encode`: Mã hóa văn bản thành vector bằng `sentence-transformers/all-MiniLM-L6-v2`.
   * `shore-ai-supervisor`: Dịch vụ điều khiển chạy trên máy chủ host, hỗ trợ lệnh khởi chạy, dừng và kiểm tra trạng thái của container `shore-ai`.
4. **Phân hệ Terminal (`shore-pty-service`):**
   * Dịch vụ Node.js độc lập chạy `node-pty`, cung cấp giao tiếp WebSocket tại `ws://127.0.0.1:9100` để thực thi an toàn các câu lệnh dòng lệnh.
5. **Hệ thống Bộ nhớ Hỗn hợp (Hybrid Memory Engine):**
   * **Short-term Memory (Redis):** Cửa sổ hội thoại trượt lưu trữ ngữ cảnh giao tiếp gần nhất theo người dùng.
   * **Profile Memory (PostgreSQL):** Lưu trữ thông tin cá nhân, thói quen và cấu hình dạng JSONB, kèm nhật ký thay đổi (Audit log).
   * **Episodic Memory (Qdrant Vector DB):** Lưu trữ tri thức sự kiện dạng vector, sử dụng định danh UUIDv5 để đảm bảo tính duy nhất.
   * **LOCOMO Extraction Worker:** Tiến trình nền tự động phân tích hội thoại khi hệ thống rảnh (idle 30 giây) để trích xuất tri thức mới ghi vào Qdrant/Postgres.
   * **Canonicalizer:** Tiến trình chạy định kỳ hàng đêm gộp các thẻ thực thể trùng lặp (Entity Tag Deduplication).

### 2.3 Đặc điểm người dùng
* **Người dùng cá nhân:** Sử dụng trợ lý cho công việc hàng ngày (nhắc lịch, tra cứu thông tin, điều khiển dòng lệnh, soạn thảo, kích hoạt tự động hóa n8n).
* **Đòi hỏi tương tác tự nhiên:** Ưu tiên giao tiếp giọng nói linh hoạt rảnh tay.

### 2.4 Ràng buộc kỹ thuật & Hạ tầng
* **Tách biệt GPU & Orchestrator:** FastAPI Backend hoàn toàn không chứa thư viện nặng (`torch`, `transformers`), giữ cho backend nhẹ và khởi động tức thì. Tất cả ML nặng chuyển sang container `shore-ai-service`.
* **Cơ chế ngắt mạch (Circuit Breaker):** Mỗi tầng của Hybrid Memory phải có cơ chế giới hạn thời gian chờ (timeout max 500ms) để không làm ngưng trệ phản hồi LLM nếu một DB bị sự cố.

### 2.5 Giả định và phụ thuộc
* Máy chủ GPU có cài đặt NVIDIA Container Toolkit để thực thi `shore-ai-service`.
* Các API đám mây bên thứ ba (Claude, Gemini, OpenAI) khả dụng khi người dùng yêu cầu chuyển giao tác vụ cho Cloud Sub-agent.

---

## 3. Yêu cầu cụ thể

### 3.1 Yêu cầu chức năng (Functional Requirements - FR)

#### Nhóm 1: Tương tác Giọng nói & Hội thoại (Voice & Chat Pipeline)
* **FR-01:** Hệ thống phải hỗ trợ hội thoại hai chiều thời gian thực qua kênh WebSocket (`/ws/chat`) dạng văn bản và giọng nói.
* **FR-02:** Client phải tự động cắt phân đoạn giọng nói bằng thuật toán Silero VAD (ONNX) và gửi dữ liệu âm thanh 16kHz về server.
* **FR-03:** Backend phải chuyển đổi giọng nói người dùng sang văn bản bằng gRPC `STT.Transcribe` thuộc phân hệ `shore-ai-service`.
* **FR-04:** Backend phải phát luồng âm thanh PCM phản hồi từ gRPC `TTS.Synthesize` về client ngay khi LLM bắt đầu sinh từ (Streaming TTS latency cực thấp).

#### Nhóm 2: Lập kế hoạch & Gọi công cụ (Agent & Tool Execution)
* **FR-05:** Agent phải hỗ trợ Native Tool Calling, cho phép tự động lập kế hoạch và thực thi chuỗi công cụ để hoàn thiện yêu cầu người dùng.
* **FR-06:** Hệ thống phải tích hợp bộ định tuyến công cụ động (Tool Retriever) dựa trên độ tương đồng vector để chỉ tải các công cụ liên quan vào ngữ cảnh LLM.
* **FR-07:** Hệ thống phải cung cấp các nhóm công cụ hệ thống tích hợp:
  * Tra cứu thời gian, đọc tệp, liệt kê thư mục.
  * Tìm kiếm web (DuckDuckGo), trích xuất nội dung bài viết web (Readability/lxml).
  * Chụp và phân tích hình ảnh màn hình qua mô hình đa thức (Multimodal Model).
  * Chạy lệnh dòng lệnh PTY an toàn qua `shore-pty-service`.
  * Khởi chạy, dừng, kiểm tra log của các dịch vụ chạy ngầm.
* **FR-08:** Hệ thống phải hỗ trợ chuyển giao tác vụ (Escalation) sang các Cloud Sub-agents (`ask_claude`, `ask_gemini`, `ask_openai`) khi có yêu cầu xử lý tư duy nâng cao.

#### Nhóm 3: Quản lý Bộ nhớ & Tự động hóa (Memory & Integration)
* **FR-09:** Hệ thống phải duy trì bộ nhớ ngắn hạn trên Redis cho mỗi phiên làm việc của người dùng.
* **FR-10:** Hệ thống phải hỗ trợ LOCOMO Worker chạy ngầm tự trích xuất thông tin dài hạn (sở thích, sự kiện, tri thức) lưu vào Postgres và Qdrant.
* **FR-11:** Hệ thống phải tích hợp hai chiều với **n8n**:
  * Tự động phát hiện luồng công việc n8n để biến thành công cụ động cho Agent.
  * Tiếp nhận Webhook từ n8n để gửi thông báo chủ động tới người dùng qua giọng nói.
* **FR-12:** Hệ thống phải hỗ trợ lập lịch tác vụ một lần hoặc định kỳ (APScheduler) và đẩy thông báo chủ động bằng lời nói qua giọng nói TTS.

#### Nhóm 4: Xác thực & Quản trị Hệ thống (Auth & Dashboard)
* **FR-13:** Hệ thống phải hỗ trợ đăng nhập qua Google OAuth, quản lý phiên làm việc bằng Redis Session.
* **FR-14:** Hệ thống phải cung cấp Dashboard giám sát trạng thái tài nguyên phần cứng (CPU, RAM, GPU), danh sách dịch vụ, và thành phần AI.
* **FR-15:** Hệ thống phải cho phép quản trị viên điều khiển khởi chạy/dừng các dịch vụ được đăng ký (`/api/services`).

---

### 3.2 Yêu cầu phi chức năng (Non-Functional Requirements - NFR)

| Mã NFR | Phân loại | Mô tả chi tiết yêu cầu |
| :--- | :--- | :--- |
| **NFR-01** | **Hiệu năng & Độ trễ** | Thời gian phản hồi gói dữ liệu TTS âm thanh đầu tiên (First-chunk TTS) không vượt quá 800ms tính từ khi kết thúc câu nói của người dùng. |
| **NFR-02** | **Tính nhẹ nhẹ của Backend** | FastAPI Backend không được chứa các phụ thuộc mã nguồn ML nặng (`torch`, `transformers`, `kokoro`), đảm bảo RAM khởi tạo backend < 300MB. |
| **NFR-03** | **Độ tin cậy & Chịu lỗi** | Mỗi tầng bộ nhớ (Redis, Postgres, Qdrant) phải áp dụng cơ chế Circuit Breaker với timeout tối đa 500ms. Khi một DB lỗi, hệ thống phải hạ cấp hoạt động mượt mà (Graceful Degradation). |
| **NFR-04** | **Tính bảo mật** | Tất cả kết nối gRPC nội bộ giữa Backend và `shore-ai-service` phải được bảo vệ bằng TLS và mã xác thực Bearer Token trong gRPC metadata. |
| **NFR-05** | **Bảo vệ CSRF & Auth** | Các API ghi dữ liệu (`POST/PUT/DELETE`) phải kiểm tra CSRF Token và xác thực Session Redis hợp lệ. |
| **NFR-06** | **Khả năng mở rộng** | Kiến trúc phải hỗ trợ đăng ký công cụ động (Dynamic Tool Registration) mà không cần phải khởi động lại server. |
| **NFR-07** | **An toàn dòng lệnh** | Hệ thống phải áp dụng Danh sách trắng (Allowlist) đối với lệnh thực thi qua Terminal PTY để ngăn ngừa câu lệnh phá hoại hệ thống. |
| **NFR-08** | **Tính riêng tư dữ liệu** | Dữ liệu hội thoại và bộ nhớ cá nhân phải được lưu trữ hoàn toàn trên hạ tầng cá nhân/cụm DB riêng của người dùng. |

---

### 3.3 Yêu cầu giao diện bên ngoài (External Interface Requirements)

#### 1. Giao diện WebSocket Client (`/ws/chat`)
* **Giao thức:** WebSocket (kết nối kép với Cookie / Bearer Header Auth).
* **Định dạng dữ liệu:** 
  * Inbound (Client -> Server): Chuỗi văn bản JSON (tin nhắn text, cấu hình) hoặc mảng byte PCM 16kHz thô.
  * Outbound (Server -> Client): JSON gói trạng thái hội thoại (Text stream, Tool call status) hoặc dữ liệu âm thanh PCM 24kHz Int16 để phát giọng nói.

#### 2. Giao diện gRPC Microservices (`shore-ai-service`)
* **`stt.proto`:** Phương thức `Transcribe(AudioRequest)` trả về `SpeechTranslationResponse`.
* **`tts.proto`:** Phương thức `Synthesize(TTSRequest)` trả về luồng `stream AudioChunk` (PCM Int16).
* **`embed.proto`:** Phương thức `Encode(EmbedRequest)` trả về `EmbedResponse` (Mảng float vectors).

#### 3. Giao diện REST APIs (`FastAPI Orchestrator`)
* `/api/auth/{login, callback, logout, me}`: Quản lý vòng đời đăng nhập Google OAuth.
* `/api/dashboard`: Cung cấp snapshot trạng thái hệ thống, phần cứng và AI components.
* `/api/services`: Cho phép kiểm tra và điều khiển dừng/phát các microservices.
* `/api/memory/*`: Cung cấp các thao tác xem và quản trị dữ liệu hồ sơ cá nhân và bộ nhớ dài hạn.

---

## 4. Phụ lục

### 4.1 Kịch bản sử dụng thực tế (Use Cases)

#### Use Case 1: Đặt lịch hẹn và đẩy thông báo nhắc nhở bằng giọng nói
* **Tác nhân:** Người dùng cá nhân.
* **Luồng xử lý:**
  1. Người dùng nói vào micro: *"Nhắc tôi họp nhóm vào 10 giờ sáng mai"*.
  2. Silero VAD phát hiện kết thúc câu nói -> gửi dữ liệu PCM qua WebSocket `/ws/chat`.
  3. Backend gọi gRPC STT nhận diện câu chữ -> LLM Agent phân tích ý định.
  4. Agent kích hoạt công cụ `set_scheduled_task` để ghi lịch hẹn vào APScheduler.
  5. Backend sinh câu trả lời *"Đã đặt lịch họp nhóm lúc 10h sáng mai cho bạn"* -> gọi gRPC TTS stream âm thanh về trình duyệt phát cho người dùng.
  6. Đến 10:00 sáng mai, APScheduler kích hoạt `NotificationService` -> Agent tạo câu nhắc bằng giọng nói đẩy về trình duyệt của người dùng.

#### Use Case 2: Truy vấn tri thức cũ & Chuyển giao tác vụ cho Cloud Sub-agent
* **Tác nhân:** Người dùng cá nhân.
* **Luồng xử lý:**
  1. Người dùng yêu cầu: *"Hãy tóm tắt lại nội dung tài liệu về dự án Shore mà tôi đã thảo luận tuần trước, sau đó dùng Claude viết giúp tôi một email báo cáo"*.
  2. Agent sử dụng `MemoryFacade` tìm kiếm trong Qdrant Episodic Memory các thông tin liên quan đến "dự án Shore".
  3. Agent kích hoạt công cụ Cloud Sub-agent `ask_claude` truyền ngữ cảnh vừa lấy được để Claude viết bản thảo email.
  4. Agent nhận kết quả từ Claude và phản hồi lại cho người dùng.

---

### 4.2 Lịch sử thay đổi tài liệu

| Phiên bản | Ngày | Tác giả | Mô tả thay đổi |
| :--- | :--- | :--- | :--- |
| **1.0** | 06/08/2026 | Đội ngũ phát triển | Khởi tạo bản dự thảo tổng quan ban đầu. |
| **2.0** | 06/08/2026 | Antigravity AI | **Cập nhật toàn diện chuẩn hóa SRS:**<br>- Bổ sung chi tiết kiến trúc Microservices thực tế (FastAPI, `shore-ai-service` gRPC, `shore-pty-service`).<br>- Chi tiết luồng âm thanh thời gian thực (Silero VAD + PCM WebSocket + Kokoro TTS streaming).<br>- Chi tiết bộ nhớ Hybrid 3 tầng (Redis + Postgres + Qdrant + LOCOMO Worker).<br>- Bổ sung danh sách yêu cầu FR-01 đến FR-15 và NFR-01 đến NFR-08.<br>- Loại bỏ hoàn toàn phân hệ Computer-Use / CUA theo yêu cầu. |