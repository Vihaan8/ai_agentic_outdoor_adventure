import json
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from prompts import SYSTEM_PROMPT, TOOLS
from tools import TOOL_FUNCTIONS

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def run_agent(user_message: str, max_turns: int = 8):
    """Run the agent loop. Yields events: tool_call, tool_result, text, done."""
    messages = [{"role": "user", "content": user_message}]
    tool_calls_made = []

    for turn in range(max_turns):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            messages=messages,
        )

        text_parts = []
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        if text_parts:
            yield {"type": "text", "content": "\n".join(text_parts)}

        if response.stop_reason == "end_turn" or not tool_uses:
            yield {
                "type": "done",
                "final_text": "\n".join(text_parts),
                "tool_calls": tool_calls_made,
                "turns": turn + 1,
            }
            return

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tu in tool_uses:
            yield {"type": "tool_call", "name": tu.name, "input": tu.input}
            tool_calls_made.append({"name": tu.name, "input": tu.input})

            fn = TOOL_FUNCTIONS.get(tu.name)
            if not fn:
                result = {"error": f"unknown tool: {tu.name}"}
            else:
                try:
                    result = fn(**tu.input)
                except Exception as e:
                    result = {"error": str(e)}

            yield {"type": "tool_result", "name": tu.name, "result": result}
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
            })

        messages.append({"role": "user", "content": tool_results})

    yield {
        "type": "done",
        "final_text": "Reached max turns without finishing.",
        "tool_calls": tool_calls_made,
        "turns": max_turns,
    }


def run_agent_sync(user_message: str, max_turns: int = 8) -> dict:
    """Non-streaming version. Returns the final result + trace."""
    events = list(run_agent(user_message, max_turns))
    final = next((e for e in reversed(events) if e["type"] == "done"), None)
    return {
        "final_text": final["final_text"] if final else "",
        "tool_calls": final["tool_calls"] if final else [],
        "turns": final["turns"] if final else 0,
        "events": events,
    }
