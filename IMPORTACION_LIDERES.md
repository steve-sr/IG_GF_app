# Importación inicial de líderes y células

Este paquete agrega el comando:

```bash
flask import-leaders-cells
```

Qué hace:
- Crea/actualiza líderes desde el Excel entregado.
- Usa `usuario` y `contraseña` del Excel.
- Crea una célula esqueleto asignada a cada líder.
- Deja cada célula en estado `paused` para que no salga pública hasta completar datos.
- Dirección, día y hora quedan “Por definir”.
- El líder, al entrar, verá su célula asignada y podrá completar la información.

Ejecutar en Render Shell una sola vez después del deploy:

```bash
flask upgrade-db
flask ensure-admin
flask import-leaders-cells
```

No usar `flask init-db` en producción porque borra la base.
