Read AGENTS.md first. Then read validation/synthetic.py and (optionally) agent/tracer.py.

Your task: write a NEW file validation/assert_synthetic.py that loads a synthetic trace and asserts the expected metrics.

The script:
1. Takes a JSONL trace path as argv[1] (default: traces/synthetic.jsonl)
2. Parses every line as JSON
3. Computes the metrics from the EXPECTED dictionary in validation/synthetic.py:
   - n_unique_logical_ids
   - v1_reuse_count (data.txt v1)
   - v2_reuse_count (data.txt v2)
   - duplication_factor at peak (max over time)
4. Prints PASS or FAIL for each, with actual vs expected
5. Exits 0 if all PASS, 1 if any FAIL

CRITICAL: be ADVERSARIAL. Assume the implementer made off-by-one errors. Design assertions to catch:

- Counting "create" events as "read" events (would inflate reuse_count)
- Off-by-one in step counting
- Including the "create" event in reuse_count (must be reads only)
- Computing duplication factor at task_end instead of true peak
- Treating identical content as different logical_ids due to whitespace
- Missing the test_output as its own logical_id (the implementer might have only counted 2)
- Using time.time() instead of time.monotonic() (lifetimes could go negative)

Implementation rules:
- Use only stdlib (json, sys, collections, hashlib). DO NOT import from analysis/ — that code may also be buggy and we want an independent oracle.
- For duplication_factor at peak, compute liveness intervals from create/mutate/free events, sample at 100 ms, take the max ratio of total_bytes / unique_bytes_by_logical_id.
- Print clearly which assertion failed and what the actual value was.

Output: a single new file validation/assert_synthetic.py.

Save it. Write a commit message starting with [CX] describing what you wrote and what bugs you specifically tried to catch.

Stage but do not commit.
