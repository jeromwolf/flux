"""
Flux AgentEngine - Core agent runtime with tool execution loop.

Extracted from flux-openclaw ConversationEngine (740 lines) and adapted
for the flux framework with SafetyShield integration.

Design principles:
- AgentEngine does not own the messages list (caller passes by reference)
- AgentEngine does not own the provider/client (caller passes them in)
- Callback-based separation of interface-specific behavior
- Sync (run_turn) + Async (run_turn_async) support
- Streaming variants (run_turn_stream, run_turn_stream_async)
- resilience.py integration (retries, timeouts)
- config.py integration (settings)
- SafetyShield integration (budget tracking, circuit breaker)

Usage:
    from flux.engine import AgentEngine, TurnResult, BudgetExceededError

    engine = AgentEngine(
        provider=provider,
        client=None,
        tool_mgr=tool_mgr,
        system_prompt=system_prompt,
        restricted_tools={"save_text_file", "screen_capture"},
    )
    result = engine.run_turn(messages)
    # or async: result = await engine.run_turn_async(messages)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import Callable

from flux.tools.manager import ToolManager, _filter_tool_input
from flux.config import get_config
from flux.core.resilience import (
    retry_llm_call,
    retry_llm_call_async,
    with_timeout,
    with_timeout_async,
    _TimeoutError,
)
from flux.safety.shield import calculate_cost, SafetyShield
from flux.llm import StreamEvent
from flux.logging import get_logger

_logger = get_logger("engine")


class BudgetExceededError(Exception):
    """Raised when agent exceeds its budget limits."""
    pass


@dataclass
class TurnResult:
    """Result of a single conversation turn."""

    text: str = ""                  # Final text response
    tool_rounds: int = 0            # Number of tool rounds
    input_tokens: int = 0           # Total input tokens
    output_tokens: int = 0          # Total output tokens
    cost_usd: float = 0.0           # Total cost (USD)
    stop_reason: str = ""           # Last stop_reason
    error: str | None = None        # Error message (if any)


class AgentEngine:
    """Agent runtime engine with tool execution loop.

    Pass either a provider or client. If provider is given,
    provider.create_message() is used; otherwise client.messages.create().
    """

    def __init__(
        self,
        provider,
        client,
        tool_mgr: ToolManager,
        system_prompt: str,
        *,
        restricted_tools: set[str] | None = None,
        safety: SafetyShield | None = None,
        on_llm_start: Callable | None = None,
        on_tool_start: Callable | None = None,
        on_tool_end: Callable | None = None,
        on_llm_response: Callable | None = None,
    ):
        self.provider = provider
        self.client = client
        self.tool_mgr = tool_mgr
        self.system_prompt = system_prompt
        self.restricted_tools = restricted_tools or set()
        self.safety = safety
        self.on_llm_start = on_llm_start
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.on_llm_response = on_llm_response

        # Model name (for cost tracking)
        self._model_name = getattr(provider, "model", None) if provider else None

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _safety_pre_check(self) -> None:
        """Run SafetyShield pre-check before an LLM call.

        Raises BudgetExceededError if the safety check fails.
        """
        if self.safety is not None:
            ok, reason = self.safety.pre_check()
            if not ok:
                raise BudgetExceededError(reason)

    def _track_cost(self, inp: int, out: int, result: TurnResult) -> None:
        """Track cost via SafetyShield and update TurnResult accumulators."""
        cost_usd = 0.0
        if isinstance(self._model_name, str):
            cost = calculate_cost(self._model_name, inp, out)
            cost_usd = cost.total_cost_usd

        if self.safety is not None:
            self.safety.record_success(cost_usd)

        result.input_tokens += inp
        result.output_tokens += out
        result.cost_usd += cost_usd

    def _record_failure(self) -> None:
        """Record an LLM call failure in SafetyShield."""
        if self.safety is not None:
            self.safety.record_failure()

    @staticmethod
    def _serialize_content(content: list) -> list:
        """Convert content blocks (dataclass objects) to plain dicts for API serialization."""
        from dataclasses import asdict
        serialized = []
        for block in content:
            if hasattr(block, '__dataclass_fields__'):
                serialized.append(asdict(block))
            elif isinstance(block, dict):
                serialized.append(block)
            else:
                # Anthropic SDK native types — convert via dict
                serialized.append({"type": block.type, **{
                    k: v for k, v in vars(block).items() if k != "type"
                }})
        return serialized

    @staticmethod
    def trim_history(messages: list, max_history: int) -> None:
        """Trim messages in-place to at most max_history entries.

        After trimming, ensures the first message has the user role.
        """
        if len(messages) > max_history:
            messages[:] = messages[-max_history:]
            while messages and messages[0]["role"] != "user":
                messages.pop(0)

    def _tool_schemas(self) -> list:
        """Return tool schemas excluding restricted_tools."""
        if not self.restricted_tools:
            return self.tool_mgr.schemas
        return [s for s in self.tool_mgr.schemas if s["name"] not in self.restricted_tools]

    def _find_schema(self, tool_name: str):
        """Look up a tool schema by name."""
        return next((s for s in self.tool_mgr.schemas if s["name"] == tool_name), None)

    def _make_llm_call(self, messages: list, tool_schemas: list, cfg):
        """Build an LLM API call partial."""
        if self.provider:
            return partial(
                self.provider.create_message,
                messages=messages,
                system=self.system_prompt,
                tools=tool_schemas,
                max_tokens=cfg.max_tokens,
            )
        return partial(
            self.client.messages.create,
            model=cfg.default_model,
            max_tokens=cfg.max_tokens,
            system=self.system_prompt,
            tools=tool_schemas,
            messages=messages,
        )

    @staticmethod
    def _extract_text(response) -> str:
        """Extract text blocks from response content."""
        parts = []
        for block in response.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts)

    @staticmethod
    def _max_tokens_error_results(content) -> list:
        """Generate error tool_results for tool_use blocks in a max_tokens response."""
        tool_uses = [b for b in content if b.type == "tool_use"]
        if not tool_uses:
            return []
        return [{
            "type": "tool_result",
            "tool_use_id": b.id,
            "content": "Error: Response was truncated, cannot execute tool. Please try a shorter response.",
            "is_error": True,
        } for b in tool_uses]

    @staticmethod
    def _safe_result(result) -> str:
        """Convert a tool result to a safe string (escape markers)."""
        safe = str(result).replace("[TOOL OUTPUT]", "[TOOL_OUTPUT]").replace("[/TOOL OUTPUT]", "[/TOOL_OUTPUT]")
        return f"[TOOL OUTPUT]\n{safe}\n[/TOOL OUTPUT]"

    # ------------------------------------------------------------------
    # Sync method (CLI usage)
    # ------------------------------------------------------------------

    def run_turn(self, messages: list) -> TurnResult:
        """Synchronous conversation turn. Modifies messages in-place."""
        cfg = get_config()
        result = TurnResult()

        try:
            self.tool_mgr.reload_if_changed()
            self.trim_history(messages, cfg.max_history)
            tool_schemas = self._tool_schemas()
            tool_round = 0

            while tool_round < cfg.max_tool_rounds:
                if self.on_llm_start:
                    self.on_llm_start()

                # Safety pre-check before LLM call
                try:
                    self._safety_pre_check()
                except BudgetExceededError as e:
                    result.error = str(e)
                    break

                fn = self._make_llm_call(messages, tool_schemas, cfg)
                try:
                    response = retry_llm_call(
                        fn,
                        max_retries=cfg.llm_retry_count,
                        base_delay=cfg.llm_retry_base_delay,
                        max_delay=cfg.llm_retry_max_delay,
                    )
                except Exception:
                    self._record_failure()
                    raise

                if self.on_llm_response:
                    self.on_llm_response(response)

                # Usage tracking
                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                self._track_cost(inp, out, result)
                result.stop_reason = response.stop_reason

                # max_tokens handling
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                    error_results = self._max_tokens_error_results(response.content)
                    if error_results:
                        messages.append({"role": "user", "content": error_results})
                        tool_round += 1
                        continue
                    break

                # Check for tool calls
                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if not tool_uses:
                    messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                    result.text = self._extract_text(response)
                    break

                # Execute tools
                messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name

                    # Block restricted tools
                    if tool_name in self.restricted_tools:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: Tool '{tool_name}' is restricted.",
                            "is_error": True,
                        })
                        continue

                    fn = self.tool_mgr.functions.get(tool_name)
                    if not fn:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: Unknown tool: {tool_name}",
                        })
                        continue

                    if self.on_tool_start:
                        self.on_tool_start(tool_name, tool_use.input)

                    try:
                        schema = self._find_schema(tool_name)
                        filtered = _filter_tool_input(tool_use.input, schema) if schema else tool_use.input
                        tool_result = with_timeout(fn, timeout_seconds=cfg.tool_timeout_seconds, **filtered)
                    except _TimeoutError:
                        tool_result = "Error: Tool execution timed out"
                    except Exception:
                        _logger.exception("Tool execution failed: %s", tool_name)
                        tool_result = "Error: Tool execution failed"

                    if self.on_tool_end:
                        self.on_tool_end(tool_name, tool_result)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": self._safe_result(tool_result),
                    })

                messages.append({"role": "user", "content": tool_results})
                tool_round += 1

            result.tool_rounds = tool_round
            if tool_round >= cfg.max_tool_rounds:
                result.error = f"Tool calls exceeded maximum of {cfg.max_tool_rounds} rounds."

        except BudgetExceededError as e:
            result.error = str(e)
        except Exception:
            _logger.exception("Exception during run_turn")
            result.error = "An error occurred while processing the request."

        return result

    # ------------------------------------------------------------------
    # Sync streaming method
    # ------------------------------------------------------------------

    def run_turn_stream(self, messages: list):
        """Synchronous streaming conversation turn. Yields StreamEvent instances.

        The last event has type "turn_complete" with data being a TurnResult.

        Usage::

            for event in engine.run_turn_stream(messages):
                if event.type == "text_delta":
                    print(event.data, end="", flush=True)
                elif event.type == "turn_complete":
                    result = event.data  # TurnResult
        """
        cfg = get_config()
        result = TurnResult()

        if not self.provider or not hasattr(self.provider, "create_message_stream"):
            # Streaming not supported: fallback to non-streaming
            result = self.run_turn(messages)
            yield StreamEvent(type="turn_complete", data=result)
            return

        try:
            self.tool_mgr.reload_if_changed()
            self.trim_history(messages, cfg.max_history)
            tool_schemas = self._tool_schemas()
            tool_round = 0

            while tool_round < cfg.max_tool_rounds:
                if self.on_llm_start:
                    self.on_llm_start()

                # Safety pre-check before LLM call
                try:
                    self._safety_pre_check()
                except BudgetExceededError as e:
                    result.error = str(e)
                    break

                # Streaming call
                try:
                    stream_gen = self.provider.create_message_stream(
                        messages=messages,
                        system=self.system_prompt,
                        tools=tool_schemas,
                        max_tokens=cfg.max_tokens,
                    )
                except Exception:
                    self._record_failure()
                    raise

                response = None
                text_parts = []

                for event in stream_gen:
                    if event.type == "text_delta":
                        text_parts.append(event.data)
                        yield event
                    elif event.type in ("tool_use_start", "tool_use_delta", "tool_use_end",
                                        "message_start", "message_end"):
                        yield event
                    elif event.type == "content_complete":
                        response = event.data
                    elif event.type == "error":
                        yield event

                if response is None:
                    break

                if self.on_llm_response:
                    self.on_llm_response(response)

                # Usage tracking
                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                self._track_cost(inp, out, result)
                result.stop_reason = response.stop_reason

                # max_tokens handling
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                    error_results = self._max_tokens_error_results(response.content)
                    if error_results:
                        messages.append({"role": "user", "content": error_results})
                        tool_round += 1
                        continue
                    break

                # Check for tool calls
                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if not tool_uses:
                    messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                    result.text = "".join(text_parts)
                    break

                # Execute tools
                messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name

                    if tool_name in self.restricted_tools:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: Tool '{tool_name}' is restricted.",
                            "is_error": True,
                        })
                        continue

                    fn = self.tool_mgr.functions.get(tool_name)
                    if not fn:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: Unknown tool: {tool_name}",
                        })
                        continue

                    if self.on_tool_start:
                        self.on_tool_start(tool_name, tool_use.input)

                    try:
                        schema = self._find_schema(tool_name)
                        filtered = _filter_tool_input(tool_use.input, schema) if schema else tool_use.input
                        tool_result = with_timeout(fn, timeout_seconds=cfg.tool_timeout_seconds, **filtered)
                    except _TimeoutError:
                        tool_result = "Error: Tool execution timed out"
                    except Exception:
                        _logger.exception("Tool execution failed: %s", tool_name)
                        tool_result = "Error: Tool execution failed"

                    if self.on_tool_end:
                        self.on_tool_end(tool_name, tool_result)

                    # Tool result event
                    yield StreamEvent(type="tool_result", data={
                        "name": tool_name, "result": str(tool_result)[:200]
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": self._safe_result(tool_result),
                    })

                messages.append({"role": "user", "content": tool_results})
                tool_round += 1
                text_parts = []  # Reset text for next round

            result.tool_rounds = tool_round
            if tool_round >= cfg.max_tool_rounds:
                result.error = f"Tool calls exceeded maximum of {cfg.max_tool_rounds} rounds."

        except BudgetExceededError as e:
            result.error = str(e)
        except Exception:
            _logger.exception("Exception during run_turn_stream")
            result.error = "An error occurred while processing the request."

        yield StreamEvent(type="turn_complete", data=result)

    # ------------------------------------------------------------------
    # Async streaming method
    # ------------------------------------------------------------------

    async def run_turn_stream_async(self, messages: list):
        """Async streaming conversation turn. Yields StreamEvent instances asynchronously.

        Usage::

            async for event in engine.run_turn_stream_async(messages):
                if event.type == "text_delta":
                    await ws.send(json.dumps({"type": "stream_delta", "text": event.data}))
                elif event.type == "turn_complete":
                    result = event.data
        """
        cfg = get_config()
        result = TurnResult()

        if not self.provider or not hasattr(self.provider, "create_message_stream"):
            result = await self.run_turn_async(messages)
            yield StreamEvent(type="turn_complete", data=result)
            return

        try:
            self.tool_mgr.reload_if_changed()
            self.trim_history(messages, cfg.max_history)
            tool_schemas = self._tool_schemas()
            tool_round = 0

            while tool_round < cfg.max_tool_rounds:
                if self.on_llm_start:
                    self.on_llm_start()

                # Safety pre-check before LLM call
                try:
                    self._safety_pre_check()
                except BudgetExceededError as e:
                    result.error = str(e)
                    break

                # Run sync streaming generator via asyncio.to_thread
                try:
                    stream_gen = await asyncio.to_thread(
                        self.provider.create_message_stream,
                        messages=messages,
                        system=self.system_prompt,
                        tools=tool_schemas,
                        max_tokens=cfg.max_tokens,
                    )
                except Exception:
                    self._record_failure()
                    raise

                response = None
                text_parts = []

                for event in stream_gen:
                    if event.type == "text_delta":
                        text_parts.append(event.data)
                        yield event
                    elif event.type in ("tool_use_start", "tool_use_delta", "tool_use_end",
                                        "message_start", "message_end"):
                        yield event
                    elif event.type == "content_complete":
                        response = event.data
                    elif event.type == "error":
                        yield event

                if response is None:
                    break

                if self.on_llm_response:
                    self.on_llm_response(response)

                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                self._track_cost(inp, out, result)
                result.stop_reason = response.stop_reason

                if response.stop_reason == "max_tokens":
                    messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                    error_results = self._max_tokens_error_results(response.content)
                    if error_results:
                        messages.append({"role": "user", "content": error_results})
                        tool_round += 1
                        continue
                    break

                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if not tool_uses:
                    messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                    result.text = "".join(text_parts)
                    break

                messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name

                    if tool_name in self.restricted_tools:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: Tool '{tool_name}' is restricted.",
                            "is_error": True,
                        })
                        continue

                    fn_tool = self.tool_mgr.functions.get(tool_name)
                    if not fn_tool:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: Unknown tool: {tool_name}",
                        })
                        continue

                    if self.on_tool_start:
                        self.on_tool_start(tool_name, tool_use.input)

                    try:
                        schema = self._find_schema(tool_name)
                        filtered = _filter_tool_input(tool_use.input, schema) if schema else tool_use.input
                        tool_result = await with_timeout_async(
                            fn_tool, timeout_seconds=cfg.tool_timeout_seconds, **filtered
                        )
                    except _TimeoutError:
                        tool_result = "Error: Tool execution timed out"
                    except Exception:
                        _logger.exception("Tool execution failed: %s", tool_name)
                        tool_result = "Error: Tool execution failed"

                    if self.on_tool_end:
                        self.on_tool_end(tool_name, tool_result)

                    yield StreamEvent(type="tool_result", data={
                        "name": tool_name, "result": str(tool_result)[:200]
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": self._safe_result(tool_result),
                    })

                messages.append({"role": "user", "content": tool_results})
                tool_round += 1
                text_parts = []

            result.tool_rounds = tool_round
            if tool_round >= cfg.max_tool_rounds:
                result.error = f"Tool calls exceeded maximum of {cfg.max_tool_rounds} rounds."

        except BudgetExceededError as e:
            result.error = str(e)
        except Exception:
            _logger.exception("Exception during run_turn_stream_async")
            result.error = "An error occurred while processing the request."

        yield StreamEvent(type="turn_complete", data=result)

    # ------------------------------------------------------------------
    # Async method (WebSocket, Telegram, Discord, Slack)
    # ------------------------------------------------------------------

    async def run_turn_async(self, messages: list) -> TurnResult:
        """Async conversation turn. Modifies messages in-place."""
        cfg = get_config()
        result = TurnResult()

        try:
            self.tool_mgr.reload_if_changed()
            self.trim_history(messages, cfg.max_history)
            tool_schemas = self._tool_schemas()
            tool_round = 0

            while tool_round < cfg.max_tool_rounds:
                if self.on_llm_start:
                    self.on_llm_start()

                # Safety pre-check before LLM call
                try:
                    self._safety_pre_check()
                except BudgetExceededError as e:
                    result.error = str(e)
                    break

                fn = self._make_llm_call(messages, tool_schemas, cfg)
                try:
                    response = await retry_llm_call_async(
                        fn,
                        max_retries=cfg.llm_retry_count,
                        base_delay=cfg.llm_retry_base_delay,
                        max_delay=cfg.llm_retry_max_delay,
                    )
                except Exception:
                    self._record_failure()
                    raise

                if self.on_llm_response:
                    self.on_llm_response(response)

                # Usage tracking
                inp = response.usage.input_tokens
                out = response.usage.output_tokens
                self._track_cost(inp, out, result)
                result.stop_reason = response.stop_reason

                # max_tokens handling
                if response.stop_reason == "max_tokens":
                    messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                    error_results = self._max_tokens_error_results(response.content)
                    if error_results:
                        messages.append({"role": "user", "content": error_results})
                        tool_round += 1
                        continue
                    break

                # Check for tool calls
                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if not tool_uses:
                    messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                    result.text = self._extract_text(response)
                    break

                # Execute tools
                messages.append({"role": "assistant", "content": self._serialize_content(response.content)})
                tool_results = []

                for tool_use in tool_uses:
                    tool_name = tool_use.name

                    # Block restricted tools
                    if tool_name in self.restricted_tools:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: Tool '{tool_name}' is restricted.",
                            "is_error": True,
                        })
                        continue

                    fn_tool = self.tool_mgr.functions.get(tool_name)
                    if not fn_tool:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error: Unknown tool: {tool_name}",
                        })
                        continue

                    if self.on_tool_start:
                        self.on_tool_start(tool_name, tool_use.input)

                    try:
                        schema = self._find_schema(tool_name)
                        filtered = _filter_tool_input(tool_use.input, schema) if schema else tool_use.input
                        tool_result = await with_timeout_async(
                            fn_tool, timeout_seconds=cfg.tool_timeout_seconds, **filtered
                        )
                    except _TimeoutError:
                        tool_result = "Error: Tool execution timed out"
                    except Exception:
                        _logger.exception("Tool execution failed: %s", tool_name)
                        tool_result = "Error: Tool execution failed"

                    if self.on_tool_end:
                        self.on_tool_end(tool_name, tool_result)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": self._safe_result(tool_result),
                    })

                messages.append({"role": "user", "content": tool_results})
                tool_round += 1

            result.tool_rounds = tool_round
            if tool_round >= cfg.max_tool_rounds:
                result.error = f"Tool calls exceeded maximum of {cfg.max_tool_rounds} rounds."

        except BudgetExceededError as e:
            result.error = str(e)
        except Exception:
            _logger.exception("Exception during run_turn_async")
            result.error = "An error occurred while processing the request."

        return result
