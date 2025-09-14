import sys
from anthropic import Anthropic


def main() -> None:
    client = Anthropic()
    conversation = []

    print("Chat with Claude (ctrl-c to quit)")
    for line in sys.stdin:
        user_text = line.rstrip("\n")
        conversation.append({"role": "user", "content": [{"type": "text", "text": user_text}]})

        msg = client.messages.create(
            model="claude-3-7-sonnet-latest",
            max_tokens=1024,
            messages=conversation,
        )

        conversation.append({"role": "assistant", "content": msg.content})

        for block in msg.content:
            if block.type == "text":
                print(f"Claude: {block.text}")


if __name__ == "__main__":
    main()
