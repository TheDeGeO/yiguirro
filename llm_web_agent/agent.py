import requests
import json
from urllib.parse import urlencode, urljoin
import sys
import re
import time
import threading
import platform
import datetime
import os

try:
    import config
except ImportError:
    print("ERROR: config.py not found. Please ensure it exists in the same directory.")
    sys.exit(1)

class SearchType:
    NONE = 0
    TEXT = 1
    IMAGE = 2

DEFAULT_DECISION_PROMPT = """You are a decision router. Respond ONLY with a JSON object:
- {"action": "search", "query": "..."} for web search
- {"action": "image_search", "query": "..."} for images
- {"action": "system_info", "query": "..."} for date/time/system info
- {"action": "respond", "answer": "..."} for direct answers
No other text."""

def get_decision_prompt():
    return getattr(config, 'DECISION_SYSTEM_PROMPT', None) or DEFAULT_DECISION_PROMPT

# --- Dynamic System Context Generator ---
def get_dynamic_system_context() -> str:
    """Generates a lightweight string with real-time system and agent info."""
    now = datetime.datetime.now()
    cpu_info = platform.processor() or "Unknown"
    
    return (
        f"--- SYSTEM CONTEXT ---\n"
        f"Current Date/Time: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')}).\n"
        f"OS: {platform.system()} {platform.release()} ({platform.machine()}).\n"
        f"CPU: {cpu_info} ({os.cpu_count()} logical cores).\n"
        f"AI Model: {config.LOCAL_LM_MODEL}.\n"
        f"Agent: LLM Web Agent v1.0.0 | Backend: Ollama+SearxNG.\n"
        f"----------------------\n"
    )

def get_search_type(prompt: str) -> SearchType:
    if not prompt: return SearchType.NONE
    prompt_lower = prompt.lower()
    
    for keyword in config.IMAGE_SEARCH_TRIGGER_KEYWORDS:
        if keyword in prompt_lower: return SearchType.IMAGE
    for keyword in config.SEARCH_TRIGGER_KEYWORDS:
        if keyword in prompt_lower: return SearchType.TEXT
    return SearchType.NONE

def perform_searxng_search(query: str, search_type: SearchType) -> tuple[str | None, list[str] | None]:
    text_context = None
    image_urls = None
    try:
        base_url = config.SEARXNG_URL
        if not base_url.endswith('/'): base_url += '/'
        
        query_params = {"q": query, **config.SEARXNG_PARAMS}
        if search_type == SearchType.IMAGE:
            query_params["categories"] = "images"
            
        search_url = urljoin(base_url, "search") + "?" + urlencode(query_params)
        response = requests.get(search_url, timeout=config.REQUEST_TIMEOUT)
        response.raise_for_status()
        results = response.json()
        
        if "results" in results and results["results"]:
            if search_type == SearchType.IMAGE:
                image_urls = []
                for result in results["results"][:config.MAX_SEARCH_RESULTS]:
                    img_src = result.get("img_src")
                    if img_src:
                        if img_src.startswith('/'): img_src = urljoin(config.SEARXNG_URL, img_src)
                        image_urls.append(img_src)
            else:
                text_context = "Web search results:\n"
                for i, result in enumerate(results["results"][:config.MAX_SEARCH_RESULTS]):
                    title = result.get("title", "No Title")
                    content = result.get("content", result.get("snippet", "No Content"))
                    url = result.get("url", "No URL")
                    content_cleaned = ' '.join(content.split()) if content else "N/A"
                    text_context += f"{i+1}. Title: {title}\n   Content: {content_cleaned}\n   URL: {url}\n"
    except Exception as e:
        print(f"\nERROR: SearxNG search failed: {e}")
    return text_context, image_urls

def remove_think_tags(text: str) -> str:
    if not text: return ""
    return re.sub(r'<think\s*>.*?</think\s*>', '', text, flags=re.DOTALL | re.IGNORECASE).strip()

def query_local_lm(prompt: str, context: str | None, history: list[dict], system_prompt_override: str | None = None) -> str | None:
    final_prompt = prompt
    if context:
        final_prompt = f"Based on the following context:\n{context}\n\nUser question: {prompt}"
        
    messages = []
    sys_prompt = system_prompt_override or config.SYSTEM_PROMPT
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    
    # Limit history to prevent context overflow
    max_turns = getattr(config, 'MAX_HISTORY_TURNS', 10)
    limited_history = history[-(max_turns * 2):] if len(history) > max_turns * 2 else history
    messages.extend(limited_history)
    messages.append({"role": "user", "content": final_prompt})
    
    payload = {
        "messages": messages, "temperature": 0.7, "max_tokens": 1000, "stream": False
    }
    if config.LOCAL_LM_MODEL:
        payload["model"] = config.LOCAL_LM_MODEL
        
    try:
        response = requests.post(config.LOCAL_LM_URL, headers={"Content-Type": "application/json"}, json=payload, timeout=300)
        response.raise_for_status()
        result = response.json()
        if "choices" in result and result["choices"]:
            message = result["choices"][0].get("message")
            if message and "content" in message:
                return remove_think_tags(message["content"].strip())
    except Exception as e:
        print(f"\nERROR: Local LM query failed: {e}")
    return None

def parse_decision(raw_response: str) -> dict | None:
    if not raw_response: return None
    
    # Clean up common LLM output issues
    cleaned = raw_response.strip()
    
    # Try to extract JSON from markdown code blocks
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
    if json_match:
        cleaned = json_match.group(1)
    
    # Try direct JSON parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and 'action' in data:
            action = data['action']
            if action in ('search', 'image_search', 'system_info') and 'query' in data:
                return {'action': action, 'query': str(data['query'])}
            elif action == 'respond' and 'answer' in data:
                return {'action': 'respond', 'answer': str(data['answer'])}
    except json.JSONDecodeError:
        pass
    
    # Relaxed regex fallback
    patterns = {
        'search': r'"action"\s*:\s*"search".*?"query"\s*:\s*"([^"]+)"',
        'image_search': r'"action"\s*:\s*"image_search".*?"query"\s*:\s*"([^"]+)"',
        'system_info': r'"action"\s*:\s*"system_info".*?"query"\s*:\s*"([^"]+)"',
        'respond': r'"action"\s*:\s*"respond".*?"answer"\s*:\s*"([^"]+)"'
    }
    for action, pattern in patterns.items():
        match = re.search(pattern, cleaned, re.DOTALL)
        if match:
            key = 'query' if action != 'respond' else 'answer'
            return {'action': action, key: match.group(1).strip()}
    return None

def decide_action(user_prompt: str, history: list[dict]) -> dict | None:
    """
    CRITICAL FIX: Do NOT pass history to decision maker.
    The decision maker should only see the current prompt to avoid contamination.
    """
    system_prompt = get_decision_prompt()
    
    # Pass empty history to decision maker - it only needs the current prompt
    raw_llm = query_local_lm(user_prompt, None, [], system_prompt_override=system_prompt)
    if not raw_llm: return None
    
    print(f"[DECISION] LLM raw: {raw_llm[:150]}...")
    decision = parse_decision(raw_llm)
    
    if decision is None:
        print("[DECISION] Parse failed, falling back to multilingual keyword detection.")
        search_type = get_search_type(user_prompt)
        if search_type == SearchType.TEXT: return {'action': 'search', 'query': user_prompt}
        elif search_type == SearchType.IMAGE: return {'action': 'image_search', 'query': user_prompt}
        else: return {'action': 'respond', 'answer': None}
    
    print(f"[DECISION] Parsed: {decision}")
    return decision

# --- Improved Waiting Animation ---
def animate_waiting(stop_event):
    """Clean waiting animation that properly clears the line."""
    animation = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0
    while not stop_event.is_set():
        print(f"\r{animation[idx % len(animation)]} Thinking... ", end="", flush=True)
        idx += 1
        time.sleep(0.1)
    # Clear the line completely
    print("\r" + " " * 30 + "\r", end="", flush=True)

# --- Command System ---
def handle_command(command: str, history: list[dict]) -> bool:
    """
    Handle slash commands. Returns True if command was handled, False otherwise.
    """
    cmd = command.lower().strip()
    
    if cmd in ['/bye', '/exit', '/quit']:
        print("\nGoodbye! 👋")
        sys.exit(0)
    
    elif cmd == '/clear':
        history.clear()
        print("\n✓ Conversation history cleared.")
        return True
    
    elif cmd == '/help':
        print("\n" + "="*40)
        print("Available Commands:")
        print("="*40)
        print("/help    - Show this help message")
        print("/clear   - Clear conversation history")
        print("/info    - Show system information")
        print("/model   - Show current AI model")
        print("/bye     - Exit the agent")
        print("="*40 + "\n")
        return True
    
    elif cmd == '/info':
        print("\n" + get_dynamic_system_context())
        return True
    
    elif cmd == '/model':
        print(f"\nCurrent model: {config.LOCAL_LM_MODEL}")
        return True
    
    return False

def print_welcome():
    """Print welcome message."""
    print("\n" + "="*50)
    print("🤖 LLM Web Agent - Local Search Assistant")
    print("="*50)
    print(f"Model: {config.LOCAL_LM_MODEL}")
    print("Type /help for available commands")
    print("="*50 + "\n")

def main():
    print_welcome()
    conversation_history = []

    while True:
        try:
            # Clean prompt with proper line handling
            print("You: ", end="", flush=True)
            user_prompt = input()
            
            if not user_prompt.strip():
                continue
            
            # Check for commands first
            if user_prompt.strip().startswith('/'):
                if handle_command(user_prompt.strip(), conversation_history):
                    continue
            
            # Decision step
            decision = decide_action(user_prompt, conversation_history)
            if decision is None:
                print("\nFailed to determine action.")
                continue

            action = decision['action']
            
            if action == 'search':
                query = decision['query']
                text_search_context, _ = perform_searxng_search(query, SearchType.TEXT)
                if text_search_context:
                    stop_indicator = threading.Event()
                    threading.Thread(target=animate_waiting, args=(stop_indicator,), daemon=True).start()
                    try:
                        llm_response = query_local_lm(user_prompt, text_search_context, conversation_history)
                    finally:
                        stop_indicator.set()
                        time.sleep(0.2)  # Ensure animation clears
                    
                    if llm_response:
                        print("\n" + "-"*50)
                        print(llm_response)
                        print("-"*50 + "\n")
                        conversation_history.append({"role": "user", "content": user_prompt})
                        conversation_history.append({"role": "assistant", "content": llm_response})
                    else:
                        print("\nFailed to get response from LLM.")
                else:
                    print("\nSearch returned no results.")

            elif action == 'image_search':
                query = decision['query']
                _, image_urls = perform_searxng_search(query, SearchType.IMAGE)
                if image_urls:
                    print("\n" + "-"*50)
                    print("Found Images:")
                    for i, url in enumerate(image_urls, 1):
                        print(f"{i}. {url}")
                    print("-"*50 + "\n")
                    conversation_history.append({"role": "user", "content": user_prompt})
                    conversation_history.append({"role": "assistant", "content": f"Displayed {len(image_urls)} images."})
                else:
                    print("\nNo images found.")

            elif action == 'system_info':
                print("[SYSTEM] Fetching dynamic context...")
                sys_context = get_dynamic_system_context()
                
                stop_indicator = threading.Event()
                threading.Thread(target=animate_waiting, args=(stop_indicator,), daemon=True).start()
                try:
                    llm_response = query_local_lm(user_prompt, sys_context, conversation_history)
                finally:
                    stop_indicator.set()
                    time.sleep(0.2)
                
                if llm_response:
                    print("\n" + "-"*50)
                    print(llm_response)
                    print("-"*50 + "\n")
                    conversation_history.append({"role": "user", "content": user_prompt})
                    conversation_history.append({"role": "assistant", "content": llm_response})
                else:
                    print("\nFailed to get response.")

            elif action == 'respond':
                answer = decision.get('answer')
                if answer:
                    print("\n" + "-"*50)
                    print(answer)
                    print("-"*50 + "\n")
                    conversation_history.append({"role": "user", "content": user_prompt})
                    conversation_history.append({"role": "assistant", "content": answer})
                else:
                    stop_indicator = threading.Event()
                    threading.Thread(target=animate_waiting, args=(stop_indicator,), daemon=True).start()
                    try:
                        llm_response = query_local_lm(user_prompt, None, conversation_history)
                    finally:
                        stop_indicator.set()
                        time.sleep(0.2)
                    
                    if llm_response:
                        print("\n" + "-"*50)
                        print(llm_response)
                        print("-"*50 + "\n")
                        conversation_history.append({"role": "user", "content": user_prompt})
                        conversation_history.append({"role": "assistant", "content": llm_response})
                    else:
                        print("\nFailed to get response.")

        except KeyboardInterrupt:
            print("\n\nExiting... (Ctrl+C)")
            break
        except EOFError:
            print("\n\nExiting... (EOF)")
            break

if __name__ == "__main__":
    if not config.LOCAL_LM_URL or not config.SEARXNG_URL:
        print("ERROR: URLs not set in config.py.")
        sys.exit(1)
    main()