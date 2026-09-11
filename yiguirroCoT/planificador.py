"""
Planificador: descompone una pregunta compleja en sub-consultas de búsqueda.
Usa el LLM local con un prompt estricto para devolver JSON válido.
"""
import json
import re
import requests
import config
import hashlib 
import cache


PLANIFICADOR_SYSTEM_PROMPT = """Descompón la pregunta en 3 sub-consultas de búsqueda web.
REGLAS:
1. Cada sub-consulta debe mencionar explícitamente el tema, el lugar y el año (si aparecen en la pregunta).
2. Devuelve SOLO: {"queries": ["...", "...", "..."]}

Ejemplo:
P: "Compara el PIB de Costa Rica y Panamá en 2024"
R: {"queries": ["PIB Costa Rica 2024 datos oficiales", "PIB Panamá 2024 datos oficiales", "comparación PIB Costa Rica Panamá 2024"]}
"""

STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "de", "del", "en", "y", "o",
    "que", "cual", "cuales", "como", "para", "por", "con", "sin", "sobre",
    "quiero", "necesito", "saber", "investigar", "comparar", "analizar",
    "diferencia", "diferencias", "impacto", "efecto", "causa", "estado",
}

LUGARES_COMUNES = {  # extiende según tu dominio típico
    "costa", "rica", "panamá", "panama", "nicaragua", "honduras", "guatemala",
    "méxico", "mexico", "colombia", "chile", "argentina", "perú", "peru",
    "españa", "usa", "estados", "unidos", "china", "europa", "españa",
}

_STOPWORDS_DEDUP = {
    # Español
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "del", "al", "en", "y", "o", "u", "que", "cual", "cuales",
    "para", "por", "con", "sin", "sobre", "entre", "hacia",
    "es", "son", "ser", "esta", "este", "esto", "estos", "estas",
    "su", "sus", "lo", "le", "les", "se", "me", "te", "nos",
    # Inglés (por si el modelo responde en otro idioma)
    "the", "of", "and", "or", "to", "for", "with", "in", "on", "at",
    "is", "are", "was", "were", "be", "been", "a", "an",
    # Genéricos de investigación que no distinguen queries
    "datos", "informacion", "información", "estadisticas", "estadísticas",
    "actual", "actuales", "reciente", "recientes", "ultimas", "últimas",
    "sobre", "acerca", "respecto", "comparacion", "comparación",
}


def extraer_anclas(pregunta: str) -> dict:
    """
    Anclas = contexto obligatorio que NINGUNA sub-consulta puede perder.
    Heurística sin dependencias externas.
    """
    palabras = pregunta.split()
    propias = [
        p.strip(".,;:!?¿¡()[]\"'") for i, p in enumerate(palabras)
        if i > 0 and p and p[0].isupper()
        and p.lower().strip(".,;:!?¿¡") not in STOPWORDS
        and len(p) > 2
    ]
    anios = re.findall(r"\b(?:19|20)\d{2}\b", pregunta)
    citas = re.findall(r'[""«"\']([^""»"\']{2,40})[""»"\']', pregunta)
    lugares = [p for p in palabras if p.lower().strip(".,;:!?") in LUGARES_COMUNES]

    return {
        "propias": list(dict.fromkeys(propias))[:6],
        "anios": list(dict.fromkeys(anios))[:3],
        "citas": list(dict.fromkeys(citas))[:3],
        "lugares": list(dict.fromkeys(lugares))[:3],
    }

def _tokenizar_simple(texto: str) -> list[str]:
    """
    Tokenización rápida para deduplicar queries.
    - Minúsculas
    - Solo tokens alfanuméricos de 2+ caracteres
    - Ignora stopwords muy comunes (evita que 'de la 2024' colapse dos queries distintas)
    """
    tokens = re.findall(r"\b\w{2,}\b", texto.lower())
    return [t for t in tokens if t not in _STOPWORDS_DEDUP]


def _reforzar_query(query: str, anclas: dict) -> str:
    """
    Añade al final de la query las anclas que falten.
    Comparación por tokens (no substrings) para evitar 'costa rica rica'.
    """
    tokens_query = set(re.findall(r"\b\w{2,}\b", query.lower()))

    refuerzos = []
    # Nombres propios + lugares
    for p in list(anclas["propias"]) + list(anclas["lugares"]):
        p_tokens = set(re.findall(r"\b\w{2,}\b", p.lower()))
        # Añadir solo si NINGÚN token del ancla ya está en la query
        if p_tokens and not (p_tokens & tokens_query):
            refuerzos.append(p)
    # Años (match exacto)
    for a in anclas["anios"]:
        if a not in query:
            refuerzos.append(a)

    # Dedup preservando orden + limitar a 3
    vistos, limpios = set(), []
    for r in refuerzos:
        k = r.lower()
        if k not in vistos:
            vistos.add(k)
            limpios.append(r)

    return f"{query} {' '.join(limpios[:3])}" if limpios else query


def planificar(pregunta: str) -> list[str]:
    """
    Genera una lista de sub-consultas a partir de la pregunta original.
    - Cache en disco: misma pregunta + mismo modelo → mismo plan.
    - Modelo dedicado (PLANNER_MODEL): barato y rápido para liberar CPU/RAM.
    - Anclas inyectadas en el user_msg Y reforzadas post-LLM (cinturón y tirantes).
    """
    # 1) Pre-procesamiento
    anclas = extraer_anclas(pregunta)
    pregunta_limpia = _truncar_inteligente(pregunta, max_palabras=150)

    # 2) User message CON las anclas explícitas (antes se calculaba y se descartaba)
    user_msg = (
        f"PREGUNTA: {pregunta_limpia}\n\n"
        f"ENTIDADES OBLIGATORIAS que deben aparecer en cada sub-consulta:\n"
        f"- Nombres propios: {', '.join(anclas['propias']) or '(ninguno)'}\n"
        f"- Lugares: {', '.join(anclas['lugares']) or '(ninguno)'}\n"
        f"- Años: {', '.join(anclas['anios']) or '(ninguno)'}\n"
    )

    messages = [
        {"role": "system", "content": PLANIFICADOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},   # ← ahora sí usa user_msg
    ]

    # 3) Cache: misma pregunta + mismo modelo → mismo plan
    #    Hash sobre (modelo, system, user) para invalidar si cambia el prompt o el modelo
    h = hashlib.sha1(
        f"{config.PLANNER_MODEL}|{PLANIFICADOR_SYSTEM_PROMPT}|{user_msg}".encode("utf-8")
    ).hexdigest()

    if config.CACHE_ENABLED:
        cached = cache.get("plan", h, ttl=cache.TTL_LLM)
        if cached:
            print(f"[PLANIFICADOR] ⚡ cache hit: {cached}")
            # Aun con cache aplicamos refuerzo por si las anclas cambiaron de heurística
            return [_reforzar_query(q, anclas) for q in cached][:5]

    # 4) Llamada al LLM con modelo pequeño dedicado
    payload = {
        "model": config.PLANNER_MODEL,        # ← 0.5B en vez de 1.5B
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 400,
        "stream": False,
        "format": "json",                      # gramática JSON forzada
        "options": {"num_ctx": 2048},          # limita KV cache en RAM baja
    }

    try:
        response = requests.post(
            config.LOCAL_LM_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=180,                       # 0.5B no necesita 240s
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.Timeout:
        print("[PLANIFICADOR] ⏱️ Timeout tras 180s. Usando fallback de frases clave.")
        return [_reforzar_query(q, anclas)
                for q in _fallback_por_frases(pregunta)][:5]
    except Exception as e:
        print(f"[PLANIFICADOR] Error al consultar LLM: {e}")
        return [_reforzar_query(q, anclas)
                for q in _fallback_por_frases(pregunta)][:5]

    # 5) Limpieza de tags <think> (regex corregido)
    raw = re.sub(r"<think.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()

        # 6) Extracción del JSON
    queries = _extraer_queries(raw)

    # 6.b) Si el planner pequeño falló, reintentar con el modelo grande
    if not queries and config.PLANNER_MODEL != config.LOCAL_LM_MODEL:
        print(f"[PLANIFICADOR] ↻ Reintentando con {config.LOCAL_LM_MODEL}...")
        payload_retry = {**payload, "model": config.LOCAL_LM_MODEL}
        try:
            r2 = requests.post(
                config.LOCAL_LM_URL,
                headers={"Content-Type": "application/json"},
                json=payload_retry,
                timeout=240,
            )
            r2.raise_for_status()
            raw2 = r2.json()["choices"][0]["message"]["content"].strip()
            queries = _extraer_queries(raw2)
        except Exception as e:
            print(f"[PLANIFICADOR] Reintento falló: {e}")

    # 6.c) Último recurso: heurística de frases
    if not queries:
        print("[PLANIFICADOR] Usando fallback de frases clave.")
        queries = _fallback_por_frases(pregunta)

    # 7) Reforzar con anclas faltantes
    queries = [_reforzar_query(q, anclas) for q in queries]

    # 8) Deduplicar por conjunto de tokens
    vistas, únicas = set(), []
    for q in queries:
        clave = frozenset(_tokenizar_simple(q))
        if clave and clave not in vistas:
            vistas.add(clave)
            únicas.append(q)
    finales = únicas[:5]

    # 9) Guardar en cache SOLO el resultado limpio y final
    if config.CACHE_ENABLED and finales:
        cache.set("plan", h, finales)

    print(f"[PLANIFICADOR] Sub-consultas generadas: {finales}")
    return finales

def _truncar_inteligente(texto: str, max_palabras: int = 400) -> str:
    """
    Trunca un texto largo conservando oraciones completas.
    400 palabras son ~500-600 tokens, perfectamente manejables por modelos de 1.5B.
    """
    palabras = texto.split()
    if len(palabras) <= max_palabras:
        return texto
    
    # Tomar las primeras max_palabras y cerrar en el último punto para no cortar a la mitad
    truncado = " ".join(palabras[:max_palabras])
    ultimo_punto = truncado.rfind(".")
    if ultimo_punto > 0:
        truncado = truncado[:ultimo_punto + 1]
    
    return truncado + " (El resto del prompt fue resumido por longitud, enfócate en estos puntos clave)."


_PREFIJOS_CONVERSACIONALES = re.compile(
    r'^\s*(?:quiero|necesito|me\s+gustar[íi]a|deseo|quisiera|'
    r'he\s+o[íi]do\s+que|he\s+escuchado\s+que|se\s+dice\s+que|'
    r'es\s+posible\s+que|creo\s+que|pienso\s+que|'
    r'investigar?\s+sobre|buscar\s+informaci[óo]n\s+sobre|'
    r'dame\s+informaci[óo]n\s+sobre|saber\s+si|saber\s+por\s+qu[ée]|'
    r'saber\s+a\s+cu[áa]les|saber\s+donde|saber\s+cu[áa]nt[oa]s?)\s+',
    re.IGNORECASE,
)


def _fallback_por_frases(pregunta: str) -> list[str]:
    """
    Fallback cuando el LLM falla o no parsea JSON.
    Extrae fragmentos sustantivos (no oraciones conversacionales) priorizando
    densidad de contenido (tokens no-stopword).
    """
    # 1) Trocear por puntuación fuerte y por conectores discursivos
    trozos = re.split(
        r'(?<=[.!?])\s+|\s*,\s*|\s+(?:y|o|pero|adem[áa]s|tambi[ée]n)\s+',
        pregunta,
    )

    # 2) Limpiar y puntuar por densidad
    candidatos = []
    for t in trozos:
        t = t.strip().strip(".,;:!?¿¡\"'()[]")
        if not t:
            continue
        # Quitar prefijos conversacionales de forma iterativa
        for _ in range(3):
            nuevo = _PREFIJOS_CONVERSACIONALES.sub("", t).strip()
            if nuevo == t:
                break
            t = nuevo
        if len(t) < 15:
            continue
        palabras = re.findall(r"\b\w{3,}\b", t.lower())
        contenido = [p for p in palabras if p not in _STOPWORDS_DEDUP]
        if len(contenido) < 3:
            continue
        candidatos.append((len(contenido), t))

    # 3) Ordenar por densidad y recortar longitud
    candidatos.sort(key=lambda x: -x[0])
    vistos, queries = set(), []
    for _, texto in candidatos:
        if len(texto) > 180:
            corte = texto[:180]
            esp = corte.rfind(" ")
            texto = corte[:esp] if esp > 100 else corte
        clave = frozenset(_tokenizar_simple(texto))
        if clave and clave not in vistos:
            vistos.add(clave)
            queries.append(texto)
        if len(queries) >= 5:
            break

    return queries or [pregunta[:200]]


def _extraer_de_data(data) -> list[str]:
    """Extrae queries de una estructura JSON ya parseada (dict, list, str)."""
    if isinstance(data, list):
        strs = [str(x).strip() for x in data if isinstance(x, str) and str(x).strip()]
        if strs:
            return strs
    if isinstance(data, dict):
        # Claves candidatas (singular/plural, varios idiomas)
        for key in ("queries", "Queries", "QUERIES", "query", "subqueries",
                    "sub_queries", "subconsultas", "preguntas", "búsquedas", "busquedas"):
            if key in data:
                r = _extraer_de_data(data[key])
                if r:
                    return r
        # Fallback: primer valor que sea lista de strings
        for v in data.values():
            r = _extraer_de_data(v)
            if r:
                return r
    if isinstance(data, str):
        partes = re.split(r"[\n,;]", data)
        return [p.strip().strip('"\'') for p in partes if 5 < len(p.strip()) < 200]
    return []


def _extraer_queries(raw: str) -> list[str]:
    """
    Extrae la lista de queries de la respuesta del LLM.
    Muy defensivo: JSON puro, JSON embebido, arrays sueltos, regex.
    Si todo falla, imprime el raw para diagnóstico.
    """
    if not raw:
        return []
    texto = raw.strip()

    # 1) Quitar bloques ```json ... ``` (o ``` ... ```)
    md = re.search(r"```(?:json)?\s*(.+?)\s*```", texto, re.DOTALL | re.IGNORECASE)
    if md:
        texto = md.group(1).strip()

    # 2) Intento JSON directo
    try:
        data = json.loads(texto)
        r = _extraer_de_data(data)
        if r:
            return r
    except json.JSONDecodeError:
        pass

    # 3) Buscar primer bloque {...} o [...] y parsearlo por separado
    for ini, fin in (("{", "}"), ("[", "]")):
        i, j = texto.find(ini), texto.rfind(fin)
        if i >= 0 and j > i:
            try:
                data = json.loads(texto[i:j + 1])
                r = _extraer_de_data(data)
                if r:
                    return r
            except json.JSONDecodeError:
                continue

    # 4) Regex sobre "queries": [...] (por si el objeto está roto pero el array no)
    m = re.search(r'"?quer(?:y|ies)"?\s*:\s*\[(.*?)\]', texto, re.DOTALL | re.IGNORECASE)
    if m:
        items = re.findall(r'"([^"]{5,200})"', m.group(1))
        if items:
            return [q.strip() for q in items if q.strip()]

    # 5) Último recurso: cualquier string entre comillas de 8-200 chars
    items = re.findall(r'"([^"]{8,200})"', texto)
    items = [q.strip() for q in items if q.strip() and q.lower() not in ("queries", "json")]
    if items:
        print(f"[PLANIFICADOR] ⚠️  JSON no estructurado, usando strings sueltos.")
        return items[:5]

    # 6) Todo falló: mostrar el raw para que puedas diagnosticar
    print(f"[PLANIFICADOR] ❌ No se pudo parsear. Raw (300 chars): {texto[:300]!r}")
    return []