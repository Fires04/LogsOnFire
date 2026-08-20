"""In-process fake agent: stands in for a real agent's /ws/agent connection
so REST/tailing-layer tests can exercise the resolve/browse/start_tail
request-reply flow (app/agents/registry.py) without an actual network
WebSocket. Attaches directly to the AgentConnectionRegistry with a stub that
implements `send_json` the same way a real `fastapi.WebSocket` would, and
replies according to a caller-supplied handler.

For genuine wire-level protocol coverage (serialization, auth, ping/pong)
see test_ws_agent.py, which drives a real /ws/agent WebSocket connection
instead.
"""
from __future__ import annotations

from collections.abc import Callable

from app.agents.registry import get_agent_registry

Handler = Callable[[dict], dict | None]


class FakeAgentConnection:
    def __init__(self, agent_id: str, handler: Handler) -> None:
        self.agent_id = agent_id
        self.sent: list[dict] = []
        self._handler = handler

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)
        reply = self._handler(message)
        if reply is None:
            return
        req_id = message.get("req_id")
        if req_id is not None:
            get_agent_registry().deliver(self.agent_id, req_id, reply)


def attach_fake_agent(agent_id: str, handler: Handler) -> FakeAgentConnection:
    """Registers a fake agent connection and returns it (its `.sent` list
    can be inspected afterwards). Call get_agent_registry().detach(agent_id)
    to simulate disconnect, or just let the test/fixture teardown handle it
    via the registry reset in conftest.py.
    """
    conn = FakeAgentConnection(agent_id, handler)
    get_agent_registry().attach(agent_id, conn)  # type: ignore[arg-type]
    return conn
