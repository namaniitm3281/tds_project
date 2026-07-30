"""
Data-analyst agent.

Given a conversation (list of {"role": "user"/"assistant", "content": str}),
the agent uses an LLM (via AI Pipe, OpenAI-compatible) with a sandboxed
python-execution tool to research, fetch data (MOSPI / any public dataset),
compute an answer, and return a JSON-serializable python object for the
"answer" field -- shaped exactly how the incoming question asked.

Every step (tool calls, tool results, final answer) is appended to a JSONL
log file so a full audit trail is available at LOG_PATH.
"""
import json
import os
import subprocess
import tempfile
import time
import uuid

from openai import OpenAI

# AI Pipe: OpenAI-compatible endpoint. Set AIPIPE_TOKEN in env.
# Check https://aipipe.org/ for the current base_url and model names
# available to you -- adjust AIPIPE_BASE_URL / AIPIPE_MODEL if different.
MODEL = os.environ.get("AIPIPE_MODEL", "openai/gpt-4.1-mini")
CLIENT = OpenAI(
    api_key=os.environ["AIPIPE_TOKEN"],
    base_url=os.environ.get("AIPIPE_BASE_URL", "https://aipipe.org/openrouter/v1"),
)

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
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute a python3 script in a fresh subprocess (pandas, numpy, "
                "requests, openpyxl available; internet access allowed). "
                "Returns stdout+stderr. Use print() to see values. "
                "State does NOT persist between calls -- re-declare variables "
                "you need, or write intermediate results to /tmp files."
            ),
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Python source to run."}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": "Submit the final answer for this question. Call exactly once, when done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"description": "The answer, in the exact shape requested. Pass as a JSON value."}
                },
                "required": ["answer"],
            },
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

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history]
    max_turns = 12

    for turn in range(max_turns):
        resp = CLIENT.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=4096,
        )
        msg = resp.choices[0].message
        _log(log_path, {"run_id": run_id, "event": "model_turn", "turn": turn,
                         "content": msg.content,
                         "tool_calls": [tc.model_dump() for tc in (msg.tool_calls or [])]})

        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            messages.append({"role": "user", "content": "Please call the final_answer tool now."})
            continue

        final = None
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            if name == "run_python":
                result = _run_python(args.get("code", ""))
                _log(log_path, {"run_id": run_id, "event": "tool_result",
                                 "tool": "run_python", "code": args.get("code", ""),
                                 "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            elif name == "final_answer":
                final = args.get("answer")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "recorded"})

        if final is not None:
            _log(log_path, {"run_id": run_id, "event": "final_answer", "answer": final})
            return final

    _log(log_path, {"run_id": run_id, "event": "error", "detail": "max turns exceeded, no final_answer"})
    return None
