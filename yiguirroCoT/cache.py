"""
Cache en disco para SearxNG y extracción de texto.
Objetivo: evitar re-consultas costosas (rate limits, timeouts, CPU) en preguntas repetidas.
Sin dependencias externas. Thread-safe por operaciones atómicas de archivo.
"""
import hashlib
import json
import os
import time
import tempfile

CACHE_DIR = os.path.expanduser("~/.cache/deep_research")
os.makedirs(CACHE_DIR, exist_ok=True)

# TTLs por defecto (segundos)
TTL_SEARCH = 60 * 60 * 6      # 6 horas: resultados de búsqueda cambian poco
TTL_EXTRACT = 60 * 60 * 24    # 24 horas: el texto de una URL es estable
TTL_LLM = 60 * 60 * 24        # 24 horas: respuestas del planner idénticas


def _key(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _path(ns: str, k: str) -> str:
    return os.path.join(CACHE_DIR, f"{ns}_{_key(k)}.json")


def get(ns: str, k: str, ttl: int = TTL_SEARCH):
    """Devuelve el valor cacheado o None si expiró / no existe / está corrupto."""
    p = _path(ns, k)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("t", 0) > ttl:
            try:
                os.remove(p)
            except OSError:
                pass
            return None
        return data.get("v")
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def set(ns: str, k: str, v):
    """Escribe el valor de forma atómica (temp + rename) para no corromper con Ctrl+C."""
    p = _path(ns, k)
    try:
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"t": time.time(), "v": v}, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        # Si el cache falla, no debe romper el pipeline
        pass


def clear(ns: str | None = None):
    """Borra el cache. Si ns=None, borra todo."""
    if not os.path.isdir(CACHE_DIR):
        return 0
    borrados = 0
    for fname in os.listdir(CACHE_DIR):
        if ns and not fname.startswith(f"{ns}_"):
            continue
        if not fname.endswith(".json"):
            continue
        try:
            os.remove(os.path.join(CACHE_DIR, fname))
            borrados += 1
        except OSError:
            pass
    return borrados


def stats() -> dict:
    """Devuelve cuántos archivos hay por namespace y el tamaño total."""
    info = {"total_files": 0, "total_mb": 0.0, "por_ns": {}}
    if not os.path.isdir(CACHE_DIR):
        return info
    for fname in os.listdir(CACHE_DIR):
        if not fname.endswith(".json"):
            continue
        ns = fname.split("_", 1)[0]
        info["por_ns"][ns] = info["por_ns"].get(ns, 0) + 1
        info["total_files"] += 1
        try:
            info["total_mb"] += os.path.getsize(os.path.join(CACHE_DIR, fname)) / (1024 * 1024)
        except OSError:
            pass
    info["total_mb"] = round(info["total_mb"], 2)
    return info