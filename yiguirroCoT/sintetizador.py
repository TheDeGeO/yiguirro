"""
Sintetizador: combina los resúmenes parciales del mapeador en un informe
final estructurado, con citas a las URLs originales.
"""
import re
import requests
import config


SINTETIZADOR_SYSTEM_PROMPT = """Eres un redactor de informes de investigación profesional. Recibirás:
1. La pregunta original del usuario.
2. Varios resúmenes parciales, cada uno con sus fuentes listadas al final.

TAREA:
- Redacta un informe completo, estructurado en Markdown (títulos, subtítulos, listas).
- Integra toda la información coherente, eliminando redundancias.
- Si hay datos contradictorios entre resúmenes, menciónalos explícitamente.
- Cita cada afirmación usando el formato [1], [2]... refiriéndote al número de fuente.
- Al final, incluye una sección "## Fuentes" con la lista numerada de URLs.
- Si la información es insuficiente, indícalo claramente al inicio.
- Escribe en el mismo idioma que la pregunta original.
"""


def _construir_contexto(resúmenes: list[dict]) -> tuple[str, dict[int, str]]:
    url_a_num = {}
    num_a_url = {}
    contador = 1
    bloques = []
    total_chars = 0
    limite = config.MAX_CONTEXT_CHARS_SYNTH

    for i, r in enumerate(resúmenes, 1):
        resumen_texto = r["resumen"]
        fuentes = r["fuentes"]

        mapeo_local_a_global = {}
        for num_local, url in fuentes.items():
            if url not in url_a_num:
                url_a_num[url] = contador
                num_a_url[contador] = url
                contador += 1
            mapeo_local_a_global[num_local] = url_a_num[url]

        for local, global_n in mapeo_local_a_global.items():
            resumen_texto = resumen_texto.replace(f"[FUENTE_{local}]", f"[{global_n}]")

        # Presupuesto: si nos pasamos, recortamos el bloque (no lo tiramos)
        bloque = f"### Sub-consulta {i}: {r['sub_query']}\n{resumen_texto}"
        if total_chars + len(bloque) > limite:
            disponible = limite - total_chars
            if disponible < 500:
                break
            bloque = bloque[:disponible] + "\n[…] (recortado por presupuesto)"
        bloques.append(bloque)
        total_chars += len(bloque)

    contexto = "\n\n---\n\n".join(bloques)
    return contexto, num_a_url


def sintetizar(pregunta_original: str, resúmenes: list[dict]) -> str:
    """
    Genera el informe final combinando todos los resúmenes parciales.
    """
    contexto, num_a_url = _construir_contexto(resúmenes)

    user_msg = (
        f"PREGUNTA ORIGINAL DEL USUARIO:\n{pregunta_original}\n\n"
        f"RESÚMENES PARCIALES DE LA INVESTIGACIÓN:\n{contexto}\n\n"
        f"Genera el informe final en Markdown, citando las fuentes con [N]."
    )

    messages = [
        {"role": "system", "content": SINTETIZADOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    payload = {
        "model": config.LOCAL_LM_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 2500,
        "stream": False,
        "options": {"num_ctx": 4096},
    }

    try:
        r = requests.post(
            config.LOCAL_LM_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=600,
        )
        r.raise_for_status()
        informe = r.json()["choices"][0]["message"]["content"].strip()
        informe = re.sub(r"<think.*?</think>", "", informe, flags=re.DOTALL | re.IGNORECASE).strip()
    except Exception as e:
        print(f"[SINTETIZADOR] Error: {e}")
        return "Error al generar el informe final."

    # Si el modelo olvidó agregar la sección de fuentes, la añadimos
    if "## Fuentes" not in informe and num_a_url:
        fuentes_md = "\n## Fuentes\n"
        for n, url in sorted(num_a_url.items()):
            fuentes_md += f"[{n}] {url}\n"
        informe += "\n" + fuentes_md

    return informe