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
- **Mock LLM mode** for development without API keys (`MOCK_LLM=1`, default in `run_dev.sh`)

## Stack

- Python 3.x · **FastAPI** · **Jinja2** · **SQLAlchemy** (SQLite by default)
- **Together AI** chat completions when not in mock mode (`TOGETHER_API_KEY`, model configurable)

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

The server listens on **http://127.0.0.1:8000** by default.

| Page | URL |
|------|-----|
| Student / home | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) |
| Professor dashboard | [http://127.0.0.1:8000/professor](http://127.0.0.1:8000/professor) |
| API docs (Swagger) | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |

### macOS

1. Open **Terminal** and go to the project folder (replace the path with where you cloned the repo):

   ```bash
   cd /path/to/RubricGuidedEssayExam
   ```

2. Create a virtual environment and activate it:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment variables (optional but recommended):

   ```bash
   cp .env.example .env
   ```

   Edit `.env` in a text editor:

   - **`MOCK_LLM=1`** — uses built-in mock questions and grades (no API key; best for local demos and development).  
   - **`MOCK_LLM=0`** and a valid **`TOGETHER_API_KEY`** — uses the [Together.ai](https://api.together.xyz/) API for real LLM calls.

5. Start the development server (pick one):

   **Option A — helper script** (sets `MOCK_LLM` to `1` by default if unset, then runs Uvicorn):

   ```bash
   chmod +x run_dev.sh
   ./run_dev.sh
   ```

   **Option B — auto-launch script** (creates `.venv`, installs deps once, and starts Uvicorn):

   ```bash
   chmod +x scripts/launch_project.sh
   ./scripts/launch_project.sh
   ```

   If you also want to enable the virtual environment in your current shell session:

   ```bash
   source .venv/bin/activate
   ```

   **Option C — manual** (activate `.venv` first, then):

   ```bash
   export MOCK_LLM=1
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

6. Leave Terminal open while you use the app. Press **Ctrl+C** to stop the server.

### Windows

1. Open **Command Prompt** or **PowerShell** and go to the project folder:

   ```bat
   cd C:\path\to\RubricGuidedEssayExam
   ```

2. Create a virtual environment:

   ```bat
   py -3 -m venv .venv
   ```

   If `py` is not available, try `python -m venv .venv` instead.

3. **Activate** the virtual environment:

   - **Command Prompt:**

     ```bat
     .venv\Scripts\activate.bat
     ```

   - **PowerShell:**

     ```powershell
     .venv\Scripts\Activate.ps1
     ```

     If PowerShell blocks scripts, run once as Administrator:  
     `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

4. Install dependencies:

   ```bat
   pip install -r requirements.txt
   ```

5. Create your `.env` file from the example:

   - **Command Prompt:**

     ```bat
     copy .env.example .env
     ```

   - **PowerShell:**

     ```powershell
     Copy-Item .env.example .env
     ```

   Edit `.env` with Notepad or your editor: set **`MOCK_LLM=1`** for mock mode, or **`MOCK_LLM=0`** and **`TOGETHER_API_KEY=...`** for live Together.ai calls.

6. Start the server (with the virtual environment **still activated**):

   **Command Prompt:**

   ```bat
   set MOCK_LLM=1
   python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

   **PowerShell:**

   ```powershell
   $env:MOCK_LLM = "1"
   python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

   (`run_dev.sh` is for Unix shells; on Windows use the commands above.)

7. Press **Ctrl+C** in the terminal to stop the server.

### Run automated tests (optional)

With the virtual environment activated and dependencies installed (including `pytest` from `requirements.txt`):

```bash
python -m pytest tests/ -v
```

Mock LLM and an isolated test database are configured automatically for tests.

## License

Add your license here if you publish the repo publicly.
