"""
Mapeador (Pre-Sintetizador): resume los párrafos relevantes de cada sub-consulta,
preservando las citas a las fuentes originales.
100% local, sin descargas de modelos externos, optimizado para CPU.
"""
import re
import requests
import hashlib
import config
import cache

MAPEADOR_SYSTEM_PROMPT = """Eres un analista de investigación riguroso. 
AÑO ACTUAL DE REFERENCIA: 2026. 
REGLA DE ORO: NO inventes fechas, estados de construcción ni cifras. Si la fuente no menciona explícitamente si un proyecto está "en construcción", "planificado" o "cancelado", debes escribir textualmente: "Estado no especificado en las fuentes consultadas".

TAREA:
- Resume la información relevante para responder la sub-consulta.
- Conserva datos concretos: cifras, fechas, nombres, porcentajes.
- CITA cada afirmación usando la etiqueta [FUENTE_N] correspondiente.
- Si hay información contradictoria entre fuentes, menciónalo.
- Si no hay información útil, responde: "Sin información relevante."

Formato de salida: texto plano en el mismo idioma que la sub-consulta, con citas [FUENTE_N] integradas. NO uses markdown, NO agregues explicaciones meta.
"""


def _presupuestar(párrafos: list[dict], max_chars: int) -> list[dict]:
    """
    Recorta la lista de párrafos para no exceder el presupuesto de caracteres.
    Prioriza el orden de entrada (ya viene ordenado por BM25 descendente).
    Descarta párrafos individuales que por sí solos excedan el presupuesto.
    """
    if max_chars <= 0:
        return párrafos
    out, total = [], 0
    for p in párrafos:
        c = len(p.get("párrafo", ""))
        if c > max_chars:
            # Párrafo gigante: cortarlo, no descartarlo
            recorte = p["párrafo"][:max_chars]
            p = {**p, "párrafo": recorte + " […]"}
            c = len(p["párrafo"])
        if total + c > max_chars:
            break
        out.append(p)
        total += c
    return out


def _numerar_fuentes(párrafos: list[dict]) -> tuple[str, dict[int, str]]:
    url_a_num = {}
    num_a_url = {}
    contador = 1

    for p in párrafos:
        url = p["url"]
        if url not in url_a_num:
            url_a_num[url] = contador
            num_a_url[contador] = url
            contador += 1

    vistos = set()
    bloques_únicos = []
    for p in párrafos:
        url = p["url"]
        num = url_a_num[url]
        tag = f"[FUENTE_{num}]"
        if tag in vistos:
            continue
        vistos.add(tag)
        bloques_únicos.append(f"{tag} ({p['title']})\n{p['párrafo']}")

    return "\n\n---\n\n".join(bloques_únicos), num_a_url


def _hash_prompt(messages: list[dict]) -> str:
    raw = "||".join(f"{m['role']}:{m['content']}" for m in messages)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def mapear(sub_query: str, párrafos: list[dict]) -> dict:
    if not párrafos:
        return {"sub_query": sub_query, "resumen": "Sin información relevante.", "fuentes": {}}

    # Presupuesto de contexto ANTES de numerar (evita numerar fuentes que luego se recortan)
    párrafos = _presupuestar(párrafos, config.MAX_CONTEXT_CHARS_MAPPER)
    contexto_final, num_a_url = _numerar_fuentes(párrafos)

    user_msg = (
        f"Sub-consulta: {sub_query}\n\n"
        f"Fragmentos disponibles:\n{contexto_final}\n\n"
        f"Genera el resumen citando las fuentes."
    )

    messages = [
        {"role": "system", "content": MAPEADOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # Cache del LLM: mismo prompt + mismo modelo → mismo resumen
    cache_key = f"{config.LOCAL_LM_MODEL}|{_hash_prompt(messages)}"
    if config.CACHE_ENABLED:
        cached = cache.get("map", cache_key, ttl=cache.TTL_LLM)
        if cached is not None:
            print(f"[MAPEADOR] ⚡ cache hit LLM para '{sub_query[:40]}'")
            return {"sub_query": sub_query, "resumen": cached, "fuentes": num_a_url}

    payload = {
        "model": config.LOCAL_LM_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 800,
        "stream": False,
        "options": {"num_ctx": 2048},
    }

    try:
        r = requests.post(
            config.LOCAL_LM_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=300,
        )
        r.raise_for_status()
        resumen = r.json()["choices"][0]["message"]["content"].strip()
        resumen = re.sub(r"<think.*?</think>", "", resumen, flags=re.DOTALL | re.IGNORECASE).strip()
    except Exception as e:
        print(f"[MAPEADOR] Error para '{sub_query}': {e}")
        resumen = "Error al procesar la información."

    if config.CACHE_ENABLED and resumen and "Error" not in resumen[:20]:
        cache.set("map", cache_key, resumen)

    return {"sub_query": sub_query, "resumen": resumen, "fuentes": num_a_url}