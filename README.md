# 🦦 Yiguirro: Deep Research Agent

A local, privacy-first Deep Research Agent that orchestrates a multi-step pipeline (Plan → Search → Filter → Map → Synthesize) using a local LLM (via Ollama) and a local SearXNG instance. 

No Docker, no cloud APIs, no data leaving your machine.

## ✨ Features
- **Deep Research Pipeline**: Automatically breaks down complex queries, searches the web, filters noise using BM25, maps findings per sub-query, and synthesizes a comprehensive final report.
- **Local-First**: Runs entirely on your hardware using Ollama and a self-hosted SearXNG instance.
- **Disk Caching**: Built-in caching system to avoid redundant LLM calls and web scrapes, saving time and compute.
- **Interactive CLI**: Clean terminal interface with helpful slash commands (`/help`, `/clear`, `/cache`, etc.).

## 🛠️ Prerequisites
Before running the agent, ensure you have the following installed and **running** on your system:
1. **Python 3.8+** (with `venv` support)
2. **Ollama**: Running locally (e.g., `ollama serve`) with a model pulled (e.g., `qwen2.5:1.5b-instruct` or your preferred model).
3. **SearXNG**: Running locally and accessible via HTTP (e.g., on port `8888`).

## 🚀 Quick Setup

1. Clone this repository:
   ```
   bash
   git clone https://github.com/TheDeGeO/yiguirro.git
   cd yiguirro
   ```

2. Run the automated setup script:
   ```
   chmod +x setup.sh
   ./setup.sh
   ```

3. Start the agent:
   ```
   cd yiguirroCoT
   venv/bin/python3 agent.py
   ```
⚙️ Configuration
The agent uses sensible defaults, but you can override them using environment variables. You can set these in your shell or by creating a .env file (if you add python-dotenv to requirements).

	
| Variable | Default | Description |
| --- | --- | --- |
| LOCAL_LM_URL | http://127.0.0.1:11434/v1/chat/completions | Your Ollama (or compatible) chat endpoint. |
| LOCAL_LM_MODEL | qwen2.5:1.5b-instruct | The main model used for reasoning and synthesis. |
| PLANNER_MODEL | qwen2.5:0.5b-instruct | Lightweight model for query planning (falls back to LOCAL_LM_MODEL if unavailable) |
| SEARXNG_URL | http://127.0.0.1:8888 | The base URL of your running SearXNG instance. |
| MAX_SEARCH_RESULTS | 10 | Max results to fetch per sub-query. |
| CACHE_ENABLED | 1 | Set to 0 to disable disk caching. |
	
🧠 Architecture (yiguirroCoT/)

    agent.py: Main orchestrator and CLI interface.
    planificador.py: Breaks the user's complex prompt into targeted sub-queries.
    buscador.py: Executes queries against SearXNG and extracts text via trafilatura.
    filtrador.py: Uses rank_bm25 to score and extract only the most relevant paragraphs.
    mapeador.py: Summarizes the filtered findings for each individual sub-query.
    sintetizador.py: Combines all mapped summaries into a cohesive, cited final report.
    cache.py: Handles persistent disk caching for LLM responses and search results.

💡 CLI Commands
While the agent is running, you can use these slash commands:

    /help : Show available commands.
    /clear : Clear the current conversation history.
    /info : Display dynamic system context (OS, CPU, model, time).
    /model : Show the currently active LLM model.
    /cache : Show disk cache statistics.
    /cache clear [ns] : Clear the cache (optionally for a specific namespace).
    /bye or /exit : Exit the agent.

📜 License
MIT License. See the LICENSE file for details.