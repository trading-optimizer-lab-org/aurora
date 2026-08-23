# Campaña sintética de cualificación del controlador

Esta carpeta contiene únicamente datos numéricos pequeños y deterministas para probar el controlador autónomo sin abrir datos de mercado, validación, datos bloqueados, credenciales ni artefactos de producción.

`campaign_v1.json` fija 24 recetas, 12 componentes, cuatro trabajadores de receta y dos de componentes. Cada componente, cada resultado y la salida final tienen un SHA-256 esperado. La reducción central y la jerárquica deben producir exactamente el mismo hash final.

Las claves RSA usadas para Q-041 se generan en memoria durante cada prueba. No se guarda, sube ni registra ninguna clave privada o token.

`manifest_v1.json` sella por ruta, tamaño y SHA-256 todos los archivos de datos y documentación de la fixture. El simulador es código de prueba y queda sellado por el recibo de cualificación y por las tres rondas de revisión.
