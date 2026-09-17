bash
#!/bin/bash

echo "🚀 Configurando Yiguirro Deep Research Agent..."

# 1. Verificar Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 no está instalado o no está en el PATH."
    exit 1
fi

# 2. Navegar al directorio del agente
if [ ! -d "yiguirroCoT" ]; then
    echo "❌ Error: No se encontró el directorio 'yiguirroCoT/'. Ejecuta este script desde la raíz del repositorio."
    exit 1
fi
cd yiguirroCoT || exit 1

# 3. Crear entorno virtual si no existe
if [ ! -d "venv" ]; then
    echo "📦 Creando entorno virtual (venv)..."
    python3 -m venv venv
else
    echo "✅ Entorno virtual (venv) ya existe."
fi

# 4. Instalar dependencias
echo "⚙️  Actualizando pip e instalando dependencias..."
venv/bin/pip install --upgrade pip > /dev/null
venv/bin/pip install -r requirements.txt

echo ""
echo "✅ ¡Configuración completada con éxito!"
echo ""
echo "📌 Para ejecutar el agente, asegúrate de que Ollama y SearXNG estén corriendo, luego usa:"
echo "   cd yiguirroCoT"
echo "   venv/bin/python3 agent.py"
echo ""