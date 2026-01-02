import asyncio
import os
from typing import TypedDict, Annotated, List
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END, START
from langchain_ollama import ChatOllama
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from prompts import SYSTEM_PROMPT, USER_TASK

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-v3.1:671b-cloud")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.0, base_url=OLLAMA_BASE_URL)


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], lambda x, y: x + y]
    finished: bool


# MCP Client Setup
mcp_client = MultiServerMCPClient({
    "browser": {"transport": "sse", "url": "http://127.0.0.1:8000/sse"}
})

CACHED_TOOLS = None
LLM_WITH_TOOLS = None


async def initialize_resources():
    global CACHED_TOOLS, LLM_WITH_TOOLS
    if CACHED_TOOLS is None:
        print("[SYSTEM] Connecting to MCP...")
        try:
            CACHED_TOOLS = await mcp_client.get_tools()
            LLM_WITH_TOOLS = llm.bind_tools(CACHED_TOOLS)
            print(f"[SYSTEM] Connected. Tools: {len(CACHED_TOOLS)}")
        except Exception as e:
            print(f"[FATAL ERROR] {e}")
            raise e
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
    print("\n--- [REASONING] ---")
    _, brain = await initialize_resources()
    response = await brain.ainvoke([SystemMessage(content=SYSTEM_PROMPT)] + state["messages"])

    if response.content:
        print(f"Thought: {response.content[:100].replace(chr(10), ' ')}...")

    if hasattr(response, 'tool_calls') and response.tool_calls:
        print(f"Actions Planned: {len(response.tool_calls)}")

    return {"messages": [response]}


async def execution_node(state: AgentState):
    """
    Executes ALL tools provided by LLM in a batch.
    Optimized: Only checks for DOM changes if structural actions are present.
    """
    print("\n--- [EXECUTION] ---")
    last_msg = state["messages"][-1]

    if last_msg.content and "TASK_COMPLETED_SUCCESSFULLY" in last_msg.content:
        return {"finished": True}

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        tools, _ = await initialize_resources()

        # 1. Analyze the batch to decide if we need to check for changes
        # If the batch is just filling inputs/scaling, skip the expensive hash check.
        batch_contains_structural_change = any(
            tool_call['name'] in STRUCTURAL_ACTIONS
            for tool_call in last_msg.tool_calls
        )

        # 2. Get current DOM state (Only if we suspect a change might happen)
        initial_hash = None
        hash_tool = next((t for t in tools if t.name == "get_dom_hash"), None)

        if batch_contains_structural_change and hash_tool:
            initial_hash = await hash_tool.ainvoke({})

        # 3. Execute ALL tools in the batch
        results = []
        for tool_call in last_msg.tool_calls:
            tool_name = tool_call['name']
            tool_obj = next((t for t in tools if t.name == tool_name), None)

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
                scan_tool = next((t for t in tools if t.name == "get_page_data"), None)
                if scan_tool:
                    try:
                        scan_result = await scan_tool.ainvoke({})
                        if isinstance(scan_result, dict):
                            elements = scan_result.get('interactive_elements', [])
                            obs = (
                                    f"CURRENT PAGE STATE:\n"
                                    f"URL: {scan_result.get('url')}\n"
                                    f"Title: {scan_result.get('title')}\n"
                                    f"Elements (Top 20):\n" + "\n".join(
                                [f"{e['id']} ({e['tag']})" for e in elements[:20]])
                            )
                            messages_to_append.append(HumanMessage(content=obs))
                    except Exception as e:
                        messages_to_append.append(HumanMessage(content=f"Scan failed: {e}"))
        else:
            print("  >> [OPTIMIZATION] Skipped scan (No structural actions detected).")

        return {"messages": messages_to_append}

    return {"messages": [HumanMessage(content="No actions taken.")]}


# --- GRAPH ---

builder = StateGraph(AgentState)
builder.add_node("reason", reasoning_node)
builder.add_node("execute", execution_node)

builder.add_edge(START, "reason")


def route(state: AgentState):
    if state.get("finished"): return END
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls: return "execute"
    return END


builder.add_conditional_edges("reason", route)
builder.add_edge("execute", "reason")

app = builder.compile()


async def run_agent(goal: str):
    print(f"*** STARTING AGENT (Ollama: {OLLAMA_MODEL}) ***\nGoal: {goal}\n")
    try:
        await initialize_resources()
        state = {"messages": [HumanMessage(content=goal)], "finished": False}
        async for _ in app.astream(state): pass
        print("\n*** COMPLETE ***")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(run_agent(USER_TASK))
