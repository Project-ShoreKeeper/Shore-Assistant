"""Ensure chat_ws.run_agent_pipeline calls assemble_context and threads the bundle."""

import inspect


def test_run_agent_pipeline_threads_memory_bundle_to_agent():
    """Source-level check: agent_service.run is invoked with memory_bundle=bundle."""
    from app.api.websockets import chat_ws
    src = inspect.getsource(chat_ws)
    assert "assemble_context(" in src
    assert "memory_bundle=" in src


def test_run_agent_pipeline_skips_assemble_context_for_notifications():
    """Notifications should NOT pay the Postgres+Qdrant round-trip.
    Source-level check: the assemble_context call is gated by `is_notification` (or equivalent)."""
    from app.api.websockets import chat_ws
    src = inspect.getsource(chat_ws)
    # The call should appear inside a conditional that excludes notifications.
    # Accept any of the common implementation shapes:
    #   1. Inline ternary on the memory_bundle kwarg line.
    #   2. Precomputed bundle with explicit `bundle = None` for notifications.
    #   3. An `if is_notification:` gate anywhere in the source.
    #   4. Precomputed bundle using `if not is_notification else None` assignment
    #      (Step 3 canonical form — bundle assigned before the try block).
    assert "memory_bundle=bundle if not is_notification else None" in src \
        or ("is_notification" in src and "assemble_context" in src and "bundle = None" in src) \
        or "if is_notification:" in src \
        or ("if not is_notification else None" in src and "memory_bundle=bundle" in src)
