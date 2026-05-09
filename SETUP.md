# Setup runbook — first bring-up

Estimated time: 2–3 hours for first run. Subsequent: ~15 min to start a session.

This is the exact recipe to follow when actually bringing the stack up. Do not
deviate without updating this file. Discoveries → append to `TROUBLESHOOTING.md`.

---

## 1. Launch RunPod pod

- Template: `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`
  (verify the latest equivalent in RunPod's template catalog)
- GPU: RTX 4090 24GB on-demand
- Persistent volume: 50GB attached at `/workspace`
- SSH key registered with RunPod, SSH enabled

Note the pod IP and SSH port from the RunPod dashboard.

---

## 2. SSH in, clone repo

```bash
ssh root@<pod-ip> -p <port>
cd /workspace
git clone <repo-url> ee392c-agent-mem
cd ee392c-agent-mem
```

---

## 3. Install Python dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
```

**Expected:** ~5–10 min. vLLM pulls a lot of CUDA libs.
**Common failure:** `pynvml` import errors → ensure `nvidia-ml-py` is installed
(not the deprecated `pynvml` package).

---

## 4. Pre-download model to persistent volume

```bash
huggingface-cli login   # if model gated; Qwen2.5-Coder is open
huggingface-cli download Qwen/Qwen2.5-Coder-7B-Instruct \
    --local-dir /workspace/hf-cache/Qwen2.5-Coder-7B-Instruct
```

**Expected:** ~14 GB, 5–10 min on RunPod.

Putting it on the persistent volume means re-launching the pod doesn't re-download.

---

## 5. Launch vLLM (foreground, in tmux)

```bash
tmux new -s vllm
bash serving/launch_vllm.sh
```

**Expected:** server ready in ~60 s, listening on `:8000`. Look for
`Uvicorn running on http://0.0.0.0:8000`.

Detach the tmux session: `Ctrl-b d`. Reattach later: `tmux attach -t vllm`.

---

## 6. Smoke test the chat endpoint

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "Print hello in Python."}]
  }' | jq .
```

**Expected:** JSON response with a code completion in `choices[0].message.content`.

---

## 7. Smoke test the metrics endpoint

```bash
curl -s http://localhost:8000/metrics | grep -E "vllm:(gpu_cache|prefix_cache|num_)"
```

**Expected:** Prometheus-format metrics including `vllm:gpu_cache_usage_perc`,
`vllm:prefix_cache_queries`, `vllm:prefix_cache_hits`, `vllm:num_requests_*`.

These are what the engine-layer telemetry scrapes.

---

## 8. (Stretch, ~30 min) Install Nsight Systems

```bash
# Method 1: apt (preferred)
apt-get update
apt-get install -y nsight-systems-cli
nsys --version

# Method 2: if apt fails, download the .deb directly from
# https://developer.nvidia.com/nsight-systems and dpkg -i
```

**Drop trigger:** if install fails or requires permissions you don't have on
the RunPod container, drop nsys (per pre-committed cut #5 in DECISIONS.md).
The methodology does not depend on it.

**Smoke test:**
```bash
nsys profile -o /tmp/smoke -- python -c "import time; time.sleep(2); print('ok')"
nsys stats /tmp/smoke.nsys-rep | head -20
```
**Expected:** stats output with no errors. If it works here, it'll work on the
real agent.

---

## 9. Validate environment

```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0))"
python -c "import pynvml; pynvml.nvmlInit(); print('NVML OK')"
python -c "import psutil; print('RSS MB:', psutil.Process().memory_info().rss / 1e6)"
nvidia-smi
```

All four should run cleanly.

---

## 10. Commit pod-specific notes

If you discovered any quirks (apt package names, vLLM flag tweaks, permission
issues), append them to `TROUBLESHOOTING.md` in the repo root and commit.

---

## Next session — implementation order

Once the bring-up runbook above succeeds end-to-end, implementation order is:

1. **`agent/tracer.py`** — implement the `Tracer` class against the schema docstring.
2. **`serving/telemetry.py`** — implement `SystemTelemetry` (NVML + psutil + threading).
3. **`agent/tools.py`** + **`agent/graph.py`** — minimal LangGraph 3-tool agent.
4. **`validation/synthetic.py`** — implement the synthetic agent run.
5. **Run `validation/synthetic.py` and verify expected values** before any real trace.
6. **`analysis/load_traces.py`** + plotting — first lifetime CDF on synthetic data.
7. **First real SWE-bench task trace.**

Do step 5 carefully. If the tracer fails on synthetic, every plot from real
traces is suspect.
