"""
Data-analyst agent.

Given a conversation (list of {"role": "user"/"assistant", "content": str}),
the agent uses Claude with a sandboxed python-execution tool to research,
fetch data (MOSPI / any public dataset), compute an answer, and return a
JSON-serializable python object for the "answer" field -- shaped exactly
how the incoming question asked.

Every step (tool calls, tool results, final answer) is appended to a JSONL
log file so a full audit trail is available at LOG_PATH.
"""
import json
import os
import subprocess
import tempfile
import time
import uuid

from anthropic import Anthropic

MODEL = "claude-sonnet-4-6"
CLIENT = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """You are a rigorous data analyst agent answering one question at a time.

You have a `run_python` tool: python3 with pandas, numpy, requests, openpyxl,
and internet access. Use it to fetch public datasets (MOSPI, data.gov.in,
Wikipedia tables, etc.), load/clean data, and compute real numeric/factual
answers. Never guess a number you could compute or look up -- fetch the data.

The user's message will specify the exact JSON shape wanted for `answer`
(e.g. {"state": "..."} or a number or a list). Read it carefully.

When you are done, call the `final_answer` tool exactly once with:
  - "answer": the answer value, matching the requested shape exactly
    (correct JSON types: string/number/bool/list/object -- not a
    stringified version of it).
Do not include any other text as your final turn besides the tool call.
"""

TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Execute a python3 script in a fresh subprocess (pandas, numpy, "
            "requests, openpyxl available; internet access allowed). "
            "Returns stdout+stderr. Use print() to see values. "
            "State does NOT persist between calls -- re-declare variables "
            "you need, or write intermediate results to /tmp files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Python source to run."}},
            "required": ["code"],
        },
    },
    {
        "name": "final_answer",
        "description": "Submit the final answer for this question. Call exactly once, when done.",
        "input_schema": {
            "type": "object",
            "properties": {"answer": {"description": "The answer, in the exact shape requested."}},
            "required": ["answer"],
        },
    },
]


def _run_python(code: str, timeout: int = 60) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        proc = subprocess.run(
            ["python3", path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = proc.stdout[-4000:]
        err = proc.stderr[-2000:]
        return f"STDOUT:\n{out}\nSTDERR:\n{err}" if err else f"STDOUT:\n{out}"
    except subprocess.TimeoutExpired:
        return "ERROR: execution timed out after %ds" % timeout
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _log(log_path: str, record: dict):
    record["ts"] = time.time()
    with open(log_path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def answer_question(history: list[dict], log_path: str) -> object:
    """history: list of {"role": "user"|"assistant", "content": str}. Returns the answer value."""
    run_id = str(uuid.uuid4())[:8]
    _log(log_path, {"run_id": run_id, "event": "start", "history": history})

    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    max_turns = 12

    for turn in range(max_turns):
        resp = CLIENT.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        _log(log_path, {"run_id": run_id, "event": "model_turn", "turn": turn,
                         "stop_reason": resp.stop_reason,
                         "content": [b.model_dump() for b in resp.content]})

        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            # Model stopped without calling final_answer -- nudge it once.
            messages.append({"role": "user", "content": "Please call the final_answer tool now."})
            continue

        tool_results = []
        final = None
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == "run_python":
                result = _run_python(block.input.get("code", ""))
                _log(log_path, {"run_id": run_id, "event": "tool_result",
                                 "tool": "run_python", "code": block.input.get("code", ""),
                                 "result": result})
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
            elif block.name == "final_answer":
                final = block.input.get("answer")
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": "recorded"})

        if final is not None:
            _log(log_path, {"run_id": run_id, "event": "final_answer", "answer": final})
            return final

        messages.append({"role": "user", "content": tool_results})

    _log(log_path, {"run_id": run_id, "event": "error", "detail": "max turns exceeded, no final_answer"})
    return None
