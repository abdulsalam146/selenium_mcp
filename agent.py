# agent.py
import asyncio
import os
from typing import TypedDict, Annotated, List
from dotenv import load_dotenv

# LangGraph & LangChain Imports
from langgraph.graph import StateGraph, END, START
from langchain_ollama import ChatOllama
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

# Import prompts
from prompts import SYSTEM_PROMPT, USER_TASK

# 1. Configuration
load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-v3.1:671b-cloud")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

llm = ChatOllama(
    model=OLLAMA_MODEL,
    temperature=0.0,
    base_url=OLLAMA_BASE_URL
)


# 2. State Definition
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], lambda x, y: x + y]
    finished: bool


# 3. MCP Client Setup (Global)
mcp_client = MultiServerMCPClient({
    "browser": {
        "transport": "sse",
        "url": "http://127.0.0.1:8000/sse"
    }
})

# --- GLOBAL ASSETS ---
CACHED_TOOLS = None
LLM_WITH_TOOLS = None


async def initialize_resources():
    global CACHED_TOOLS, LLM_WITH_TOOLS

    if CACHED_TOOLS is None:
        print("[SYSTEM] Connecting to MCP Server...")
        try:
            # Get ALL tools from MCP
            CACHED_TOOLS = await mcp_client.get_tools()

            # FILTER OUT SYSTEM TOOLS from the LLM's view
            # This prevents the LLM from calling 'get_page_data' or 'get_dom_hash' manually
            HIDDEN_TOOLS = {"get_page_data", "get_dom_hash"}
            visible_tools = [t for t in CACHED_TOOLS if t.name not in HIDDEN_TOOLS]

            # Bind only the visible tools to the LLM
            LLM_WITH_TOOLS = llm.bind_tools(visible_tools)

            print(f"[SYSTEM] Connected. Total Tools: {len(CACHED_TOOLS)}. Visible to LLM: {len(visible_tools)}")
        except Exception as e:
            print(f"[FATAL ERROR] Failed to connect to MCP: {e}")
            raise e

    # Return the FULL list of tools (for the execution_node to use) and the LLM brain
    return CACHED_TOOLS, LLM_WITH_TOOLS


# --- CONFIGURATION: OPTIMIZED SCANNING ---

# Actions that DEFINITELY change the page (URL, Navigation, Context Switch)
STRUCTURAL_ACTIONS = {
    "go_to_url", "click_element", "select_dropdown_by_text",
    "select_dropdown_by_value", "toggle_checkbox", "select_radio_button",
    "switch_to_tab", "switch_to_iframe", "switch_to_main_content",
    "refresh_page", "go_back"
}


# --- NODES ---

async def reasoning_node(state: AgentState):
    """The LLM decides what to do next."""
    print("\n--- [REASONING] ---")
    _, brain = await initialize_resources()

    # Pass the full message history to the LLM
    response = await brain.ainvoke(state["messages"])

    if response.content:
        # Clean up thought for console
        thought = response.content.replace('\n', ' ')
        print(f"Thought: {thought[:150]}...")

    if hasattr(response, 'tool_calls') and response.tool_calls:
        print(f"Actions Planned: {len(response.tool_calls)}")

    # Standard return: dictionary matching AgentState keys
    return {"messages": [response]}


async def execution_node(state: AgentState):
    """
    Executes ALL tools provided by LLM in a batch.
    Optimized: Only checks for DOM changes if structural actions are present.
    """
    print("\n--- [EXECUTION] ---")
    last_msg = state["messages"][-1]

    # 1. Check for Termination
    if last_msg.content and "TASK_COMPLETED_SUCCESSFULLY" in last_msg.content:
        print("[SYSTEM] Task marked complete.")
        return {"finished": True}

    # 2. Check for Tool Calls
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        # Get FULL tool list (execution node needs access to hidden tools like get_dom_hash)
        all_tools, _ = await initialize_resources()

        # 1. Analyze the batch to decide if we need to check for changes
        # We only scan if the batch includes actions that *could* change the structure
        batch_contains_structural_change = any(
            tool_call['name'] in STRUCTURAL_ACTIONS
            for tool_call in last_msg.tool_calls
        )

        # 2. Get current DOM state (Only if we suspect a change might happen)
        initial_hash = None
        hash_tool = next((t for t in all_tools if t.name == "get_dom_hash"), None)

        if batch_contains_structural_change and hash_tool:
            initial_hash = await hash_tool.ainvoke({})

        # 3. Execute ALL tools in the batch
        results = []
        for tool_call in last_msg.tool_calls:
            tool_name = tool_call['name']
            tool_obj = next((t for t in all_tools if t.name == tool_name), None)

            if not tool_obj:
                results.append(f"Error: Tool '{tool_name}' not found.")
                continue

            try:
                print(f"  > Executing: {tool_name}")
                res = await tool_obj.ainvoke(tool_call["args"])
                results.append(str(res))
            except Exception as e:
                results.append(f"Error in {tool_name}: {str(e)}")
                # If an action fails, stop the batch to be safe
                break

        # 4. Check if DOM changed (Only if we started with a structural action)
        messages_to_append = [HumanMessage(content=" | ".join(results))]

        if batch_contains_structural_change and hash_tool:
            final_hash = await hash_tool.ainvoke({})
            if initial_hash != final_hash:
                print("  >> [DETECTED] Page content changed. Triggering Scan...")
                perception_tool = next((t for t in all_tools if t.name == "get_page_data"), None)

                if perception_tool:
                    try:
                        scan_result = await perception_tool.ainvoke({})

                        if isinstance(scan_result, dict):
                            url = scan_result.get('url', 'Unknown')
                            title = scan_result.get('title', 'Unknown')
                            elements = scan_result.get('interactive_elements', [])

                            element_summary = "\n".join([
                                f"ID: {e['id']} | Tag: {e['tag']} | Text: {e.get('text', '')}"
                                for e in elements[:20]
                            ])

                            observation = (
                                f"CURRENT PAGE STATE:\n"
                                f"URL: {url}\n"
                                f"Title: {title}\n"
                                f"Elements (Top 20):\n{element_summary}\n"
                                f"Total Elements: {len(elements)}"
                            )
                            messages_to_append.append(HumanMessage(content=observation))
                    except Exception as scan_err:
                        messages_to_append.append(HumanMessage(content=f"Scan failed: {scan_err}"))
        else:
            print("  >> [OPTIMIZATION] Skipped scan (No structural actions detected).")

        return {"messages": messages_to_append}

    print("[SYSTEM] No tool calls generated.")
    return {"messages": [HumanMessage(content="No action taken.")]}


# --- GRAPH CONSTRUCTION ---

builder = StateGraph(AgentState)

builder.add_node("reason", reasoning_node)
builder.add_node("execute", execution_node)

builder.add_edge(START, "reason")


def route_after_reasoning(state: AgentState):
    """Decides whether to execute a tool or finish."""
    last_msg = state["messages"][-1]

    # If finished flag was set
    if state.get("finished"):
        return END

    # If there are tool calls, go to execution
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "execute"

    # If no tool calls but not finished, loop back to reason (e.g. LLM is just thinking)
    # This prevents infinite loops if LLM hallucinates text without tools
    return END


builder.add_conditional_edges("reason", route_after_reasoning)

# After execution, we always go back to reasoning.
# The page scan was handled (or skipped) inside execution_node.
builder.add_edge("execute", "reason")

app = builder.compile()


# --- RUNNER ---

async def run_agent(goal: str):
    print(f"*** STARTING AGENT (Ollama: {OLLAMA_MODEL}) ***\nGoal: {goal}\n")

    # Initial State
    initial_state = {
        "messages": [HumanMessage(content=goal)],
        "finished": False
    }

    max_turns = 30
    turn_count = 0

    try:
        await initialize_resources()

        async for event in app.astream(initial_state):
            turn_count += 1
            if turn_count > max_turns:
                print("\n[SYSTEM] Max turns reached. Stopping.")
                break

        print("\n*** PROCESS COMPLETE ***")

    except ConnectionRefusedError:
        print("\n[FATAL ERROR] Could not connect to MCP Server.")
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")


if __name__ == "__main__":
    try:
        asyncio.run(run_agent(USER_TASK))
    except KeyboardInterrupt:
        print("Stopped by user.")
