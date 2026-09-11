"""
Configuration settings for the LLM Web Agent.
"""
import os
import sys

def get_env(name, default):
    """Return an environment override, or the default when unset or blank."""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value

def get_int_env(name, default):
    """Return a positive integer environment override, or fall back clearly."""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        print(f"WARNING: {name} must be a positive integer; using default {default}.", file=sys.stderr)
        return default
    if parsed <= 0:
        print(f"WARNING: {name} must be a positive integer; using default {default}.", file=sys.stderr)
        return default
    return parsed

# --- Local LM API Endpoint ---
LOCAL_LM_URL = get_env("LOCAL_LM_URL", "http://127.0.0.1:11434/v1/chat/completions")
LOCAL_LM_MODEL = get_env("LOCAL_LM_MODEL", "qwen2.5:1.5b-instruct")

# --- SearxNG Instance ---
SEARXNG_URL = get_env("SEARXNG_URL", "http://127.0.0.1:8888")

# --- Multilingual Fallback Keywords ---
SEARCH_TRIGGER_KEYWORDS = [
    # English
    "latest", "current", "today", "recent", "news", "price of", "stock", "weather", "who won", "search for", "find info",
    # Spanish
    "últimas", "actual", "hoy", "reciente", "noticias", "precio de", "clima", "quién ganó", "buscar", "información",
    # French
    "dernières", "actuel", "aujourd'hui", "récent", "actualités", "prix de", "météo", "qui a gagné", "rechercher",
    # Portuguese
    "últimas", "atual", "hoje", "recente", "notícias", "preço de", "clima", "quem ganhou", "pesquisar",
    # Italian
    "ultime", "attuale", "oggi", "recente", "notizie", "prezzo di", "meteo", "chi ha vinto", "cercare",
    # German
    "neueste", "aktuell", "heute", "nachrichten", "preis von", "wetter", "wer hat gewonnen", "suchen"
]

IMAGE_SEARCH_TRIGGER_KEYWORDS = [
    "image of", "images of", "picture of", "pictures of", "show me image", "show me picture",
    "imagen de", "imágenes de", "foto de", "fotos de", "muéstrame imagen",
    "image de", "photo de", "imagem de", "foto de", "immagine di", "foto di", "bild von", "foto von"
]

SEARXNG_PARAMS = {
    "format": "json",
    "engines": "google,bing,duckduckgo",
    "safesearch": "0",
}

# --- Deep Research Settings ---
DEEP_RESEARCH_MAX_RESULTS_PER_QUERY = get_int_env("DEEP_RESEARCH_MAX_RESULTS_PER_QUERY", 8)
DEEP_RESEARCH_TOP_K_PARAGRAPHS = get_int_env("DEEP_RESEARCH_TOP_K_PARAGRAPHS", 8)

MAX_SEARCH_RESULTS = get_int_env("MAX_SEARCH_RESULTS", 10)
REQUEST_TIMEOUT = get_int_env("REQUEST_TIMEOUT", 15)

# --- Decision System Prompt (Improved for consistency) ---
DECISION_SYSTEM_PROMPT = """You are a decision router. Analyze the user's message and respond ONLY with a valid JSON object. No explanations, no extra text.

Available actions:
- {"action": "search", "query": "search query"} - For current events, news, prices, weather, recent information
- {"action": "image_search", "query": "search query"} - For finding images
- {"action": "system_info", "query": "info needed"} - For questions about current date/time, system hardware, OS, or your own AI model/version
- {"action": "respond", "answer": "your answer"} - For general knowledge questions you can answer directly

Examples:
User: "What is the weather today?"
Response: {"action": "search", "query": "weather today"}

User: "What date is it?"
Response: {"action": "system_info", "query": "current date"}

User: "Show me pictures of cats"
Response: {"action": "image_search", "query": "cats"}

User: "What is the capital of France?"
Response: {"action": "respond", "answer": "The capital of France is Paris."}

Respond ONLY with the JSON object:"""

DECISION_TEMPERATURE = 0.1
SYSTEM_PROMPT = """You are a helpful, precise, and critical assistant. 
CRITICAL RULE: When using web search results, you MUST verify that the information strictly satisfies ALL constraints in the user's question. 
If the provided search results do not contain a valid answer that meets all the user's constraints, state clearly: "The search did not yield a definitive answer that meets your specific criteria," instead of guessing or contradicting the prompt.
Base your answer strictly on the provided context, but apply logical filtering."""

# --- Conversation Settings ---
MAX_HISTORY_TURNS = 10  # Limit history to prevent context overflow

# --- Modelo dedicado para el planificador (barato y rápido) ---
# Fallback automático a LOCAL_LM_MODEL si no está disponible en Ollama.
PLANNER_MODEL = get_env("PLANNER_MODEL", "qwen2.5:0.5b-instruct")

# --- Presupuesto de contexto para prompts (caracteres) ---
MAX_CONTEXT_CHARS_MAPPER = get_int_env("MAX_CONTEXT_CHARS_MAPPER", 4000)
MAX_CONTEXT_CHARS_SYNTH = get_int_env("MAX_CONTEXT_CHARS_SYNTH", 12000)

# --- Cache ---
CACHE_ENABLED = get_env("CACHE_ENABLED", "1").strip() not in ("0", "false", "False", "")