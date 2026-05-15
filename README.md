# RubricGuidedEssayExam (RGEE) — Modular Oral-Style Exam System

A web app for **adaptive, oral-style exams**: students get essay questions tailored to a professor-provided domain, submit answers (optionally with time-on-question), and receive **LLM-assisted grading** against a structured rubric. Sessions and results are stored locally; instructors can review attempts from a simple dashboard.

## Team — GREEN

- WL: Anis, Sahrish
- Byrnes, Nikola
- Dang, Kenny
- Gervacio, Angeles
- Lopez, Angela
- Maloney, Nigel
- Mui, Ethan
- WL: Prljic, Vojislav
- Reyna, Rodolfo
- Sanchez, Ricardo
- Tavassoli, Armin

## Features

- **Multi-question exams** (1–20 questions per session) with context carried across questions
- **Question generation** from a free-text “professor domain” plus prior questions in the session
- **Per-question grading** with rubric alignment and a **final aggregate grade** when the exam completes
- **Professor views** listing recent sessions and per-session detail (prompts, responses, grades)
- **Student entry:** the home page uses themed **Start exam** / **Resume exam** buttons. **Start exam** opens a choice between a **generated** exam (topic, level, rubric strictness) and an **instructor nominated exam** (fixed questions from analysis; student ID plus an **8-character** nominated exam ID from the instructor—the same idea as resume, but with the published nominated code).
- **Nominated exams (instructors):** after **Question analysis**, open **Nominated exams** to select scored questions (manual feedback is copied into the student-facing notes), publish, and share the **8-character** exam ID. The analysis results view summarizes how many sessions in the current filter already have a nominated exam published.
- **Mock LLM mode** for development without API keys (`MOCK_LLM=1`, defaulted by the start scripts when unset)
- **Optional RGEE_Analysis_Agent** — separate FastAPI + Uvicorn service for instructor question-analysis embeddings (keeps heavy scoring out of the main exam process when `RGEE_ANALYSIS_AGENT_URL` is set)

## Stack

- Python 3.11+ · **FastAPI** · **Uvicorn** · **Jinja2** · **SQLAlchemy** (SQLite by default)
- **Together AI** chat completions when not in mock mode (`TOGETHER_API_KEY`, model configurable)
- **Optional RGEE_Analysis_Agent** — second FastAPI + Uvicorn app for semantic question scoring over HTTP (`RGEE_ANALYSIS_AGENT_URL`)

## Prerequisites

- **Python 3.11+** for the core app; **Python 3.12 (recommended)** or **3.11 / 3.13** if you install **sentence-transformers / PyTorch** for instructor question-analysis (wheels often **do not exist for bleeding-edge releases like 3.14** yet). Check with `python3 --version` (Mac/Linux) or `py -3 --version` / `python --version` (Windows).
- **Git** (to clone the repository).

### Use Python 3.12 in a fresh venv (macOS/Linux)

After installing Python 3.12 (e.g. `brew install python@3.12`, or [python.org](https://www.python.org/downloads/), or **pyenv** with the repo’s `.python-version`),

```bash
chmod +x scripts/recreate_venv.sh
./scripts/recreate_venv.sh
```

This removes `.venv`, recreates it with 3.12 (or the next-best 3.11/3.13 on your PATH), and installs `requirements.txt` plus **`requirements-analysis.txt`** (PyTorch stack).

## How to run the app

The main app is **FastAPI** on **Uvicorn** and listens on **http://127.0.0.1:8000** by default (override with `PORT=8080 ./scripts/launch_project.sh`).

| Page | URL |
|------|-----|
| Student / home | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) |
| Start — choose generated vs nominated | [http://127.0.0.1:8000/start](http://127.0.0.1:8000/start) |
| Generated exam (customize topic and level) | [http://127.0.0.1:8000/start/generated](http://127.0.0.1:8000/start/generated) |
| Nominated exam (student ID + 8-character ID) | [http://127.0.0.1:8000/start/nominated](http://127.0.0.1:8000/start/nominated) |
| Resume in-progress exam | [http://127.0.0.1:8000/resume](http://127.0.0.1:8000/resume) |
| Professor dashboard | [http://127.0.0.1:8000/professor](http://127.0.0.1:8000/professor) |
| Question analysis | [http://127.0.0.1:8000/professor/question-analysis](http://127.0.0.1:8000/professor/question-analysis) |
| Nominated exams (publish from analysis) | [http://127.0.0.1:8000/professor/question-analysis/nomination](http://127.0.0.1:8000/professor/question-analysis/nomination) |
| API docs (Swagger) | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |

**Resume vs nominated:** **Resume** uses your student ID and the **5-character** exam code for an attempt you already started. **Nominated exam** uses your student ID and the **8-character** code your instructor published from question analysis (fixed question set).

### macOS / Linux (recommended)

1. Open a terminal and go to the project root (where this `README.md` lives).

2. **One-command startup** (creates `.venv` if needed, installs or refreshes deps when `requirements.txt` changes, creates `.env` from `.env.example` if missing, then starts Uvicorn with reload):

   ```bash
   chmod +x scripts/launch_project.sh run_dev.sh scripts/launch_analysis_agent.sh
   ./scripts/launch_project.sh
   ```

   - Sets **`MOCK_LLM=1`** by default when unset (safe local demos).  
   - If **`RGEE_ANALYSIS_AGENT_URL`** is set in `.env`, instructor question analysis calls that URL instead of running embeddings inside this process.

3. **Faster re-runs** after `.venv` already exists:

   ```bash
   ./run_dev.sh
   ```

   Same Uvicorn reload layout; exits with a hint if `.venv` is missing (run `launch_project.sh` once).

4. **Environment file:** copy and edit if you have not already:

   ```bash
   cp .env.example .env
   ```

   - **`MOCK_LLM=1`** — mock questions and grades (no API key).  
   - **`MOCK_LLM=0`** and **`TOGETHER_API_KEY`** — [Together.ai](https://api.together.xyz/) for live LLM calls.  
   - **`RGEE_ANALYSIS_AGENT_URL`** (optional) — e.g. `http://127.0.0.1:8010` when the analysis agent is running (see below).  
   - Instructor login: see comments in `.env.example` (`INSTRUCTOR_SESSION_SECRET`, credentials file path).

5. Press **Ctrl+C** to stop the server.

### Optional: RGEE_Analysis_Agent (parallel analysis service)

Same stack (**FastAPI + Uvicorn**), separate process on **port 8010**, own SQLite DB under `RGEE_Analysis_Agent/`. Use it so instructor **Question analysis** does not load PyTorch in the main exam server.

1. Second terminal:

   ```bash
   ./scripts/launch_analysis_agent.sh
   ```

2. In `.env` for the main app:

   ```bash
   RGEE_ANALYSIS_AGENT_URL=http://127.0.0.1:8010
   ```

   Optional shared secret: **`RGEE_ANALYSIS_AGENT_SECRET`** in both apps (see `.env.example`).

3. For **live** embeddings (not mock), install a Python with PyTorch wheels and set `RGEE_MOCK_QUESTION_ANALYSIS=0` on the agent; see `requirements-analysis.txt` / `scripts/recreate_venv.sh` on the main app for the analogous stack.

### Docker (main + agent)

From the repo root:

```bash
docker compose up --build
```

- Main app: **http://localhost:8000**  
- Agent health: **http://localhost:8010/health**  

Configure instructor auth via environment or a mounted credentials file as you would locally.

### Manual Uvicorn (after `source .venv/bin/activate`)

```bash
export MOCK_LLM=1
uvicorn app.main:app --reload --reload-dir app --reload-dir templates --reload-dir static --reload-dir assets --host 127.0.0.1 --port 8000
```

### Windows

Use **Git Bash** (from Git for Windows) to run the same `./scripts/launch_project.sh` and `./run_dev.sh` as on macOS/Linux, **or** use the manual steps below in Command Prompt / PowerShell.

1. Go to the project folder, e.g. `cd C:\path\to\RGEE`.

2. Create and activate a virtual environment (`py -3 -m venv .venv` or `python -m venv .venv`, then activate — see previous README patterns).

3. Install dependencies: `pip install -r requirements.txt`

4. Copy `.env`: `copy .env.example .env` (CMD) or `Copy-Item .env.example .env` (PowerShell). Edit **`MOCK_LLM`**, **`TOGETHER_API_KEY`**, and optional **`RGEE_ANALYSIS_AGENT_URL`**.

5. With `.venv` activated, start the app (include the same `--reload-dir` flags as Unix for a consistent dev experience):

   **Command Prompt:**

   ```bat
   set MOCK_LLM=1
   python -m uvicorn app.main:app --reload --reload-dir app --reload-dir templates --reload-dir static --reload-dir assets --host 127.0.0.1 --port 8000
   ```

   **PowerShell:**

   ```powershell
   $env:MOCK_LLM = "1"
   python -m uvicorn app.main:app --reload --reload-dir app --reload-dir templates --reload-dir static --reload-dir assets --host 127.0.0.1 --port 8000
   ```

6. Press **Ctrl+C** to stop the server.

### Run automated tests

From the **repository root**, with dependencies installed (the start scripts install `pytest` from `requirements.txt`):

```bash
.venv/bin/python -m pytest tests/ -v
```

Or after `source .venv/bin/activate`:

```bash
python -m pytest tests/ -v
```

Tests use **mock LLM** and an **isolated temporary SQLite database** (`tests/conftest.py`); they do not require Together.ai keys or a running analysis agent unless a test explicitly sets `RGEE_ANALYSIS_AGENT_URL` with a mock HTTP client.

## License

Add your license here if you publish the repo publicly.
