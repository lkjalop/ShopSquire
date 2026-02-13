#!/usr/bin/env python
"""Simple Claude CLI wrapper using Anthropic SDK."""

import os
import sys
from anthropic import Anthropic


def main():
    # Get the prompt from command line arguments
    if len(sys.argv) < 2:
        print("Usage: python claude_cli.py <prompt>")
        print("Example: python claude_cli.py 'What is 2+2?'")
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])

    # Get API key from environment
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "Error: ANTHROPIC_API_KEY environment variable not set.",
            file=sys.stderr,
        )
        print(
            "Set it with: $env:ANTHROPIC_API_KEY = 'your-key-here'",
            file=sys.stderr,
        )
        sys.exit(1)

    # Create Anthropic client and send message
    try:
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        print(message.content[0].text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
