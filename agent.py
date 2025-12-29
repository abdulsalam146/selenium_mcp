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
            CACHED_TOOLS = await mcp_client.get_tools()
            LLM_WITH_TOOLS = llm.bind_tools(CACHED_TOOLS)
            print(f"[SYSTEM] Connected. Found {len(CACHED_TOOLS)} tools.")
        except Exception as e:
            print(f"[FATAL ERROR] Failed to connect to MCP: {e}")
            raise e
            
    return CACHED_TOOLS, LLM_WITH_TOOLS

# --- NODES ---

async def reasoning_node(state: AgentState):
    """The LLM decides what to do next."""
    print("\n--- [REASONING] ---")
    _, brain = await initialize_resources()
    
    input_messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    
    response = await brain.ainvoke(input_messages)
    
    if response.content:
        # Clean up thought for console
        thought = response.content.replace('\n', ' ')
        print(f"Thought: {thought[:150]}...")
    
    return {"messages": [response]}

async def execution_node(state: AgentState):
    """
    Executes tools and AUTOMATICALLY scans the page if the action 
    likely changed the page structure.
    """
    print("\n--- [EXECUTION] ---")
    last_msg = state["messages"][-1]
    
    # 1. Check for Termination
    if last_msg.content and "TASK_COMPLETED_SUCCESSFULLY" in last_msg.content:
        print("[SYSTEM] Task marked complete.")
        return {"finished": True}

    # 2. Check for Tool Calls
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        tools, _ = await initialize_resources()
        tool_call = last_msg.tool_calls[0]
        
        tool_name = tool_call['name']
        print(f"Action: {tool_name}({tool_call['args']})")
        
        tool_obj = next((t for t in tools if t.name == tool_name), None)
        
        if not tool_obj:
            return {"messages": [HumanMessage(content=f"Error: Tool '{tool_name}' not found.")]}
        
        try:
            # --- EXECUTE THE ACTION ---
            result = await tool_obj.ainvoke(tool_call["args"])
            result_str = str(result) if isinstance(result, dict) else str(result)
            
            print(f"Result: {result_str[:80]}...")

            # --- SMART SCAN LOGIC ---
            # List of actions that definitely change the page structure or context
            structural_actions = {
                "go_to_url", "click_element", "select_dropdown_by_text", 
                "select_dropdown_by_value", "toggle_checkbox", "select_radio_button",
                "switch_to_tab", "switch_to_iframe", "switch_to_main_content",
                "go_back", "refresh_page"
            }

            # If the action was structural, automatically run get_page_data
            if tool_name in structural_actions:
                print(">> [AUTO-SCAN] Page structure likely changed. Scanning...")
                perception_tool = next((t for t in tools if t.name == "get_page_data"), None)
                
                if perception_tool:
                    try:
                        scan_result = await perception_tool.ainvoke({})
                        
                        # Format scan for LLM
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
                            # Append scan result directly to messages
                            return {"messages": [
                                HumanMessage(content=result_str), # Action result
                                HumanMessage(content=observation)  # Auto Scan result
                            ]}
                    except Exception as scan_err:
                        print(f"Auto-scan failed: {scan_err}")

            # If not structural, or scan failed, just return action result
            return {"messages": [HumanMessage(content=result_str)]}

        except Exception as e:
            error_msg = HumanMessage(content=f"Tool execution crashed: {str(e)}")
            print(f"Error: {str(e)}")
            # If we crash, we should probably scan again to see what state we are in
            perception_tool = next((t for t in tools if t.name == "get_page_data"), None)
            if perception_tool:
                try:
                    scan = await perception_tool.ainvoke({})
                    return {"messages": [error_msg, HumanMessage(content=f"Recovery Scan: {scan}")]}
                except: pass
            
            return {"messages": [error_msg]}
    
    print("[SYSTEM] No tool calls generated.")
    return {"messages": [HumanMessage(content="No action taken.")]}

# --- GRAPH CONSTRUCTION ---

builder = StateGraph(AgentState)

# We no longer need a separate Perception node. Execution handles it.
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
