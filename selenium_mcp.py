# selenium_mcp.py
import uuid
import atexit
import time
from mcp.server.fastmcp import FastMCP
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException

# Initialize MCP Server
mcp = FastMCP("WebAutomation")

# --- Driver Setup ---
options = webdriver.ChromeOptions()
#options.add_argument("--headless=new") # Remove this line if you want to watch the browser
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=options)

def cleanup():
    try:
        driver.quit()
    except:
        pass

atexit.register(cleanup)

# Global map to store Node IDs -> WebElement objects
node_map = {}

# --- Helper Functions ---

def wait_for_ready(timeout=10):
    """Waits for page to be fully loaded and jQuery (if present) to finish."""
    try:
        WebDriverWait(driver, timeout).until(lambda d: 
            d.execute_script("return document.readyState === 'complete'")
        )
        time.sleep(0.5) # Small buffer for rendering
    except:
        pass

def get_element_safe(node_id):
    """Retrieves element from map and checks for staleness."""
    el = node_map.get(node_id)
    if not el:
        raise ValueError(f"Node ID '{node_id}' not found. Page might have refreshed.")
    
    try:
        el.is_displayed() # Check attachment
        return el
    except StaleElementReferenceException:
        raise StaleElementReferenceException(f"Node ID '{node_id}' is stale. Please run get_page_data again.")

# =========================================================================
# 1. NAVIGATION ACTIONS
# =========================================================================

@mcp.tool()
def go_to_url(url: str):
    """Navigates the browser to a specific URL."""
    driver.get(url)
    wait_for_ready()
    return f"Navigated to {url}"

@mcp.tool()
def go_back():
    """Navigates back in browser history."""
    driver.back()
    wait_for_ready()
    return "Navigated back."

@mcp.tool()
def refresh_page():
    """Reloads the current page."""
    driver.refresh()
    wait_for_ready()
    return "Page refreshed."

# =========================================================================
# 2. TEXT INPUT ACTIONS
# =========================================================================

@mcp.tool()
def fill_input(node_id: str, text: str):
    """Types text into a standard input field (e.g., username, search)."""
    try:
        el = get_element_safe(node_id)
        el.clear()
        el.send_keys(text)
        return f"Entered text into input {node_id}."
    except Exception as e:
        return f"Error filling input: {str(e)}"

@mcp.tool()
def write_in_textarea(node_id: str, text: str):
    """Types text into a large text area (e.g., comment box, description)."""
    try:
        el = get_element_safe(node_id)
        el.clear()
        el.send_keys(text)
        return f"Entered text into textarea {node_id}."
    except Exception as e:
        return f"Error writing in textarea: {str(e)}"

@mcp.tool()
def clear_field(node_id: str):
    """Clears the content of an input or textarea."""
    try:
        get_element_safe(node_id).clear()
        return f"Cleared field {node_id}."
    except Exception as e:
        return f"Error clearing field: {str(e)}"

# =========================================================================
# 3. SELECTION ACTIONS (Clicks, Toggles)
# =========================================================================

@mcp.tool()
def click_element(node_id: str):
    """Clicks a button, link, or interactive element."""
    try:
        el = get_element_safe(node_id)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        el.click()
        wait_for_ready()
        return "Clicked element."
    except Exception as e:
        return f"Error clicking: {str(e)}"

@mcp.tool()
def hover_over_element(node_id: str):
    """Moves mouse over an element (useful for dropdown menus)."""
    try:
        el = get_element_safe(node_id)
        ActionChains(driver).move_to_element(el).perform()
        return "Hovered over element."
    except Exception as e:
        return f"Error hovering: {str(e)}"

@mcp.tool()
def toggle_checkbox(node_id: str, should_check: bool):
    """Checks or unchecks a checkbox based on the boolean value."""
    try:
        el = get_element_safe(node_id)
        if el.is_selected() != should_check:
            el.click()
        return f"Checkbox set to {should_check}."
    except Exception as e:
        return f"Error toggling checkbox: {str(e)}"

@mcp.tool()
def select_radio_button(node_id: str):
    """Selects a radio button option."""
    try:
        el = get_element_safe(node_id)
        if not el.is_selected():
            el.click()
        return "Radio button selected."
    except Exception as e:
        return f"Error selecting radio: {str(e)}"

# =========================================================================
# 4. DROPDOWN ACTIONS
# =========================================================================

@mcp.tool()
def select_dropdown_by_text(node_id: str, option_text: str):
    """Selects an option from a dropdown list by its visible text."""
    try:
        el = get_element_safe(node_id)
        select = Select(el)
        select.select_by_visible_text(option_text)
        wait_for_ready()
        return f"Selected '{option_text}' in dropdown."
    except Exception as e:
        return f"Error selecting dropdown text: {str(e)}"

@mcp.tool()
def select_dropdown_by_value(node_id: str, value: str):
    """Selects an option from a dropdown list by its 'value' attribute."""
    try:
        el = get_element_safe(node_id)
        select = Select(el)
        select.select_by_value(value)
        wait_for_ready()
        return f"Selected value '{value}' in dropdown."
    except Exception as e:
        return f"Error selecting dropdown value: {str(e)}"

# =========================================================================
# 5. LAYOUT & VISIBILITY ACTIONS
# =========================================================================

@mcp.tool()
def scroll_to_element(node_id: str):
    """Scrolls the page so the element is in the center of the view."""
    try:
        el = get_element_safe(node_id)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        return "Scrolled to element."
    except Exception as e:
        return f"Error scrolling: {str(e)}"

@mcp.tool()
def scroll_page(direction: str = "down"):
    """Scrolls the page up or down. Options: 'up' or 'down'."""
    try:
        val = 600 if direction == "down" else -600
        driver.execute_script(f"window.scrollBy(0, {val});")
        return f"Scrolled page {direction}."
    except Exception as e:
        return f"Error scrolling page: {str(e)}"

# =========================================================================
# 6. CONTEXT ACTIONS (Tabs, Frames)
# =========================================================================

@mcp.tool()
def switch_to_tab(index: int):
    """Switches focus to a specific browser tab by index (0, 1, 2...)."""
    try:
        handles = driver.window_handles
        if 0 <= index < len(handles):
            driver.switch_to.window(handles[index])
            return f"Switched to tab {index}."
        else:
            return f"Tab index {index} out of range."
    except Exception as e:
        return f"Error switching tab: {str(e)}"

@mcp.tool()
def switch_to_iframe(node_id: str):
    """Switches focus into a specific iframe using its Node ID."""
    try:
        el = get_element_safe(node_id)
        driver.switch_to.frame(el)
        return "Switched into iframe."
    except Exception as e:
        return f"Error switching to iframe: {str(e)}"

@mcp.tool()
def switch_to_main_content():
    """Switches focus back to the main page content (exits iframes)."""
    try:
        driver.switch_to.default_content()
        return "Switched back to main content."
    except Exception as e:
        return f"Error switching to main content: {str(e)}"

# =========================================================================
# 7. DATA EXTRACTION & PERCEPTION
# =========================================================================

@mcp.tool()
def get_page_data():
    """
    Scans the current page and returns a list of interactive elements.
    This updates the internal node_map. Call this after every navigation or action.
    """
    global node_map
    node_map = {}
    
    selectors = (
        "button, input, a, label, select, textarea, "
        "h1, h2, h3, h4, h5, h6, p, span, div, li, td, th, "
        "[role='button'], [role='link'], [role='option'], iframe"
    )
    
    elements = driver.find_elements(By.CSS_SELECTOR, selectors)
    nodes = []

    for el in elements:
        try:
            if not el.is_displayed():
                continue
            
            tag = el.tag_name.lower()
            # Generate ID: Prefer HTML ID, otherwise short UUID
            html_id = el.get_attribute("id")
            nid = html_id if html_id and len(html_id) < 50 else str(uuid.uuid4())[:8]
            
            node_map[nid] = el
            node_info = {"id": nid, "tag": tag}
            
            # Extract text
            text = el.text.strip()
            if text:
                node_info["text"] = text[:80] # Keep it short for tokens
            
            # Extract input attributes
            if tag == "input":
                node_info["type"] = el.get_attribute("type")
                node_info["placeholder"] = el.get_attribute("placeholder")
                node_info["name"] = el.get_attribute("name")
            elif tag == "iframe":
                 node_info["name"] = el.get_attribute("name") or el.get_attribute("title")

            nodes.append(node_info)
            
        except Exception:
            continue

    return {
        "url": driver.current_url,
        "title": driver.title,
        "interactive_elements": nodes
    }

@mcp.tool()
def get_element_text(node_id: str):
    """Reads and returns the exact text content of a specific element."""
    try:
        el = get_element_safe(node_id)
        return el.text
    except Exception as e:
        return f"Error reading text: {str(e)}"

@mcp.tool()
def get_current_url():
    """Returns the current URL of the browser."""
    return driver.current_url

if __name__ == "__main__":
    mcp.run(transport="sse")
