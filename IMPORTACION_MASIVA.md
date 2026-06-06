# Importación masiva de líderes y células

Este paquete incluye `data/lideres_import.csv` generado desde el Excel original.

En Render Shell correr:

```bash
flask upgrade-db
flask ensure-admin
flask import-leaders-cells
```

Opcional si también querés importar direcciones ya procesadas:

```bash
flask import-group-addresses
```

No uses `flask init-db` en producción.

Las células creadas por `import-leaders-cells` quedan pausadas y con ubicación por definir para que cada líder complete su información.
