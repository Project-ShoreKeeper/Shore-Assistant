# Manual smoke — node-pty backend

Prereqs:
- `shore-pty-service` built and runnable (`cd shore-pty-service && npm install && npm run build`).
- llama-server running on :8080 (per CLAUDE.md).
- Frontend reachable.

## Steps

1. **Start Node service**
   ```bash
   cd shore-pty-service && npm start
   ```
   Expect log: `shore-pty-service listening { host: '127.0.0.1', port: 9100 }`.

2. **Start FastAPI with node backend**
   ```bash
   cd back-end
   $env:TERMINAL_BACKEND="node"
   python -m uvicorn app.main:app --reload --port 9000
   ```

3. **Frontend test — one-shot**
   - In chat, ask: "run git status"
   - Expect xterm one-shot panel shows output, LLM summarizes.

4. **Frontend test — PTY session**
   - Open a new session tab "dev" (powershell).
   - Type `Get-Process | Select-Object -First 5` and press Enter.
   - Expect ANSI-colored process list in xterm.

5. **Resilience — kill Node mid-flight**
   - With a session open, kill the Node process.
   - Expect frontend tab gets a `terminal_session_closed` (reason: `node_disconnect`).
   - Restart Node: `npm start`.
   - Open a new session — should succeed (Python auto-reconnected).

6. **Fallback test**
   - Stop Node, set `TERMINAL_BACKEND=pywinpty`, restart FastAPI.
   - Repeat steps 3–4 — should still work via pywinpty.

## Pass criteria
- All 6 steps complete without manual intervention beyond what's listed.
- No tracebacks in FastAPI logs except those caused by step 5's intentional kill.
