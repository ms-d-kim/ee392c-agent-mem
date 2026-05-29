Read AGENTS.md first. Then read validation/synthetic.py and agent/tracer.py.

Your task: implement run_synthetic() in validation/synthetic.py.

The function must emit a sequence of Tracer events that exactly matches the scenario in the module docstring:

- Step 0 (phase="task_setup"): create text "hello world" as data.txt v1
- Steps 1-3 (phase="tool_exec"): three reads of data.txt v1
- Step 4 (phase="tool_exec"): mutate data.txt to v2 ("hello world goodbye")
- Step 5 (phase="tool_exec"): run_tests, creates a test_output as a separate logical object

Implementation rules:
- Do NOT call any actual model or tool — emit Tracer events directly to simulate the agent loop
- Use time.sleep(0.01) between events so lifetimes are nonzero
- For each logical object, emit ALL representations that would be live: text, tokens, kv_estimated. Use plausible byte sizes (e.g. text len(content), tokens ~content_len/4, kv ~tokens * 800 bytes for the model's KV-per-token).
- The same content should produce the same logical_id across representations (use compute_logical_id)
- Close the tracer with .stop() at the end

After implementing, run:
   python -m validation.synthetic --output traces/synthetic.jsonl

and verify:
- The output file exists
- It has at least 15 events (rough lower bound for the scenario)
- jq '.logical_id' traces/synthetic.jsonl | sort -u | wc -l shows 3 unique logical_ids (v1 of data.txt, v2 of data.txt, test_output)

Wait — the EXPECTED dict in the file says n_unique_logical_ids = 2. That's because it didn't account for the test_output. Update EXPECTED to 3 and adjust the comment.

Write a concise commit message. Stage but do not commit. Do not include tool/vendor authorship tags.
