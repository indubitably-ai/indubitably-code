import sys
import json
from typing import Callable, Dict, Any, List
from anthropic import Anthropic


ToolFunc = Callable[[Dict[str, Any]], str]


class Tool:
    def __init__(self, name: str, description: str, input_schema: Dict[str, Any], fn: ToolFunc):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.fn = fn


def run_agent(tools: List["Tool"]) -> None:
    client = Anthropic()
    conversation: List[Dict[str, Any]] = []

    print("Chat with Claude (ctrl-c to quit)")
    read_user = True

    while True:
        if read_user:
            line = sys.stdin.readline()
            if not line:
                break
            conversation.append({"role": "user", "content": [{"type": "text", "text": line.rstrip('\n')}]})

        tool_defs = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

        msg = client.messages.create(
            model="claude-3-7-sonnet-latest",
            max_tokens=1024,
            messages=conversation,
            tools=tool_defs,
        )

        conversation.append({"role": "assistant", "content": msg.content})

        tool_results_content: List[Dict[str, Any]] = []
        for block in msg.content:
            if block.type == "text":
                print(f"Claude: {block.text}")
            elif block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                # Log the tool invocation with full input
                try:
                    print(f"tool_use: {tool_name} input={json.dumps(tool_input, ensure_ascii=False)}")
                except Exception:
                    # Fallback if input isn't JSON-serializable as-is
                    print(f"tool_use: {tool_name} input={tool_input}")

                impl = next((t for t in tools if t.name == tool_name), None)
                if impl is None:
                    print(f"tool_use: {tool_name} error=tool not found")
                    tool_results_content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": "tool not found",
                            "is_error": True,
                        }
                    )
                else:
                    try:
                        result_str = impl.fn(tool_input)
                        print(f"tool_use: {tool_name} result={result_str}")
                        tool_results_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result_str,
                                "is_error": False,
                            }
                        )
                    except Exception as e:
                        print(f"tool_use: {tool_name} error={str(e)}")
                        tool_results_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": str(e),
                                "is_error": True,
                            }
                        )

        if not tool_results_content:
            read_user = True
            continue

        conversation.append({"role": "user", "content": tool_results_content})
        read_user = False


