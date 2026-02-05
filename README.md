# AI Construction Site - GeneralContractorAI

A locally-hosted, multi-agent simulation where AI agents work together to build a house in a SQLite database. Powered by **LangGraph**, **Ollama**, and **Arize Phoenix** for observability.

> **Read the narrative article explaining the concepts here:** [Build Your Own AI "General Contractor"](LINK_TO_ARTICLE)

## Features

*   **Multi-Agent Workflow**: Includes a Supervisor (Router), Specialized Workers (Foundation, Framing, etc.), an Inspector, and a Safety Guardrail.
*   **Local LLM**: Uses [Ollama](https://ollama.com/) (Llama 3 recommended) for privacy and zero cost.
*   **Persistence**: Game state is saved to a local SQLite database (`game_data/game_site.db`).
*   **Observability**: Full tracing of agent thoughts and actions using [Arize Phoenix](https://phoenix.arize.com/).
*   **Containerized**: Zero python dependency hell—runs entirely in Docker/Podman.
*   **Permit Office**: An "LLM-as-a-Judge" node that qualitatively reviews the quantitative inspections.

## Prerequisites

1.  **Docker** or **Podman** installed.
2.  **Ollama** installed locally on your host machine.
    *   Run `ollama serve` in a separate terminal.
    *   Pull the model: `ollama pull llama3` (approx 4.7GB).

## How to Run

### 1. Start Support Services (Phoenix Observability)
Start the observability platform in the background:

```bash
# For Docker
docker compose up -d phoenix

# For Podman
podman compose up -d phoenix
```
*Access the Phoenix UI at [http://localhost:6006](http://localhost:6006)*

### 2. Run the Game (Interactive Mode)
Because the game requires user input, it runs best in an interactive container.

**Using Docker:**
```bash
docker run -it --network host \
  -e PH_HOST=0.0.0.0 \
  -e PH_PORT=6006 \
  -e OLLAMA_HOST=http://host.docker.internal:11434 \
  -e PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317 \
  ai-construction-game-game
```

**Using Podman:**
This project has been tested primarily on Podman.

```bash
podman run -it --network host \
   -e PH_HOST=0.0.0.0 \
   -e PH_PORT=6006 \
   -e OLLAMA_HOST=http://localhost:11434 \
   -e PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317 \
   generalcontractorai_game
```

*(Note: If the image isn't found, build it first with `docker compose build` or `podman build -t generalcontractorai_game .`)*

## How to Play

You act as the **client**. Give orders to the construction crew.

**Example Commands:**
*   "Pour the foundation."
*   "Build the framing."
*   "Wire the house for electricity."
*   "Put the roof on."
*   "Start a fire!" (Will trigger the Safety Guardrail)
*   "Build a pool" (Will trigger the Grumpy Supervisor rejection)

**Rules:**
*   You must build in order: Foundation -> Framing -> Roof.
*   The Inspector will check the work.
*   Workers have a **30% chance of "slacking off"** (hallucinating success without writing to the DB).
*   Visualise the agent's "thoughts" in the Phoenix UI running on port 6006.

## Architecture

The system uses [LangGraph](https://python.langchain.com/docs/langgraph) to define a state machine with the following nodes:

1.  **Guardrail**: Checks for unsafe input (regex-based).
2.  **Supervisor**: Uses LLM to route intent to the correct worker resource.
3.  **Worker**: Attempts to update the SQLite database.
4.  **Inspector**: Deterministically checks the database state against the worker's claim.
5.  **Permit Office**: Uses LLM to generate a ruling based on the Inspector's findings.

## Troubleshooting

**"Connection refused" to Ollama?**
*   Ensure Ollama is running (`ollama serve`).
*   Docker/Podman needs to reach the host. The config uses `host.docker.internal` (Docker) or `localhost` (Podman with `--network host`).

**Input prompt disappears or can't type?**
*   This happens if you `attach` to a background container. Use the "Interactive Mode" command (`run -it`) instead.
