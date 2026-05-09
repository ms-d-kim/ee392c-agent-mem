Read AGENTS.md first. Then read agent/tracer.py.

Your task: code-review agent/tracer.py. Do NOT edit any code. Output a markdown review document only.

Look specifically for:

1. Schema divergence — does the implementation match the docstring schema exactly?
2. Race conditions if emit() is called from multiple threads
3. Missing flush() calls — events must survive a process crash
4. File handle leaks (start() without stop(), exceptions in emit())
5. Edge cases in normalize_for_logical_id and compute_logical_id:
   - Empty strings
   - Unicode characters (NFC vs NFD normalization)
   - Very long content (>1MB)
   - Content that's already lowercase / whitespace-collapsed
   - Trailing/leading whitespace
6. Time monotonicity assumptions — what if start() is called twice?
7. JSONL formatting — trailing newline? embedded newlines in object_id or content?
8. Type safety — does the Literal-typed parameter actually get enforced or is it advisory?

Output format: a markdown document with severity-tagged findings:
- [BLOCKER] — must fix before any real trace
- [HIGH] — should fix before pitch
- [NIT] — style/preference

For each finding, include:
- File and line number
- Brief description
- Suggested fix (code snippet, but do NOT apply it)

Save the review as reviews/01-tracer-review.md. Do not modify agent/tracer.py.

After saving, write a commit message starting with [CX] describing what you reviewed.
