"""Flux Multi-LLM Provider Abstraction Layer

Uses Anthropic Claude API format as the internal standard.
Each provider handles format conversion internally.

Supported providers:
- anthropic: Claude (default) - claude-sonnet-4-20250514
- openai: GPT-4o, GPT-4-turbo
- google: Gemini 2.5 Pro, Gemini 2.5 Flash
- ollama: Local LLM via OpenAI-compatible API

Environment variables:
- LLM_PROVIDER: anthropic|openai|google|ollama (default: anthropic)
- LLM_MODEL: Model name (default: provider-specific default)
- ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY

Usage:
    from flux.llm import get_provider

    provider = get_provider()  # Auto-select based on env vars
    response = provider.create_message(
        messages=messages,
        system=system_prompt,
        tools=tool_schemas,
        max_tokens=4096,
    )
    # response.content = [TextBlock(...), ToolUseBlock(...), ...]
    # response.stop_reason = "end_turn" | "tool_use" | "max_tokens"
    # response.usage.input_tokens, response.usage.output_tokens
"""

from dataclasses import dataclass, field
from typing import Any

from flux.logging import get_logger

logger = get_logger("llm")


# ============================================================
# Unified Response Objects (Anthropic format compatible)
# ============================================================

@dataclass
class ToolUseBlock:
    """Tool call block (Anthropic tool_use compatible)"""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class TextBlock:
    """Text block (Anthropic text compatible)"""
    type: str = "text"
    text: str = ""


@dataclass
class Usage:
    """Token usage"""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamEvent:
    """Streaming event

    type:
      - "text_delta": Text chunk (data = str)
      - "tool_use_start": Tool call start (data = {"id": str, "name": str})
      - "tool_use_delta": Tool input chunk (data = {"id": str, "partial_json": str})
      - "tool_use_end": Tool call complete (data = {"id": str, "name": str, "input": dict})
      - "message_start": Message start (data = {"model": str})
      - "message_end": Message end (data = {"stop_reason": str, "usage": Usage})
      - "content_complete": Full content complete (data = LLMResponse)
      - "error": Error (data = str)
    """
    type: str
    data: Any = None


@dataclass
class LLMResponse:
    """Unified provider response (Anthropic format compatible)

    Maintains the existing access pattern:
    response.content, response.stop_reason,
    response.usage.input_tokens, etc.
    """
    content: list = field(default_factory=list)  # [TextBlock, ToolUseBlock, ...]
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"
    usage: Usage = field(default_factory=Usage)
    raw: Any = None  # Raw response (for debugging)


# ============================================================
# Base Provider Class
# ============================================================

class BaseLLMProvider:
    """LLM provider base class

    All providers inherit from this class and implement
    the Anthropic-style interface.
    """

    PROVIDER_NAME = "base"
    DEFAULT_MODEL = ""

    def __init__(self, api_key: str, model: str = None):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL

    def create_message(self, messages, system="", tools=None, max_tokens=4096) -> LLMResponse:
        """Create a message (Anthropic-compatible interface)

        Args:
            messages: Anthropic format message list
                      [{"role": "user", "content": "..."}, ...]
            system: System prompt string
            tools: Anthropic format tool schema list
                   [{"name": "...", "description": "...", "input_schema": {...}}, ...]
            max_tokens: Maximum output tokens

        Returns:
            LLMResponse: Unified response object
        """
        raise NotImplementedError

    def create_message_stream(self, messages, system="", tools=None, max_tokens=4096):
        """Streaming message creation (generator).

        Yields:
            StreamEvent

        Default implementation: calls create_message() and yields result at once.
        Override per-provider for true streaming.
        """
        # Default fallback: non-streaming behavior
        response = self.create_message(messages, system, tools, max_tokens)
        yield StreamEvent(type="message_start", data={"model": self.model})
        for block in response.content:
            if hasattr(block, "text") and block.text:
                yield StreamEvent(type="text_delta", data=block.text)
            elif hasattr(block, "name") and block.name:
                yield StreamEvent(type="tool_use_start", data={"id": block.id, "name": block.name})
                yield StreamEvent(type="tool_use_end", data={"id": block.id, "name": block.name, "input": block.input})
        yield StreamEvent(type="message_end", data={"stop_reason": response.stop_reason, "usage": response.usage})
        yield StreamEvent(type="content_complete", data=response)

    def convert_tools(self, anthropic_tools):
        """Convert Anthropic tool schema to this provider's format"""
        raise NotImplementedError

    def convert_messages(self, anthropic_messages, system=""):
        """Convert Anthropic messages to this provider's format"""
        raise NotImplementedError


# ============================================================
# Anthropic Provider
# ============================================================

class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude provider

    Wraps the existing anthropic.Anthropic usage.
    No format conversion needed since Anthropic is the internal standard.
    """

    PROVIDER_NAME = "anthropic"
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key, model=None):
        super().__init__(api_key, model)
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def create_message(self, messages, system="", tools=None, max_tokens=4096):
        logger.debug(f"Anthropic API call: model={self.model}")
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        # Convert Anthropic response to LLMResponse
        content = []
        for block in response.content:
            if block.type == "text":
                content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                content.append(ToolUseBlock(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                ))

        return LLMResponse(
            content=content,
            stop_reason=response.stop_reason,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            raw=response,
        )

    def create_message_stream(self, messages, system="", tools=None, max_tokens=4096):
        """Anthropic streaming (client.messages.stream() context manager)"""
        logger.debug("Anthropic streaming API call: model=%s", self.model)
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        yield StreamEvent(type="message_start", data={"model": self.model})

        content = []
        current_tool = None
        tool_json_parts = []

        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                # text delta
                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    yield StreamEvent(type="text_delta", data=event.delta.text)

                # tool_use start
                elif event.type == "content_block_start" and hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                    current_tool = {"id": event.content_block.id, "name": event.content_block.name}
                    tool_json_parts = []
                    yield StreamEvent(type="tool_use_start", data={"id": current_tool["id"], "name": current_tool["name"]})

                # tool input delta
                elif event.type == "content_block_delta" and hasattr(event.delta, "partial_json"):
                    tool_json_parts.append(event.delta.partial_json)
                    if current_tool:
                        yield StreamEvent(type="tool_use_delta", data={"id": current_tool["id"], "partial_json": event.delta.partial_json})

                # content block stop
                elif event.type == "content_block_stop":
                    if current_tool:
                        import json as _json
                        full_json = "".join(tool_json_parts)
                        try:
                            tool_input = _json.loads(full_json) if full_json else {}
                        except _json.JSONDecodeError:
                            tool_input = {}
                        yield StreamEvent(type="tool_use_end", data={"id": current_tool["id"], "name": current_tool["name"], "input": tool_input})
                        content.append(ToolUseBlock(id=current_tool["id"], name=current_tool["name"], input=tool_input))
                        current_tool = None
                        tool_json_parts = []

            # Assemble final message
            final_message = stream.get_final_message()

        # Reconstruct content
        final_content = []
        for block in final_message.content:
            if block.type == "text":
                final_content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                final_content.append(ToolUseBlock(id=block.id, name=block.name, input=block.input))

        response = LLMResponse(
            content=final_content,
            stop_reason=final_message.stop_reason,
            usage=Usage(
                input_tokens=final_message.usage.input_tokens,
                output_tokens=final_message.usage.output_tokens,
            ),
            raw=final_message,
        )
        yield StreamEvent(type="message_end", data={"stop_reason": response.stop_reason, "usage": response.usage})
        yield StreamEvent(type="content_complete", data=response)

    def convert_tools(self, anthropic_tools):
        """Anthropic format is the internal standard, no conversion needed"""
        return anthropic_tools

    def convert_messages(self, anthropic_messages, system=""):
        """Anthropic format is the internal standard, no conversion needed"""
        return anthropic_messages


# ============================================================
# OpenAI Provider
# ============================================================

class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT provider

    Converts Anthropic format input to OpenAI format,
    and OpenAI responses to unified LLMResponse.

    Key conversions:
    - system message included in messages array
    - tool_result (Anthropic) -> tool role (OpenAI)
    - input_schema (Anthropic) -> parameters (OpenAI)
    - stop_reason mapping: stop->end_turn, tool_calls->tool_use, length->max_tokens
    """

    PROVIDER_NAME = "openai"
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key, model=None):
        super().__init__(api_key, model)
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError(
                "openai package is required: pip install openai"
            )

    def convert_tools(self, anthropic_tools):
        """Anthropic -> OpenAI tool format conversion

        Anthropic:
          {"name": "x", "description": "y",
           "input_schema": {"type": "object", "properties": {...}, "required": [...]}}

        OpenAI:
          {"type": "function", "function":
           {"name": "x", "description": "y",
            "parameters": {"type": "object", "properties": {...}, "required": [...]}}}
        """
        if not anthropic_tools:
            return None

        openai_tools = []
        for tool in anthropic_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "input_schema",
                        {"type": "object", "properties": {}}
                    ),
                },
            })
        return openai_tools

    def convert_messages(self, anthropic_messages, system=""):
        """Anthropic -> OpenAI message format conversion

        Key differences:
        - OpenAI: system message is first element in messages array
        - Anthropic tool_result -> OpenAI tool role
        - Anthropic assistant content list (TextBlock + ToolUseBlock mix)
          -> OpenAI assistant message (content + tool_calls)
        """
        import json as _json

        openai_messages = []

        if system:
            openai_messages.append({"role": "system", "content": system})

        for msg in anthropic_messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                if isinstance(content, str):
                    openai_messages.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    # tool_result list or text block list
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            tool_content = item.get("content", "")
                            if isinstance(tool_content, list):
                                # Extract text from content list
                                parts = []
                                for part in tool_content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        parts.append(part.get("text", ""))
                                    else:
                                        parts.append(str(part))
                                tool_content = "\n".join(parts)
                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": item.get("tool_use_id", ""),
                                "content": str(tool_content),
                            })
                        elif isinstance(item, dict) and item.get("type") == "text":
                            openai_messages.append({
                                "role": "user",
                                "content": item.get("text", ""),
                            })
                        else:
                            openai_messages.append({
                                "role": "user",
                                "content": str(item),
                            })
                else:
                    openai_messages.append({"role": "user", "content": str(content)})

            elif role == "assistant":
                if isinstance(content, str):
                    openai_messages.append({"role": "assistant", "content": content})
                elif isinstance(content, list):
                    # Handle mixed TextBlock + ToolUseBlock
                    text_parts = []
                    tool_calls = []

                    for block in content:
                        # dataclass objects (TextBlock, ToolUseBlock) or dict
                        block_type = getattr(block, "type", None) or (
                            block.get("type") if isinstance(block, dict) else None
                        )

                        if block_type == "text":
                            text = getattr(block, "text", None)
                            if text is None and isinstance(block, dict):
                                text = block.get("text", "")
                            text_parts.append(text or "")

                        elif block_type == "tool_use":
                            block_id = getattr(block, "id", None)
                            block_name = getattr(block, "name", None)
                            block_input = getattr(block, "input", None)
                            if block_id is None and isinstance(block, dict):
                                block_id = block.get("id", "")
                                block_name = block.get("name", "")
                                block_input = block.get("input", {})

                            tool_calls.append({
                                "id": block_id or "",
                                "type": "function",
                                "function": {
                                    "name": block_name or "",
                                    "arguments": _json.dumps(
                                        block_input or {}, ensure_ascii=False
                                    ),
                                },
                            })

                    assistant_msg = {"role": "assistant"}
                    if text_parts:
                        assistant_msg["content"] = "\n".join(text_parts)
                    else:
                        assistant_msg["content"] = None
                    if tool_calls:
                        assistant_msg["tool_calls"] = tool_calls
                    openai_messages.append(assistant_msg)
                else:
                    openai_messages.append({
                        "role": "assistant",
                        "content": str(content),
                    })

        return openai_messages

    def create_message(self, messages, system="", tools=None, max_tokens=4096):
        import json as _json

        logger.debug(f"OpenAI API call: model={self.model}")
        openai_messages = self.convert_messages(messages, system)
        openai_tools = self.convert_tools(tools) if tools else None

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": openai_messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = self.client.chat.completions.create(**kwargs)

        # OpenAI response -> unified format
        choice = response.choices[0]
        content = []

        if choice.message.content:
            content.append(TextBlock(text=choice.message.content))

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = _json.loads(tc.function.arguments)
                except (_json.JSONDecodeError, TypeError):
                    args = {}
                content.append(ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        # stop_reason mapping: OpenAI -> Anthropic compatible
        stop_reason_map = {
            "stop": "end_turn",
            "tool_calls": "tool_use",
            "length": "max_tokens",
            "content_filter": "end_turn",
        }
        stop_reason = stop_reason_map.get(choice.finish_reason, "end_turn")

        return LLMResponse(
            content=content,
            stop_reason=stop_reason,
            usage=Usage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            ),
            raw=response,
        )

    def create_message_stream(self, messages, system="", tools=None, max_tokens=4096):
        """OpenAI streaming"""
        import json as _json

        logger.debug("OpenAI streaming API call: model=%s", self.model)
        openai_messages = self.convert_messages(messages, system)
        openai_tools = self.convert_tools(tools) if tools else None

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": openai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        yield StreamEvent(type="message_start", data={"model": self.model})

        content = []
        tool_calls_acc = {}  # index -> {id, name, args_parts}
        finish_reason = None
        usage_data = None

        stream_response = self.client.chat.completions.create(**kwargs)
        for chunk in stream_response:
            if not chunk.choices and hasattr(chunk, "usage") and chunk.usage:
                usage_data = Usage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )
                continue

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason or finish_reason

            # text delta
            if delta and delta.content:
                yield StreamEvent(type="text_delta", data=delta.content)

            # tool calls
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc.id or "", "name": "", "args_parts": []}
                        if tc.function and tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                            yield StreamEvent(type="tool_use_start", data={"id": tc.id or "", "name": tc.function.name})
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["args_parts"].append(tc.function.arguments)
                        yield StreamEvent(type="tool_use_delta", data={"id": tool_calls_acc[idx]["id"], "partial_json": tc.function.arguments})

        # Complete tool calls
        for idx in sorted(tool_calls_acc.keys()):
            tc_data = tool_calls_acc[idx]
            full_args = "".join(tc_data["args_parts"])
            try:
                tool_input = _json.loads(full_args) if full_args else {}
            except _json.JSONDecodeError:
                tool_input = {}
            yield StreamEvent(type="tool_use_end", data={"id": tc_data["id"], "name": tc_data["name"], "input": tool_input})
            content.append(ToolUseBlock(id=tc_data["id"], name=tc_data["name"], input=tool_input))

        # stop_reason mapping
        stop_map = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}
        stop_reason = stop_map.get(finish_reason, "end_turn")

        if not usage_data:
            usage_data = Usage()

        response = LLMResponse(
            content=content,
            stop_reason=stop_reason,
            usage=usage_data,
        )
        yield StreamEvent(type="message_end", data={"stop_reason": stop_reason, "usage": usage_data})
        yield StreamEvent(type="content_complete", data=response)


# ============================================================
# Google Gemini Provider
# ============================================================

class GoogleProvider(BaseLLMProvider):
    """Google Gemini provider

    Converts Anthropic format input to Gemini format,
    and Gemini responses to unified LLMResponse.

    Key conversions:
    - role: assistant -> model
    - tool_result -> function_response Part
    - tool_use -> function_call Part
    - system passed as GenerativeModel system_instruction
    - UUID generated instead of tool_use_id (Gemini has no tool ID)
    """

    PROVIDER_NAME = "google"
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key, model=None):
        super().__init__(api_key, model)
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.genai = genai
        except ImportError:
            raise ImportError(
                "google-generativeai package is required: "
                "pip install google-generativeai"
            )

    def convert_tools(self, anthropic_tools):
        """Anthropic -> Google Gemini tool format conversion

        Anthropic input_schema -> Gemini FunctionDeclaration parameters
        """
        if not anthropic_tools:
            return None

        function_declarations = []
        for tool in anthropic_tools:
            schema = tool.get("input_schema", {})
            params = {
                "type": schema.get("type", "object"),
                "properties": schema.get("properties", {}),
            }
            if "required" in schema:
                params["required"] = schema["required"]

            function_declarations.append(
                self.genai.protos.FunctionDeclaration(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    parameters=params,
                )
            )

        return self.genai.protos.Tool(
            function_declarations=function_declarations
        )

    def _resolve_tool_name(self, tool_use_id, messages):
        """Resolve tool name from tool_use_id by searching previous messages

        Gemini's function_response requires the function name,
        but Anthropic's tool_result only has tool_use_id, so we look up
        the tool name from previous assistant messages.
        """
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                block_type = getattr(block, "type", None) or (
                    block.get("type") if isinstance(block, dict) else None
                )
                if block_type != "tool_use":
                    continue
                block_id = getattr(block, "id", None)
                if block_id is None and isinstance(block, dict):
                    block_id = block.get("id")
                if block_id == tool_use_id:
                    block_name = getattr(block, "name", None)
                    if block_name is None and isinstance(block, dict):
                        block_name = block.get("name")
                    return block_name or "unknown"
        return "unknown"

    def convert_messages(self, anthropic_messages, system=""):
        """Anthropic -> Gemini message format conversion

        Gemini uses only "user" and "model" roles.
        tool_result is converted to function_response Part.
        tool_use is converted to function_call Part.
        """
        gemini_history = []

        for msg in anthropic_messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                if isinstance(content, str):
                    gemini_history.append({
                        "role": "user",
                        "parts": [content],
                    })
                elif isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            # tool_result -> function_response
                            tool_use_id = item.get("tool_use_id", "unknown")
                            tool_name = self._resolve_tool_name(
                                tool_use_id, anthropic_messages
                            )
                            result_content = item.get("content", "")
                            if isinstance(result_content, list):
                                text_parts = []
                                for part in result_content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        text_parts.append(part.get("text", ""))
                                    else:
                                        text_parts.append(str(part))
                                result_content = "\n".join(text_parts)
                            parts.append(self.genai.protos.Part(
                                function_response=self.genai.protos.FunctionResponse(
                                    name=tool_name,
                                    response={"result": str(result_content)},
                                )
                            ))
                        elif isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
                        else:
                            parts.append(str(item))
                    if parts:
                        gemini_history.append({"role": "user", "parts": parts})

            elif role == "assistant":
                if isinstance(content, str):
                    gemini_history.append({
                        "role": "model",
                        "parts": [content],
                    })
                elif isinstance(content, list):
                    parts = []
                    for block in content:
                        block_type = getattr(block, "type", None) or (
                            block.get("type") if isinstance(block, dict) else None
                        )

                        if block_type == "text":
                            text = getattr(block, "text", None)
                            if text is None and isinstance(block, dict):
                                text = block.get("text", "")
                            if text:
                                parts.append(text)

                        elif block_type == "tool_use":
                            block_name = getattr(block, "name", None)
                            block_input = getattr(block, "input", None)
                            if block_name is None and isinstance(block, dict):
                                block_name = block.get("name", "")
                                block_input = block.get("input", {})
                            parts.append(self.genai.protos.Part(
                                function_call=self.genai.protos.FunctionCall(
                                    name=block_name or "",
                                    args=block_input or {},
                                )
                            ))

                    if parts:
                        gemini_history.append({"role": "model", "parts": parts})

        return gemini_history

    def create_message(self, messages, system="", tools=None, max_tokens=4096):
        import uuid

        logger.debug(f"Google API call: model={self.model}")
        gemini_tools = [self.convert_tools(tools)] if tools else None
        gemini_history = self.convert_messages(messages, system)

        # Gemini GenerativeModel configuration
        model_kwargs = {}
        if system:
            model_kwargs["system_instruction"] = system
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools

        generation_config = self.genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
        )

        model = self.genai.GenerativeModel(self.model, **model_kwargs)

        # Gemini uses chat.send_message pattern
        # Send last message via send_message, rest as history
        if not gemini_history:
            return LLMResponse()

        if len(gemini_history) > 1:
            chat = model.start_chat(history=gemini_history[:-1])
            last_msg = gemini_history[-1]
            response = chat.send_message(
                last_msg["parts"],
                generation_config=generation_config,
            )
        else:
            chat = model.start_chat()
            response = chat.send_message(
                gemini_history[0]["parts"],
                generation_config=generation_config,
            )

        # Gemini response -> unified format
        content = []
        has_tool_calls = False

        for part in response.parts:
            if hasattr(part, "text") and part.text:
                content.append(TextBlock(text=part.text))
            elif hasattr(part, "function_call") and part.function_call:
                has_tool_calls = True
                fc = part.function_call
                content.append(ToolUseBlock(
                    id="toolu_{}".format(uuid.uuid4().hex[:24]),
                    name=fc.name,
                    input=dict(fc.args) if fc.args else {},
                ))

        # stop_reason mapping
        stop_reason = "tool_use" if has_tool_calls else "end_turn"
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "finish_reason"):
                fr = str(candidate.finish_reason)
                if "MAX_TOKENS" in fr:
                    stop_reason = "max_tokens"

        # usage extraction
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(
                response.usage_metadata, "prompt_token_count", 0
            ) or 0
            output_tokens = getattr(
                response.usage_metadata, "candidates_token_count", 0
            ) or 0

        return LLMResponse(
            content=content,
            stop_reason=stop_reason,
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
            raw=response,
        )

    def create_message_stream(self, messages, system="", tools=None, max_tokens=4096):
        """Google Gemini streaming"""
        import uuid

        logger.debug("Google streaming API call: model=%s", self.model)
        gemini_tools = [self.convert_tools(tools)] if tools else None
        gemini_history = self.convert_messages(messages, system)

        model_kwargs = {}
        if system:
            model_kwargs["system_instruction"] = system
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools

        generation_config = self.genai.types.GenerationConfig(max_output_tokens=max_tokens)
        model = self.genai.GenerativeModel(self.model, **model_kwargs)

        if not gemini_history:
            yield StreamEvent(type="content_complete", data=LLMResponse())
            return

        yield StreamEvent(type="message_start", data={"model": self.model})

        if len(gemini_history) > 1:
            chat = model.start_chat(history=gemini_history[:-1])
            response_stream = chat.send_message(
                gemini_history[-1]["parts"],
                generation_config=generation_config,
                stream=True,
            )
        else:
            chat = model.start_chat()
            response_stream = chat.send_message(
                gemini_history[0]["parts"],
                generation_config=generation_config,
                stream=True,
            )

        content = []
        has_tool_calls = False

        for chunk in response_stream:
            for part in chunk.parts:
                if hasattr(part, "text") and part.text:
                    yield StreamEvent(type="text_delta", data=part.text)
                elif hasattr(part, "function_call") and part.function_call:
                    has_tool_calls = True
                    fc = part.function_call
                    tool_id = "toolu_{}".format(uuid.uuid4().hex[:24])
                    tool_input = dict(fc.args) if fc.args else {}
                    yield StreamEvent(type="tool_use_start", data={"id": tool_id, "name": fc.name})
                    yield StreamEvent(type="tool_use_end", data={"id": tool_id, "name": fc.name, "input": tool_input})
                    content.append(ToolUseBlock(id=tool_id, name=fc.name, input=tool_input))

        stop_reason = "tool_use" if has_tool_calls else "end_turn"

        # Get final response via resolve()
        try:
            final_response = response_stream.resolve()
            if hasattr(final_response, "candidates") and final_response.candidates:
                candidate = final_response.candidates[0]
                if hasattr(candidate, "finish_reason"):
                    fr = str(candidate.finish_reason)
                    if "MAX_TOKENS" in fr:
                        stop_reason = "max_tokens"

            input_tokens = 0
            output_tokens = 0
            if hasattr(final_response, "usage_metadata") and final_response.usage_metadata:
                input_tokens = getattr(final_response.usage_metadata, "prompt_token_count", 0) or 0
                output_tokens = getattr(final_response.usage_metadata, "candidates_token_count", 0) or 0
            usage_data = Usage(input_tokens=input_tokens, output_tokens=output_tokens)
        except Exception:
            usage_data = Usage()

        response = LLMResponse(content=content, stop_reason=stop_reason, usage=usage_data)
        yield StreamEvent(type="message_end", data={"stop_reason": stop_reason, "usage": usage_data})
        yield StreamEvent(type="content_complete", data=response)


# ============================================================
# Ollama Provider
# ============================================================

class OllamaProvider(OpenAIProvider):
    """Ollama local LLM provider (OpenAI-compatible API)

    Ollama provides an OpenAI-compatible API at http://localhost:11434/v1.
    Reuses all message/tool conversion logic from OpenAIProvider.

    Usage:
        provider = OllamaProvider(model="llama3.1:8b")
        response = provider.create_message(messages=[...], max_tokens=500)
    """

    PROVIDER_NAME = "ollama"
    DEFAULT_MODEL = "llama3.1:8b"

    def __init__(self, model=None, base_url="http://localhost:11434/v1", api_key="ollama", timeout=120.0):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        except ImportError:
            raise ImportError(
                "openai package is required: pip install openai"
            )


# ============================================================
# Provider Factory
# ============================================================

PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
    "ollama": OllamaProvider,
}

DEFAULT_PROVIDER = "anthropic"


def get_provider(provider_name=None, model=None, api_key=None):
    """Create an LLM provider from environment variables or arguments.

    Args:
        provider_name: "anthropic"|"openai"|"google"|"ollama"
                       If None, uses LLM_PROVIDER env var (default: anthropic)
        model: Model name. If None, uses LLM_MODEL env var or provider default
        api_key: API key. If None, auto-discovers from environment

    Returns:
        BaseLLMProvider instance

    Raises:
        ValueError: Unknown provider or missing API key
        ImportError: Provider library not installed

    Examples:
        # Environment-based (most common)
        provider = get_provider()

        # Explicit specification
        provider = get_provider("openai", model="gpt-4-turbo")

        # Direct API key
        provider = get_provider("anthropic", api_key="sk-ant-...")
    """
    import os

    provider_name = provider_name or os.environ.get(
        "LLM_PROVIDER", DEFAULT_PROVIDER
    )
    model = model or os.environ.get("LLM_MODEL")

    provider_cls = PROVIDERS.get(provider_name)
    if not provider_cls:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(
            f"Unknown provider: {provider_name}. Available: {available}"
        )

    # Auto-discover API key
    if not api_key:
        key_env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
            "ollama": "OLLAMA_API_KEY",
        }
        env_name = key_env_map.get(provider_name, "")
        api_key = os.environ.get(env_name, "")
        if not api_key:
            if provider_name == "ollama":
                api_key = "ollama"  # Ollama doesn't need real API key
            else:
                raise ValueError(
                    f"{env_name} environment variable is not set."
                )

    return provider_cls(api_key=api_key, model=model)


def list_providers():
    """Return list of available providers.

    Returns:
        list[dict]: Provider info list
            [{"name": "anthropic", "default_model": "claude-sonnet-4-20250514",
              "class": "AnthropicProvider"}, ...]
    """
    result = []
    for name, cls in PROVIDERS.items():
        result.append({
            "name": name,
            "default_model": cls.DEFAULT_MODEL,
            "class": cls.__name__,
        })
    return result
