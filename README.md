# Modelo Integral Proyecciones Nómina JMC V1.3

Versión modular por pestañas.

## Qué cambia frente a V1.2

- Los módulos ya no se cargan ni ejecutan todos en una sola pantalla.
- Cada módulo tiene su propia pestaña, botón de ejecución y descarga de Excel.
- Si un módulo falla, no se pierden las salidas de los módulos ya calculados.
- El usuario puede revisar/comparar cada salida contra su plantilla base antes de continuar.
- El DKON se carga desde el inicio y se usa desde el Módulo 1 para cuentas y marcas.

## Flujo

1. Parametrización: DKON, MD actual y MD anterior.
2. Devengos proyectados: cálculo central tipo Proyección Costos.
3. Seguridad social y parafiscales: desde la salida del módulo 1.
4. Prestaciones: bases de prima y cesantías.
5. Vacaciones: base móvil 12 meses.
6. Consolidación final: une las salidas disponibles por cuenta DKON.

## Archivos raíz para Streamlit Cloud

- app.py
- engine.py
- requirements.txt
- runtime.txt
- packages.txt
- README.md
- .streamlit/config.toml

