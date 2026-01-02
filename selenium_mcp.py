import uuid
import atexit
import time
from mcp.server.fastmcp import FastMCP
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import StaleElementReferenceException

mcp = FastMCP("WebAutomation")

# Driver Setup
options = webdriver.ChromeOptions()
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=options)

def cleanup():
    try: driver.quit()
    except: pass
atexit.register(cleanup)

node_map = {}

def wait_for_ready(timeout=10):
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.execute_script("return document.readyState === 'complete'"))
        time.sleep(0.2)
    except: pass

def get_element_safe(node_id):
    el = node_map.get(node_id)
    if not el: raise ValueError(f"Node ID '{node_id}' not found.")
    try:
        el.is_displayed()
        return el
    except StaleElementReferenceException:
        raise StaleElementReferenceException(f"Node ID '{node_id}' is stale.")

# =========================================================================
# 1. DOM SIGNATURE (For Change Detection)
# =========================================================================

@mcp.tool()
def get_dom_hash():
    """
    Returns a hash of the current page content.
    Used by the agent to detect if the DOM has changed without a full scan.
    """
    # DJB2 Hash algorithm in JS for speed
    js_script = """
    var str = document.body.innerHTML;
    var hash = 5381;
    for (i = 0; i < str.length; i++) {
        char = str.charCodeAt(i);
        hash = ((hash << 5) + hash) + char; /* hash * 33 + c */
    }
    return hash >>> 0; // Convert to unsigned 32-bit integer
    """
    return driver.execute_script(js_script)

# =========================================================================
# 2. ACTIONS (All existing tools)
# =========================================================================

@mcp.tool()
def go_to_url(url: str):
    driver.get(url)
    wait_for_ready()
    return "Navigated."

@mcp.tool()
def fill_input(node_id: str, text: str):
    try:
        el = get_element_safe(node_id)
        el.clear()
        el.send_keys(text)
        return f"Filled {node_id}."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def write_in_textarea(node_id: str, text: str):
    try:
        el = get_element_safe(node_id)
        el.clear()
        el.send_keys(text)
        return f"Written to textarea {node_id}."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def clear_field(node_id: str):
    try:
        get_element_safe(node_id).clear()
        return f"Cleared {node_id}."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def click_element(node_id: str):
    try:
        el = get_element_safe(node_id)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        el.click()
        wait_for_ready()
        return "Clicked."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def hover_over_element(node_id: str):
    try:
        ActionChains(driver).move_to_element(get_element_safe(node_id)).perform()
        return "Hovered."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def toggle_checkbox(node_id: str, should_check: bool):
    try:
        el = get_element_safe(node_id)
        if el.is_selected() != should_check: el.click()
        return f"Checkbox set to {should_check}."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def select_radio_button(node_id: str):
    try:
        el = get_element_safe(node_id)
        if not el.is_selected(): el.click()
        return "Radio selected."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def select_dropdown_by_text(node_id: str, option_text: str):
    try:
        el = get_element_safe(node_id)
        Select(el).select_by_visible_text(option_text)
        wait_for_ready()
        return f"Selected '{option_text}'."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def select_dropdown_by_value(node_id: str, value: str):
    try:
        el = get_element_safe(node_id)
        Select(el).select_by_value(value)
        wait_for_ready()
        return f"Selected value '{value}'."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def scroll_to_element(node_id: str):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", get_element_safe(node_id))
        return "Scrolled to element."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def scroll_page(direction: str = "down"):
    val = 600 if direction == "down" else -600
    driver.execute_script(f"window.scrollBy(0, {val});")
    return "Scrolled page."

@mcp.tool()
def switch_to_tab(index: int):
    try:
        handles = driver.window_handles
        if 0 <= index < len(handles):
            driver.switch_to.window(handles[index])
            return f"Switched to tab {index}."
        return "Invalid tab index."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def switch_to_iframe(node_id: str):
    try:
        driver.switch_to.frame(get_element_safe(node_id))
        return "Switched to iframe."
    except Exception as e: return f"Error: {e}"

@mcp.tool()
def switch_to_main_content():
    try:
        driver.switch_to.default_content()
        return "Switched to main content."
    except Exception as e: return f"Error: {e}"

# =========================================================================
# 3. PERCEPTION
# =========================================================================

@mcp.tool()
def get_page_data():
    global node_map
    node_map = {}
    selectors = ("button, input, a, label, select, textarea, h1, h2, h3, h4, h5, h6, p, span, div, li, td, th, [role='button'], iframe")
    elements = driver.find_elements(By.CSS_SELECTOR, selectors)
    nodes = []

    for el in elements:
        try:
            if not el.is_displayed(): continue
            tag = el.tag_name.lower()
            html_id = el.get_attribute("id")
            nid = html_id if html_id and len(html_id) < 50 else str(uuid.uuid4())[:8]
            node_map[nid] = el
            node_info = {"id": nid, "tag": tag}
            text = el.text.strip()
            if text: node_info["text"] = text[:80]
            if tag == "input":
                node_info["type"] = el.get_attribute("type")
                node_info["placeholder"] = el.get_attribute("placeholder")
            nodes.append(node_info)
        except: continue

    return {
        "url": driver.current_url,
        "title": driver.title,
        "interactive_elements": nodes
    }

if __name__ == "__main__":
    mcp.run(transport="sse")
