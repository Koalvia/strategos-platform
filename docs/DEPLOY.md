# Despliegue (GitHub Actions → Hetzner)

Cada push a `main` (o ejecución manual del workflow) construye dos imágenes
(`backend` y `frontend`), las publica en **GHCR** y las despliega en el VPS por
SSH con `docker-compose.prod.yml`.

```
push main ─▶ build amd64 (backend + frontend) ─▶ push GHCR ─▶ scp compose+Caddyfile ─▶ ssh: pull + up -d
```

Archivos relevantes:
- [.github/workflows/deploy.yml](../.github/workflows/deploy.yml) — el pipeline.
- [docker-compose.prod.yml](../docker-compose.prod.yml) — stack de prod autocontenido (imágenes GHCR).
- [caddy/Caddyfile](../caddy/Caddyfile) — config del Caddy INTERNO de Strategos (strategos-caddy, sin puertos de host).
- `.env.deploy.example` — plantilla del `.env` de interpolación del servidor.

> **Dev no cambia.** `docker-compose.yml` (con `build:` y hot-reload) sigue igual:
> `docker compose up` en local funciona exactamente como antes.

Este stack comparte VPS con otros proyectos (`craze-commercial-platform`,
`solar-lead-generator`, ...), cada uno con su propio Caddy interno colgado de la
red externa `proxy`, y todos detrás del Caddy de entrada gestionado en el repo
[`Koalvia/infra`](https://github.com/Koalvia/infra) (dueño del 80/443 del host).

---

## 1. Secrets de GitHub (Settings → Secrets and variables → Actions)

| Secret | Qué es |
|---|---|
| `SERVER_IP` | IP del VPS de Hetzner |
| `SSH_USERNAME` | usuario SSH (`root`) |
| `SSH_PRIVATE_KEY` | clave privada SSH cuya pública está en `~/.ssh/authorized_keys` del VPS |
| `CR_PAT` | Personal Access Token (classic) con scope **`read:packages`**. Lo usa el VPS para hacer `docker login ghcr.io` y bajar las imágenes privadas |

> El push a GHCR desde el CI usa el `GITHUB_TOKEN` automático (no hay que crearlo).
> El `CR_PAT` es solo para que el **servidor** pueda *bajar* las imágenes. Si en su
> lugar marcas los packages como públicos (ver 2.5), `CR_PAT` deja de ser necesario.

---

## 2. Preparar el VPS (una sola vez)

### 2.1 Docker
Ya está instalado en este VPS (compartido con otros proyectos).

### 2.2 DNS
- Apunta un registro **A**: `strategos-platform.koalvia.com` → IP del VPS.
- Los puertos **80/443** ya los tiene el Caddy de entrada existente (`Koalvia/infra`);
  Strategos NO los toca.

### 2.3 Crear el directorio y los `.env` (¡los secretos viven aquí, no en GitHub!)
```bash
mkdir -p ~/strategos-platform/backend ~/strategos-platform/frontend
cd ~/strategos-platform
```

Crea **tres** ficheros `.env` (el workflow falla si faltan):

**`./.env`** — interpolación de la compose (mira `.env.deploy.example`):
```dotenv
PROXY_NETWORK=proxy
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<password-fuerte>
POSTGRES_DB=strategos_db
```

**`./backend/.env`** — secretos del backend. Parte de `backend/.env.example` del repo y rellena:
```dotenv
APP_ENV=production
SECRET_KEY=<random, min 32 chars>
CORS_ORIGINS=["https://strategos-platform.koalvia.com"]
FRONTEND_URL=https://strategos-platform.koalvia.com
RESEND_API_KEY=<clave real de Resend>
RESEND_FROM_EMAIL=noreply@koalvia.com
TESTING=0
```
> No hace falta poner `DATABASE_URL` ni `REDIS_URL`: la compose de prod los fija
> apuntando a los servicios internos `db` y `redis`.
>
> Mientras `RESEND_API_KEY` no sea una clave real, el envío del email de
> verificación falla en silencio (el registro/login siguen funcionando, pero
> hay que verificar el usuario a mano — ver "Primer deploy" más abajo).

**`./frontend/.env`** — config del frontend (vars server-side, se leen en runtime):
```dotenv
NEXT_PUBLIC_API_KEY=<la api key del api_client creado en el backend, ver "Primer deploy">
# NEXT_PUBLIC_API_URL lo fija la compose a http://api:8000 (no lo pongas aquí)
```

> Permisos: `chmod 600 .env backend/.env frontend/.env`.

### 2.4 Caddy de entrada: red compartida + site block

Ya está resuelto para este VPS (compartido con craze/solar-lead-generator): la red
`proxy` ya existe y el Caddy de entrada ya está conectado a ella. El site block para
Strategos vive en [`Koalvia/infra`](https://github.com/Koalvia/infra)
(`caddy/Caddyfile`):

```caddy
strategos-platform.koalvia.com {
    reverse_proxy strategos-caddy:80
}
```

Para aplicar cambios a ese fichero: edítalo en el repo `Koalvia/infra`, `git push`,
luego en el VPS:
```bash
cd ~/infra && git pull
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```
El Caddy de entrada saca el certificado TLS para `strategos-platform.koalvia.com`
automáticamente (requiere que el DNS ya resuelva) y reenvía HTTP plano a
`strategos-caddy`, que a su vez enruta al frontend (ver
[caddy/Caddyfile](../caddy/Caddyfile), la config interna de Strategos).

### 2.5 GHCR privado
Las imágenes son privadas por defecto. El VPS hace login con `CR_PAT` (lo hace el
workflow). Si prefieres, marca los *packages*
(`strategos-platform-backend`/`-frontend`) como públicos en GitHub y el login
del servidor pasa a ser opcional.

---

## 3. Desplegar

- **Automático:** `git push` a `main`.
- **Manual:** pestaña *Actions* → *Deploy* → *Run workflow*.

La primera vez, el contenedor `api` corre las migraciones (`RUN_MIGRATIONS=1`).

**Primer deploy — crear la API key (BD vacía):** el `frontend/.env` necesita una
`NEXT_PUBLIC_API_KEY` que exista en `api_clients`. En una BD nueva todavía no hay
ninguna:
```bash
cd ~/strategos-platform
docker compose -f docker-compose.prod.yml exec api python scripts/create_api_client.py --name frontend-app
# copia la key -> ponla en frontend/.env (NEXT_PUBLIC_API_KEY=...) y recrea el frontend:
docker compose -f docker-compose.prod.yml up -d --force-recreate frontend
```

**Primer deploy — sembrar el directorio de Usuarios (opcional):**
```bash
docker compose -f docker-compose.prod.yml exec api python -m scripts.seed_staff_users
```

**Verificar un usuario a mano** (mientras `RESEND_API_KEY` no sea real y el email
de verificación no llegue):
```bash
docker compose -f docker-compose.prod.yml exec db psql -U postgres -d strategos_db \
  -c "UPDATE users SET is_verified = true WHERE email = '<email>';"
```

Comprobar:
```bash
ssh hetzner-koalvia
cd ~/strategos-platform
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f caddy api frontend worker
# y que strategos-caddy y el Caddy de entrada comparten la red proxy:
docker network inspect proxy --format '{{range .Containers}}{{.Name}} {{end}}'
```

---

## 4. Rollback

Cada build deja también un tag inmutable `sha-XXXXXXX` en GHCR. Para volver atrás,
fija el tag en `./.env` del servidor y relanza:
```dotenv
BACKEND_IMAGE=ghcr.io/davidalonsobadia/strategos-platform-backend:sha-abc1234
FRONTEND_IMAGE=ghcr.io/davidalonsobadia/strategos-platform-frontend:sha-abc1234
```
```bash
docker compose -f docker-compose.prod.yml up -d
```
