"""
Filtrador: usa BM25 para seleccionar los párrafos más relevantes
de cada documento en relación con una sub-consulta.
"""
import re

try:
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except ImportError:
    _HAS_BM25 = False
    print("[FILTRADOR] WARNING: rank_bm25 no instalado. Usando fallback simple. Instala con: pip install rank_bm25")


def _tokenizar(texto: str) -> list[str]:
    """Tokenización simple: minúsculas, solo palabras alfanuméricas de 2+ caracteres."""
    return re.findall(r"\b\w{2,}\b", texto.lower())


def _dividir_en_párrafos(texto: str) -> list[str]:
    """Divide el texto en párrafos por saltos de línea dobles o simples."""
    # Primero por dobles saltos
    partes = re.split(r"\n\s*\n", texto)
    # Si quedan bloques muy grandes, dividir por saltos simples
    párrafos = []
    for p in partes:
        p = p.strip()
        if not p:
            continue
        if len(p) > 1500:
            sub = p.split("\n")
            párrafos.extend([s.strip() for s in sub if len(s.strip()) > 50])
        else:
            párrafos.append(p)
    return párrafos


def _rank_fallback(query: str, párrafos: list[str], top_k: int) -> list[tuple[int, float]]:
    """Fallback simple: cuenta coincidencias de palabras de la query en cada párrafo."""
    tokens_q = set(_tokenizar(query))
    if not tokens_q:
        return [(i, 0.0) for i in range(min(top_k, len(párrafos)))]
    puntuaciones = []
    for i, p in enumerate(párrafos):
        tokens_p = set(_tokenizar(p))
        score = len(tokens_q & tokens_p) / len(tokens_q)
        puntuaciones.append((i, score))
    puntuaciones.sort(key=lambda x: x[1], reverse=True)
    return puntuaciones[:top_k]


def filtrar_por_relevancia(sub_query, documentos, top_k_por_documento=2, max_párrafos_totales=8):
    # 1) Filtro de origen: solo documentos que nacieron de esta sub-consulta
    docs_candidatos = {
        url: doc for url, doc in documentos.items()
        if doc.get("query_origen") == sub_query
    }
    # Si el filtro deja vacío, cae a todos (evita perder recall cuando el planner colapsa)
    if not docs_candidatos:
        docs_candidatos = documentos

    # 2) Recopilar TODOS los párrafos como corpus global
    todos = []  # [(url, title, párrafo, idx_global)]
    for url, doc in docs_candidatos.items():
        for i, p in enumerate(_dividir_en_párrafos(doc["texto"])):
            if len(p) > 40:
                todos.append((url, doc["title"], p, i))

    if not todos:
        return []

    # 3) BM25 UNA SOLA VEZ con el corpus completo (esto es lo correcto)
    corpus_tokens = [_tokenizar(t[2]) for t in todos]
    if _HAS_BM25:
        bm25 = BM25Okapi(corpus_tokens)
        scores = bm25.get_scores(_tokenizar(sub_query))
    else:
        # Fallback Jaccard
        q_tokens = set(_tokenizar(sub_query))
        scores = []
        for toks in corpus_tokens:
            s = set(toks)
            scores.append(len(q_tokens & s) / max(len(q_tokens), 1))

    # 4) Agrupar por documento y quedarnos con top_k por doc
    por_doc: dict[str, list[tuple[float, str, str]]] = {}
    for (url, title, parr, _), sc in zip(todos, scores):
        if sc <= 0:
            continue
        por_doc.setdefault(url, []).append((sc, title, parr))

    candidatos = []
    for url, lista in por_doc.items():
        lista.sort(key=lambda x: x[0], reverse=True)
        for sc, title, parr in lista[:top_k_por_documento]:
            candidatos.append({
                "url": url, "title": title, "párrafo": parr,
                "score": sc, "query": sub_query,
            })

    candidatos.sort(key=lambda x: x["score"], reverse=True)

    # 5) Umbral dinámico: descarta la cola con score < 30% del mejor
    if candidatos:
        umbral = candidatos[0]["score"] * 0.3
        candidatos = [c for c in candidatos if c["score"] >= umbral]

    return candidatos[:max_párrafos_totales]