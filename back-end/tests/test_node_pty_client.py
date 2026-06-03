import asyncio
import json
import pytest
import websockets

from app.services.node_pty_client import NodePtyClient


async def _fake_server(port: int, handler):
    async def conn(ws):
        await handler(ws)
    return await websockets.serve(conn, "127.0.0.1", port)


@pytest.fixture
async def server_factory():
    started = []
    async def factory(handler, port=19102):
        s = await _fake_server(port, handler)
        started.append(s)
        return port
    yield factory
    for s in started:
        s.close()
        await s.wait_closed()


async def test_connect_succeeds(server_factory):
    async def handler(ws):
        try:
            await ws.recv()
        except Exception:
            pass

    port = await server_factory(handler, port=19102)
    client = NodePtyClient(url=f"ws://127.0.0.1:{port}", auth_token="")
    await client.connect()
    assert client.is_connected
    await client.close()


async def test_call_returns_result(server_factory):
    async def handler(ws):
        msg = json.loads(await ws.recv())
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {"pong": True, "version": "test"},
        }))

    port = await server_factory(handler, port=19103)
    client = NodePtyClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    result = await client.call("ping", {})
    assert result == {"pong": True, "version": "test"}
    await client.close()


async def test_call_raises_on_rpc_error(server_factory):
    async def handler(ws):
        msg = json.loads(await ws.recv())
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": msg["id"],
            "error": {"code": -32002, "message": "session not found"},
        }))

    port = await server_factory(handler, port=19104)
    client = NodePtyClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    from app.services.node_pty_client import NodePtyRpcError
    with pytest.raises(NodePtyRpcError) as exc:
        await client.call("session.send", {"session_id": "x", "data": "y"})
    assert exc.value.code == -32002
    await client.close()


async def test_notification_dispatch(server_factory):
    async def handler(ws):
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "method": "session.output",
            "params": {"session_id": "s1", "data": "hello"},
        }))
        await asyncio.sleep(0.5)

    port = await server_factory(handler, port=19105)
    client = NodePtyClient(url=f"ws://127.0.0.1:{port}")
    captured = []
    async def on_notify(method, params):
        captured.append((method, params))
    client.on_notification(on_notify)
    await client.connect()
    await asyncio.sleep(0.3)
    assert ("session.output", {"session_id": "s1", "data": "hello"}) in captured
    await client.close()


async def test_in_flight_rejected_on_close(server_factory):
    async def handler(ws):
        try:
            await ws.recv()
        except Exception:
            pass
        await asyncio.sleep(0.3)
        await ws.close()

    port = await server_factory(handler, port=19106)
    client = NodePtyClient(url=f"ws://127.0.0.1:{port}")
    await client.connect()
    from app.services.node_pty_client import NodePtyRpcError

    async def make_call():
        return await client.call("ping", {}, timeout=10)

    task = asyncio.create_task(make_call())
    await asyncio.sleep(0.5)  # let server close
    with pytest.raises(NodePtyRpcError) as exc:
        await task
    assert exc.value.code == -32603
    await client.close()


async def test_reconnect_after_drop(server_factory):
    request_count = {"n": 0}

    async def handler(ws):
        request_count["n"] += 1
        if request_count["n"] == 1:
            await ws.close()
            return
        msg = json.loads(await ws.recv())
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {"pong": True, "version": "test"},
        }))
        await asyncio.sleep(0.5)

    port = await server_factory(handler, port=19107)
    client = NodePtyClient(
        url=f"ws://127.0.0.1:{port}",
        reconnect_base_ms=50,
        reconnect_max_ms=200,
    )
    client.start_auto_reconnect()
    await client.connect()
    await asyncio.sleep(0.1)  # let server close first connection
    # Should reconnect transparently
    for _ in range(20):
        if client.is_connected:
            break
        await asyncio.sleep(0.1)
    assert client.is_connected
    result = await client.call("ping", {})
    assert result["pong"] is True
    await client.close()


async def test_heartbeat_closes_on_pong_timeout(server_factory):
    async def handler(ws):
        try:
            while True:
                await ws.recv()
        except Exception:
            pass

    port = await server_factory(handler, port=19108)
    client = NodePtyClient(
        url=f"ws://127.0.0.1:{port}",
        ping_interval=0.2,
        ping_timeout=0.3,
    )
    await client.connect()
    client.start_heartbeat()
    for _ in range(20):
        if not client.is_connected:
            break
        await asyncio.sleep(0.1)
    assert not client.is_connected
    await client.close()


async def test_disconnect_callback_async(server_factory):
    async def handler(ws):
        await asyncio.sleep(0.1)
        await ws.close()

    port = await server_factory(handler, port=19110)
    client = NodePtyClient(url=f"ws://127.0.0.1:{port}")
    fired = []
    async def on_dc():
        fired.append(True)
    client.on_disconnect(on_dc)
    await client.connect()
    for _ in range(20):
        if fired:
            break
        await asyncio.sleep(0.1)
    assert fired
    await client.close()
