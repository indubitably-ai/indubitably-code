from typing import Dict, Any


def read_file_tool_def() -> dict:
    return {
        "name": "read_file",
        "description": "Read the contents of a given relative file path. Use for file contents. Not for directories.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to a file in the working directory.",
                }
            },
            "required": ["path"],
        },
    }


def read_file_impl(input: Dict[str, Any]) -> str:
    path = input.get("path", "")
    if not path:
        raise ValueError("missing 'path'")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


