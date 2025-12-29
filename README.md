# selenium_mcp

LLM-driven, Selenium-based automated web UI testing framework that lets users write tests in plain human language instead of code or page-specific selectors. The system uses Large Language Models (LLMs) — by default this repository demonstrates an Ollama-based model integrated through LangChain / LangGraph — to interpret user instructions, map them to Selenium actions at runtime, and interact with web pages without requiring prior knowledge of the page's implementation details.

Key idea: write tests like "Go to https://example.com, log in with username X and password Y, select the first product and add it to cart" — the framework translates this natural language into step-by-step UI actions, parses the live DOM to find elements, and executes them with Selenium.

Important notes:
- selenium_mcp parses the page structure (DOM and visible metadata) at runtime to identify elements to interact with — users do not need to know the page structure or implement a Page Object Model (POM).
- The project is experimental and currently does not focus on token-efficient LLM usage.
- The repo exposes a simple "selenium mcp" library that can be reused in other applications.
- The example LLM integration uses Ollama via LangChain / LangGraph. Other LLM providers can be used by configuring the LangChain/LangGraph connector.

## Table of contents
- [Project overview](#project-overview)
- [Features](#features)
- [How it works (high level)](#how-it-works-high-level)
- [Prompts & defining user tasks](#prompts--defining-user-tasks)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Running the MCP server and Agent (separately)](#running-the-mcp-server-and-agent-separately)
- [Writing natural-language scenarios](#writing-natural-language-scenarios)
- [Configuration & secure credentials](#configuration--secure-credentials)
- [Running tests](#running-tests)
- [Test reporting & artifacts](#test-reporting--artifacts)
- [Security & privacy](#security--privacy)
- [Limitations & best practices](#limitations--best-practices)
- [Reuse as a library](#reuse-as-a-library)
- [CI / Continuous Integration](#ci--continuous-integration)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## Project overview
selenium_mcp provides a layer on top of Selenium WebDriver that:
- Accepts human-language test scenarios.
- Uses an LLM (Ollama by default, via LangChain / LangGraph) to plan a sequence of user-like UI actions (clicks, form fills, waits, navigation).
- Parses the current page structure (DOM and visible metadata) at runtime to identify UI elements and map actions to them.
- Executes the plan with Selenium on real browsers (local or remote).
- Captures structured results, screenshots, and logs for debugging.

Because the framework inspects and interprets the page at runtime, test authors do not need to create or maintain page objects or selectors — the LLM + runtime parsing determines where to click, what to type, and what to verify.

## Features
- Natural-language scenarios (no POM or selector wiring required).
- Runtime DOM parsing to find actionable elements without prior page knowledge.
- LangChain / LangGraph orchestration with an Ollama model by default (pluggable for other providers).
- Configurable browser backends (local Chrome/Firefox, remote Selenium Grid, BrowserStack/Sauce Labs).
- Screenshots and HTML capture on failure.
- Simple, reusable "selenium mcp" library/API for embedding in other tools.
- Experimental: not optimized for token efficiency — current focus is capability and clarity.

## How it works (high level)
1. User supplies a plain-language scenario (single string or a scenario file).
2. The MCP server captures a snapshot / metadata of the current page.
3. The Agent (LLM + LangChain/LangGraph) receives the instruction + page context and returns a step plan (navigate, find element by visible text, click, fill field, wait, verify).
4. The MCP server executes each step with Selenium, using DOM parsing heuristics to locate elements.
5. Results, screenshots, and logs are produced for each run.

The server/agent split separates planning (agent) from deterministic execution (server).

## Prompts & defining user tasks
User tasks and high-level instructions are provided to the Agent via prompts. The contents of these prompts drive how the Agent interprets scenarios and the level of detail in generated step plans.

- Where prompts live:
  - By default, the Agent reads its instruction template from the repository's prompts/config (or the Agent configuration). You can also supply prompt text at runtime via a CLI flag or a prompt file.
  - If you want to change Agent behavior, update the prompt template (for example, a file like prompts/default_prompt.txt) or pass a different prompt when starting the Agent.

- What to include in a prompt:
  - Clear goal statement (what the user wants to achieve).
  - Constraints and safety rules (e.g., do not send secrets, do not navigate off-domain).
  - Expected step granularity (high-level steps vs. very explicit low-level actions).
  - Any domain hints (stable labels, known selectors, or business rules).

- Example prompt (short):
  You are an agent that converts human-language test scenarios into a step-by-step Selenium plan. Use the provided DOM snapshot to locate visible elements. Avoid revealing secrets in logs. Prefer clicking by visible text, labels, or accessible names. If unsure, describe the uncertainty in the step plan.

- Editing prompts:
  - Update the prompt file or modify the Agent's configuration to alter behavior.
  - Prompts are the primary mechanism for customizing how the Agent reasons about tasks—use them to tune verbosity, safety checks, and execution preferences.

## Prerequisites
- Git
- Python 3.8+ (recommended)
- Browser(s): Chrome, Firefox, Edge (installed locally or available via remote grid)
- Matching WebDriver binaries (chromedriver / geckodriver) or a remote WebDriver endpoint
- Ollama (if using the default Ollama model) or another LLM provider configured via LangChain/LangGraph
- Docker (optional; recommended for running browsers in containers)

## Quick start
1. Clone the repo:
   git clone https://github.com/abdulsalam146/selenium_mcp.git
   cd selenium_mcp

2. Install dependencies (example for Python):
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt

3. Prepare your LLM runtime:
   - If using Ollama (recommended for the example), install Ollama locally and pull the model you plan to use.
   - Ensure the Ollama daemon / model is running and accessible to the Agent.

Other models/providers can be used through LangChain/LangGraph by changing the provider connector.

## Running the MCP server and Agent (separately)
This project runs two primary components independently:
- MCP server — responsible for Selenium browser control, DOM snapshots, and executing action steps.
- Agent — responsible for interpreting natural-language scenarios with an LLM and generating step plans. The Agent assumes the MCP server is running locally.

Start the components in separate terminals:

1. Start the MCP server:
   python selenium_mcp.py

   The server will:
   - start or connect to a Selenium session,
   - expose local endpoints for the agent to request DOM snapshots and submit execution plans,
   - write artifacts to reports/ by default.

2. Start the Agent:
   python agent.py --provider ollama --model <model-name>

   Replace <model-name> with the Ollama model name you installed (e.g., a llama2 or other model name supported by your Ollama instance).

Notes:
- The Agent assumes the MCP server is running locally; the included agent connects to the local server by default — no URL parameter is required for the standard setup.
- If you customize host/port, update the Agent configuration accordingly.

## Writing natural-language scenarios
Create a plain-text or YAML scenario describing the user intent. The framework understands common verbs and UI intents like "go to", "click", "enter", "submit", "select", "wait until", "choose product", "add to cart", etc.

Example scenario file (tests/scenarios/login_and_add_product.txt):
Go to https://example.com
Log in with username "user@example.com" and password "P@ssw0rd!"
After logging in, search for "wireless headphones"
Select the first product from the results
Add the product to the shopping cart
Verify that the cart contains 1 item and the product title contains "wireless headphones"

Because selenium_mcp parses the DOM at runtime, you do not need to supply selectors or page objects; however, adding stable hints (e.g., data-test-id) will increase reliability for critical tests.

## Configuration & secure credentials
Common settings (env vars or config file):
- LLM_PROVIDER (e.g., ollama, openai)
- LLM_MODEL (the model name used by the provider)
- TEST_BROWSER (chrome | firefox)
- BROWSER_HEADLESS (true|false)
- SELENIUM_REMOTE_URL (if using Grid or a cloud provider)
- TIMEOUT_SECONDS (default step timeout)
- MCP_SERVER_HOST / MCP_SERVER_PORT (only if customizing)

Important: Do not store secrets in plaintext in the repository. Use OS environment variables, your OS secret manager, or your CI secret store to provide any provider credentials. This README intentionally does not recommend putting all API keys into a .env file — use secure secret management for production usage.

## Running tests
- Start the MCP server:
  python selenium_mcp.py

- user task is defined in prompts.py. Explain your scenario there before running the agent

- Start the Agent:
  python agent.py 


The Agent will:
- request a DOM snapshot from the MCP server,
- call the LLM via LangChain/LangGraph,
- return a step plan and instruct the server to execute it.

## Test reporting & artifacts
On failure you get:
- Screenshots per failing step under reports/screenshots/
- Page HTML snapshot under reports/html/
- Execution logs and step plan under reports/logs/

These artifacts can be uploaded to CI for debugging.

## Security & privacy
- Avoid sending secrets to public LLMs. Use secret management and redact sensitive data when necessary.
- Consider running Ollama or other models on local/private infrastructure for sensitive data.
- The server/agent split reduces accidental credential leakage by centralizing execution and snapshot collection.

## Limitations & best practices
- Experimental: behavior may change; expect occasional nondeterministic LLM interpretations.
- Not token-efficient by default: current implementations prioritize capability and clarity over minimizing tokens.
- For critical tests, provide stable hints (data-test-id attributes) or mix LLM-driven tests with selector-based tests.
- Use explicit verification statements in scenarios to make intent clear and reduce ambiguity.

## Reuse as a library
selenium_mcp exposes a simple API/module that can be embedded into other applications to:
- Convert plain-language test steps into executable Selenium workflows.
- Use the DOM-parsing + LangChain/LangGraph orchestration pipeline programmatically.

See the examples/ directory for embedding patterns and example usage.

## CI / Continuous Integration
- Store LLM provider credentials in your CI secret store and configure the runner to access them securely.
- Ensure a browser or remote grid is available in the CI environment.
- Start the MCP server as part of the CI job (or point the Agent to a hosted server), then run the Agent to execute scenarios.
- Upload reports/ as CI artifacts for inspection.

## Contributing
- Fork and create feature branches (feat/your-feature).
- Add scenarios and tests that increase confidence without leaking secrets.
- If improving reliability (token-efficiency batching, local planning, or stable-hint workflows), document trade-offs and tests.

## License
Add a LICENSE file (e.g., MIT) if you want to open-source this repo.

## TODOs
- Improve token efficiency (batching, local planning).
- Add more example scenarios and templates.
- Add support for other providers (e.g., Anthropic, Cohere, etc.).
- Generate selenium code along with actions taken by agents to reuse instead of reusing the LLM.

## Contact
- Maintainer: abdulsalam146 (GitHub)
- Issues: open an issue in this repository for bugs, feature requests, or questions.
