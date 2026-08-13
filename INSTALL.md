# Installing BioResearch AI

The fastest way to get BioResearch AI running on any machine is:

```bash
git clone https://github.com/grfone/bioresearch-ai.git
cd bioresearch-ai
python3 bootstrap.py
```

That's it. `bootstrap.py` is the single entry point. It detects your
operating system, installs Docker if needed, builds the container image,
brings the backend and (optionally) the local Ollama service up, opens
a first-run GUI that asks for your LLM credentials, probes each one
live, and finally opens the running app in your default browser.

Re-running `python3 bootstrap.py` is safe — it is idempotent. It
reuses the existing Docker image and only re-prompts when the `.env`
file is missing.

---

## What bootstrap.py does

| Step | What happens |
|------|--------------|
| 1. Detect OS / hardware | Reads `platform.system()`, sizes RAM, looks for an NVIDIA GPU via `nvidia-smi`. |
| 2. Install Docker | Uses the OS package manager (`apt-get`, `dnf`, `pacman`, or Homebrew on macOS). Prints a clear error on Windows without WSL2. |
| 3. Build the image | Runs `docker build -t bioresearch-ai:latest .` once (~5 minutes cold). |
| 4. Open the GUI | A Tkinter window asks for `LLM provider`, `API key`, `Base URL`, `Model`, `PubMed email`, and `PubMed API key`. Choosing `local` pulls a quantized DeepSeek model sized for your hardware. |
| 5. Probe credentials | A background thread calls `scripts/probe_credentials.py` to verify each key before saving. Failures produce actionable hints (e.g. *“Your OpenAI key looks invalid — check the value and try again.”*). |
| 6. Save `.env` | Writes the values to `.env` (chmod 600, owner-only) so the next run is silent. |
| 7. Pull the local model | When `local` is chosen, `docker exec ollama ollama pull <model>` runs. |
| 8. Start containers | `docker compose up -d --build`. |
| 9. Wait for backend | Polls `http://localhost:8000/api` until 200. |
| 10. Open browser | `http://localhost:8000` is opened in the default browser. |

---

## Choosing the LLM

The GUI offers two providers out of the box:

### Cloud (22 providers)

The GUI lists every provider in the catalog, grouped by region:

**US**
- OpenAI (`gpt-4.1`, `gpt-4.1-mini`, `o3`, `o4-mini` …)
- Anthropic (`claude-3-5-sonnet`, `claude-3-5-haiku`, `claude-opus-4`)
- Google Gemini (`gemini-2.0-flash`, `gemini-2.0-pro`)
- Azure OpenAI (uses your deployment name as the model)
- xAI Grok (`grok-3`, `grok-3-mini`, `grok-3-fast`)
- Perplexity (`llama-3.1-sonar-large-128k-online`)

**EU**: Mistral AI (`mistral-large-latest`, `mistral-medium`)

**CA**: Cohere (`command-r-plus`)

**China (14 providers)**
- DeepSeek (`deepseek-chat`, `deepseek-reasoner`)
- MiniMax, the model you already use (`MiniMax-M3`)
- Moonshot Kimi (`moonshot-v1-32k`, `moonshot-v1-128k`)
- Zhipu GLM (`glm-4-plus`, `glm-4-air`)
- Alibaba Qwen (`qwen-plus`, `qwen-max`, `qwen-coder-plus`)
- Baidu Qianfan / ERNIE (`ernie-4.0-8k`)
- Tencent Hunyuan (`hunyuan-pro`)
- ByteDance Doubao (`doubao-pro-32k`)
- Baichuan (`baichuan4-turbo`)
- 01.AI Yi (`yi-large`)
- SenseTime SenseChat (`SenseChat-5`)
- iFlytek Spark (`generalv3.5`)
- StepFun (`step-1v-32k`)
- Huawei Pangu (`pangu-4`)

Plus **Local** (self-hosted Ollama) at the top of the picker.

The picker fills the default `Base URL`, `Model`, and the API-key
environment variable name per provider. The provider list lives in
`app/application/services/llm_provider_catalog.py` — adding a new
provider is one entry in that file.

### Local (self-hosted Ollama)

Pick `local`. The GUI inspects your machine and suggests a model
tier that fits comfortably:

| Hardware profile | Recommended model |
|------------------|-------------------|
| NVIDIA GPU with ≥ 8 GB VRAM | `deepseek-r1-distill-llama-8b-q4_k_m` |
| CPU only, ≥ 16 GB RAM | `deepseek-coder-v2-lite-instruct-q4_k_m` |
| CPU only, 8–16 GB RAM | `deepseek-coder-v2-lite-instruct-q3_k_m` |
| Less than 8 GB RAM | Not recommended — the GUI warns and the model will fail to load. |

On Apple Silicon, Ollama uses the Metal GPU automatically. The
picker treats any macOS as “GPU available” and lets the model tier
take its best guess.

The model is pulled inside the `ollama` container
(`docker exec bioresearch-ai-ollama ollama pull <model>`). The
download is several GB; the bootstrap polls the container’s
progress bar.

---

## Daily workflow

Once installed, the app is reachable at <http://localhost:8000>.
The data and the SQLite database live next to the checkout:

```bash
docker compose ps              # see which containers are running
docker compose logs -f backend  # follow the backend logs
docker compose down            # stop everything
python3 bootstrap.py           # resume / reconfigure
```

The workspace database (`bioresearch.db`) is bind-mounted into the
container so it survives `docker compose down` and `docker compose up`.

---

## Troubleshooting

### Docker is installed but the daemon is not reachable

On macOS / Windows, you need to launch Docker Desktop manually the
first time. Open it from the Applications folder, wait for the
whale icon in the menu bar to settle, then re-run `python3 bootstrap.py`.

On Linux, run `sudo systemctl enable --now docker` and re-run.

### Port 8000 is already in use

Stop the conflicting process (`lsof -i :8000` on macOS/Linux,
`netstat -ano | findstr :8000` on Windows) or edit
`docker-compose.yml` to publish a different host port.

### The model pull is slow

Ollama downloads from `registry.ollama.ai`. On a 100 Mbps link the
8B quantized model takes ~5 minutes. If you cancel and restart,
the partial download is cached.

### The GUI complains that Tkinter is missing

```bash
# Debian / Ubuntu
sudo apt-get install -y python3-tk

# Fedora
sudo dnf install -y python3-tkinter

# macOS (Homebrew Python)
brew install python-tk
```

### The build fails with a conda timeout

The default channel is `https://conda-forge.org/conda-forge`. If
your network is slow or blocks that host, the build will retry
three times before giving up. If retries are not enough, point
the bootstrap at a mirror:

```bash
python3 bootstrap.py --mirror https://mirrors.tuna.tsinghua.edu.cn/conda-forge
```

Popular mirrors:

- `https://conda.anaconda.cloud/conda-forge` (default; conda-forge's
  canonical host as of the 2026 transition)
- `https://mirrors.tuna.tsinghua.edu.cn/conda-forge` (China: TUNA)
- `https://mirrors.aliyun.com/conda-forge` (China: Aliyun)
- `https://conda-forge.org/conda-forge` (legacy host, being phased out)
- `https://conda.anaconda.org/conda-forge` (legacy CDN, being phased out)

The choice is saved to `.env` so subsequent runs reuse the same
mirror. You can also pass the mirror directly to `docker build`:

```bash
docker build --build-arg CONDA_CHANNEL=https://mirrors.tuna.tsinghua.edu.cn/conda-forge .
```

### The LLM probe fails

The probe prints a hint in the GUI. Common causes:

- **401 Unauthorized** — the API key is wrong or has the wrong role.
- **404 model_not_found** — pick a different model name.
- **429 rate limit** — wait a few seconds and retry.

### The local model is too slow

Quantized 8B at Q4_K_M runs at ~10 tokens/s on an RTX 2070 Super
(CUDA). On CPU only, expect 2–4 tokens/s. Use a smaller model
(Q3_K_M) or upgrade to a GPU with more VRAM.

---

## Development workflow

If you want to edit the source, prefer the two-server dev loop:

```bash
# Terminal 1 — backend with hot reload
PYTHONPATH=. uvicorn main:app --reload

# Terminal 2 — Vite dev server
cd frontend && npm install && npm run dev
```

The Vite dev server proxies to the backend on `http://localhost:8000`
and the GUI continues to work. Use this for editing TS/TSX or the
FastAPI app.

The Docker image is the production path. It is rebuilt only when
`bootstrap.py` is re-run with `--skip-gui` and the source has changed
(the compose `up` command runs `docker build` automatically because of
the `--build` flag).

---

## Uninstallation

```bash
docker compose down                       # stop and remove containers
docker image rm bioresearch-ai:latest     # remove the image
docker volume rm bioresearch-ai_ollama_models  # remove downloaded models
rm -rf .env bioresearch.db               # remove local config and data
```

The clone itself can be deleted: `rm -rf bioresearch-ai`.
