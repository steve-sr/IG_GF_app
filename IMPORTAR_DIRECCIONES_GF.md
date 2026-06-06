# Importación de direcciones de Grupos Familiares

Este paquete agrega el comando:

```bash
flask import-group-addresses
```

Qué hace:
- Crea/actualiza líderes según usuario/teléfono.
- Crea/actualiza la célula asignada a cada líder.
- Carga barrio, dirección y día desde la hoja de Grupos Familiares.
- Deja la hora como `Por definir` porque el archivo no trae hora.
- Activa las células que tienen dirección.
- No borra coordenadas, Google Maps ni Waze si ya fueron configurados.
- Es idempotente: se puede ejecutar otra vez sin duplicar.

Uso en Render Shell:

```bash
flask upgrade-db
flask ensure-admin
flask import-group-addresses
```

Después de importarlo, los líderes solo tendrían que entrar y usar `Usar mi ubicación actual` o `Señalar en mapa` para dejar coordenadas exactas.
