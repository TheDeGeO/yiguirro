"""
Buscador y extractor: consulta SearxNG y descarga el texto limpio de cada URL.
Usa trafilatura para ignorar menús, anuncios y boilerplate.
"""
import requests
import time
import random
import re
from urllib.parse import urlencode, urljoin
import config
import cache

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL = True
except ImportError:
    import requests as curl_requests
    _HAS_CURL = False
    print("[BUSCADOR] WARNING: curl_cffi no instalado. Usando requests estándar.")

try:
    import trafilatura
except ImportError:
    trafilatura = None
    print("[BUSCADOR] WARNING: trafilatura no instalado. Instalalo con: pip install trafilatura")


def buscar_urls(query: str, max_results: int | None = None) -> list[dict]:
    max_results = max_results or config.MAX_SEARCH_RESULTS

    # Cache: mismo query + mismos parámetros → mismos resultados
    cache_key = f"{query}|{max_results}|{config.SEARXNG_URL}|{config.SEARXNG_PARAMS}"
    if config.CACHE_ENABLED:
        cached = cache.get("searx", cache_key, ttl=cache.TTL_SEARCH)
        if cached is not None:
            print(f"[BUSCADOR] ⚡ cache hit: '{query[:50]}'")
            return cached

    base_url = config.SEARXNG_URL if config.SEARXNG_URL.endswith("/") else config.SEARXNG_URL + "/"
    params = {"q": query, **config.SEARXNG_PARAMS}
    url = urljoin(base_url, "search") + "?" + urlencode(params)

    try:
        r = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[BUSCADOR] Error en SearxNG para '{query}': {e}")
        return []

    resultados = []
    for item in data.get("results", [])[:max_results]:
        resultados.append({
            "title": item.get("title", "Sin título"),
            "url": item.get("url", ""),
            "snippet": item.get("content", item.get("snippet", "")),
        })

    if config.CACHE_ENABLED:
        cache.set("searx", cache_key, resultados)

    return resultados


def extraer_texto(url: str) -> str:
    if not url:
        return ""

    # Cache de extracción: la misma URL raramente cambia en 24h
    if config.CACHE_ENABLED:
        cached = cache.get("extract", url, ttl=cache.TTL_EXTRACT)
        if cached is not None:
            print(f"[BUSCADOR] ⚡ cache hit extract: {url[:70]}")
            return cached

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.google.com/",
    }

    try:
        time.sleep(random.uniform(0.3, 0.8))
        if _HAS_CURL:
            r = curl_requests.get(
                url, headers=headers, timeout=config.REQUEST_TIMEOUT,
                impersonate="chrome120", verify=False,
            )
        else:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            r = curl_requests.get(
                url, headers=headers, timeout=config.REQUEST_TIMEOUT, verify=False,
            )
        r.raise_for_status()
    except Exception as e:
        if "SSL" in str(e) or "403" in str(e) or "429" in str(e) or "Could not resolve" in str(e):
            pass
        else:
            print(f"[BUSCADOR] Fallo inesperado en {url}: {e}")
        return ""

    if trafilatura is None:
        texto = r.text[:500] + "..."
    else:
        texto = trafilatura.extract(
            r.text,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=True,
        ) or ""

    if config.CACHE_ENABLED and texto:
        cache.set("extract", url, texto)

    return texto


def _sanitizar_query(query: str) -> str:
    query = re.sub(r'[¿?¡!]', '', query)
    query = re.sub(r'^(quiero saber|necesito saber|investigar sobre|información sobre)\s+', '', query, flags=re.IGNORECASE)
    query = query.strip()
    
    if len(query) > 250:
        palabras = query.split()
        truncada = ""
        for p in palabras:
            if len(truncada) + len(p) + 1 > 250:
                break
            truncada += (" " if truncada else "") + p
        query = truncada
    
    return query


def recolectar(queries: list[str], max_por_query: int | None = None) -> dict[str, dict]:
    max_por_query = max_por_query or config.MAX_SEARCH_RESULTS
    documentos = {}

    for q in queries:
        q_limpia = _sanitizar_query(q)
        if not q_limpia:
            print(f"[BUSCADOR] Query vacía tras sanitizar: '{q[:50]}...'")
            continue
        
        print(f"[BUSCADOR] Buscando: '{q_limpia}'")
        resultados = buscar_urls(q_limpia, max_por_query)
        
        if not resultados:
            print(f"[BUSCADOR]   ⚠️ 0 resultados para '{q_limpia[:50]}'")
            continue
            
        for res in resultados:
            url = res["url"]
            if not url or url in documentos:
                continue
            texto = extraer_texto(url)
            if not texto or len(texto.strip()) < 100:
                continue
            documentos[url] = {
                "title": res["title"],
                "texto": texto,
                "snippet": res["snippet"],
                "query_origen": q,
            }
        print(f"[BUSCADOR]   → {len(resultados)} resultados, {len(documentos)} documentos acumulados.")

    print(f"[BUSCADOR] Total de documentos útiles recolectados: {len(documentos)}")
    return documentos