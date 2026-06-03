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
