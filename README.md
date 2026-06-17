# Modelo Integral Proyecciones Nómina JMC V1.4

Ajuste principal de esta versión:

- Corrige lectura de archivos de novedades en formato plantilla ancha JMC, como Gerencia Administrativa y Compensación y Beneficios.
- Detecta correctamente la fila de encabezado cuando el archivo tiene título arriba y el encabezado real empieza en una fila posterior.
- Soporta plantillas donde el concepto SAP viene en una fila superior y el valor en columnas separadas.
- Si un archivo opcional falla, el módulo no se cae completo: registra el problema en ALERTAS_MODULO1 y continúa con los demás insumos.
- Mantiene DKON desde el módulo 1 y asignación de cuenta por tipo CECO: 101=60, 102=62, 103=63.

Archivos para Streamlit Cloud:

- app.py
- engine.py
- requirements.txt
- runtime.txt
- packages.txt
- .streamlit/config.toml

