"""
Agent: orquestador principal del sistema de Deep Research local.
Integra: planificador → buscador → filtrador → mapeador → sintetizador.
"""
import sys
import time
import threading
import datetime
import platform
import os
import re
import cache

try:
    import config
    import planificador
    import buscador
    import filtrador
    import mapeador
    import sintetizador
except ImportError as e:
    print(f"ERROR: Módulo no encontrado: {e}")
    sys.exit(1)


def get_dynamic_system_context() -> str:
    now = datetime.datetime.now()
    cpu_info = platform.processor() or "Unknown"
    return (
        f"--- SYSTEM CONTEXT ---\n"
        f"Current Date/Time: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')}).\n"
        f"OS: {platform.system()} {platform.release()} ({platform.machine()}).\n"
        f"CPU: {cpu_info} ({os.cpu_count()} logical cores).\n"
        f"AI Model: {config.LOCAL_LM_MODEL}.\n"
        f"Agent: Deep Research Agent v2.0 | Backend: Ollama+SearxNG.\n"
        f"----------------------\n"
    )


def animate_waiting(stop_event, mensaje="Procesando"):
    animation = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0
    while not stop_event.is_set():
        print(f"\r{animation[idx % len(animation)]} {mensaje}...  ", end="", flush=True)
        idx += 1
        time.sleep(0.1)
    print("\r" + " " * 60 + "\r", end="", flush=True)

def validar_input(texto: str) -> str:
    """
    Relaja el límite a 3000 caracteres (aprox. 800-1000 tokens).
    Los modelos de 1.5B manejan esto sin problemas y evita perder
    detalles críticos como cifras, comparaciones y nombres específicos.
    """
    if len(texto) <= 3000:
        return texto
    
    print(f"\n⚠️  Input extremadamente largo ({len(texto)} caracteres). Truncando a las primeras 10 oraciones sustantivas.")
    oraciones = re.split(r'(?<=[.!?])\s+', texto)
    oraciones_validas = [o for o in oraciones if len(o.strip()) > 20][:10]
    return " ".join(oraciones_validas)

def ejecutar_deep_research(pregunta: str) -> str:
    """
    Pipeline completo de Deep Research:
    1. Planificar sub-consultas
    2. Buscar y extraer texto
    3. Filtrar por relevancia (BM25)
    4. Mapear (resumir por sub-consulta)
    5. Sintetizar (informe final)
    """
    print("\n" + "=" * 60)
    print(f"🔬 INICIANDO INVESTIGACIÓN: {pregunta}")
    print("=" * 60)

    # 1. Planificar
    print("\n[1/5] 🧠 Planificando sub-consultas...")
    sub_queries = planificador.planificar(pregunta)
    print(f"   → {len(sub_queries)} sub-consultas.")

    # 2. Buscar y extraer
    print("\n[2/5] 🔍 Buscando y extrayendo contenido...")
    documentos = buscador.recolectar(sub_queries, max_por_query=config.MAX_SEARCH_RESULTS)
    if not documentos:
        return "⚠️ No se pudo extraer contenido útil de ninguna página."

    # 3. Filtrar por relevancia
    print("\n[3/5] 🎯 Filtrando párrafos relevantes (BM25)...")
    todos_párrafos = []
    for q in sub_queries:
        párrafos = filtrador.filtrar_por_relevancia(q, documentos, top_k_por_documento=2, max_párrafos_totales=8)
        todos_párrafos.extend(párrafos)
        print(f"   → '{q[:50]}...': {len(párrafos)} párrafos relevantes.")

    if not todos_párrafos:
        return "⚠️ No se encontró información relevante en las páginas consultadas."

    # 4. Mapear (resumir por sub-consulta)
    print("\n[4/5] 📝 Resumiendo información por sub-consulta...")
    resúmenes = []
    for q in sub_queries:
        párrafos_q = [p for p in todos_párrafos if p["query"] == q]
        if not párrafos_q:
            continue
        stop = threading.Event()
        threading.Thread(target=animate_waiting, args=(stop, f"Mapeando '{q[:30]}'"), daemon=True).start()
        try:
            resumen = mapeador.mapear(q, párrafos_q)
            resúmenes.append(resumen)
        finally:
            stop.set()
            time.sleep(0.2)

    # 5. Sintetizar
    print("\n[5/5] 📄 Redactando informe final...")
    stop = threading.Event()
    threading.Thread(target=animate_waiting, args=(stop, "Sintetizando informe"), daemon=True).start()
    try:
        informe = sintetizador.sintetizar(pregunta, resúmenes)
    finally:
        stop.set()
        time.sleep(0.2)

    return informe


def handle_command(command: str, history: list) -> bool:
    cmd = command.lower().strip()
    if cmd in ["/bye", "/exit", "/quit"]:
        print("\nGoodbye! 👋")
        sys.exit(0)
    elif cmd == "/clear":
        history.clear()
        print("\n✓ Conversation history cleared.")
        return True
    elif cmd == "/help":
        print("\n" + "=" * 50)
        print("🤖 Deep Research Agent - Comandos")
        print("=" * 50)
        print("/help    - Mostrar esta ayuda")
        print("/clear   - Limpiar historial")
        print("/info    - Información del sistema")
        print("/model   - Modelo actual")
        print("/bye     - Salir")
        print("=" * 50)
        print("\n💡 Escribe cualquier pregunta compleja para iniciar")
        print("   una investigación profunda con fuentes reales.\n")
        print("/cache   - Estadísticas del cache en disco")
        print("/cache clear [ns] - Borrar cache (todo o por namespace)")
        return True
    elif cmd == "/info":
        print("\n" + get_dynamic_system_context())
        return True
    elif cmd == "/model":
        print(f"\nModelo actual: {config.LOCAL_LM_MODEL}")
        return True
    elif cmd == "/cache":
        info = cache.stats()
        print(f"\n📦 Cache: {info['total_files']} archivos, {info['total_mb']} MB")
        for ns, n in info["por_ns"].items():
            print(f"   {ns}: {n} entradas")
        return True
    elif cmd.startswith("/cache clear"):
        partes = cmd.split()
        ns = partes[2] if len(partes) > 2 else None
        n = cache.clear(ns)
        print(f"\n✓ Cache borrado: {n} archivos ({'todo' if ns is None else ns})")
        return True
    return False


def print_welcome():
    print("\n" + "=" * 60)
    print("🔬 Deep Research Agent - Investigación Local Avanzada")
    print("=" * 60)
    print(f"Modelo: {config.LOCAL_LM_MODEL}")
    print(f"SearxNG: {config.SEARXNG_URL}")
    print("Escribe /help para ver los comandos disponibles.")
    print("=" * 60 + "\n")


def main():
    print_welcome()
    conversation_history = []

    while True:
        try:
            print("Tú: ", end="", flush=True)
            user_prompt = input()
            if not user_prompt.strip():
                continue

            if user_prompt.strip().startswith("/"):
                if handle_command(user_prompt.strip(), conversation_history):
                    continue

            # Pipeline de Deep Research
            user_prompt_limpio = validar_input(user_prompt.strip())
            informe = ejecutar_deep_research(user_prompt_limpio)

            print("\n" + "=" * 60)
            print(informe)
            print("=" * 60 + "\n")

            conversation_history.append({"role": "user", "content": user_prompt})
            conversation_history.append({"role": "assistant", "content": informe})

            # Limitar historial
            max_turns = getattr(config, "MAX_HISTORY_TURNS", 10)
            if len(conversation_history) > max_turns * 2:
                conversation_history = conversation_history[-(max_turns * 2):]

        except KeyboardInterrupt:
            print("\n\nSaliendo... (Ctrl+C)")
            break
        except EOFError:
            print("\n\nSaliendo... (EOF)")
            break


if __name__ == "__main__":
    if not config.LOCAL_LM_URL or not config.SEARXNG_URL:
        print("ERROR: URLs no configuradas en config.py.")
        sys.exit(1)
    main()