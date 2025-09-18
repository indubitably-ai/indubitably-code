"""Minimal non-agent chat loop against the Anthropic Messages API."""

import sys
from anthropic import Anthropic

from config import load_anthropic_config


def main() -> None:
    config = load_anthropic_config()
    client = Anthropic()
    conversation = []

    print("Chat with Samus (ctrl-c to quit)")
    for line in sys.stdin:
        user_text = line.rstrip("\n")
        conversation.append({"role": "user", "content": [{"type": "text", "text": user_text}]})

        try:
            msg = client.messages.create(
                model=config.model,
                max_tokens=config.max_tokens,
                messages=conversation,
            )
        except Exception as exc:  # pragma: no cover - surfaced to user
            print(f"Anthropic error: {exc}", file=sys.stderr)
            if conversation and conversation[-1].get("role") == "user":
                conversation.pop()
            continue

        conversation.append({"role": "assistant", "content": msg.content})

        for block in msg.content:
            if block.type == "text":
                print(f"Samus: {block.text}")


if __name__ == "__main__":
    main()
