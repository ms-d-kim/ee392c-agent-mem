Read AGENTS.md first. Then read DECISIONS.md and the docstring at the top of agent/tracer.py.

Your task: implement the Tracer class in agent/tracer.py against the JSONL schema described in the module docstring.

Requirements:
- Use time.monotonic() (not time.time()) for the ts field
- Append-only writes to the output JSONL file
- Flush after each event so traces survive process crashes mid-run
- Open the file in start(), close it in stop()
- stop() must be idempotent (safe to call twice)
- emit() must be safe to call from multiple threads (use a threading.Lock)
- Create the output_path's parent directory if missing
- One JSON object per line, no embedded newlines

Do NOT:
- Implement the LangGraph agent or tools
- Modify the schema docstring
- Modify any file other than agent/tracer.py
- Add new dependencies

When done, write a one-paragraph commit message describing what you did, but do not commit yet — leave the staged changes for me to review. Do not include tool/vendor authorship tags.
