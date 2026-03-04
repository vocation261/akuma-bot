# BotkumaX

Bot de Discord para:
- reproducir X Spaces en canal de voz;
- consultar por scraping los participantes del Space actual (host, co-hosts, speakers y listeners);
- controlar reproducción por slash commands;
- guardar historial en SQLite;
- monitorear cuentas de X y enviar alertas automáticas cuando detecta Spaces en vivo.

## Resumen rápido del proyecto

BotkumaX unifica dos flujos en un solo proceso:
1. **Player de voz**: entra al voice channel y reproduce live/recorded.
2. **Monitor de alertas**: vigila cuentas de X y publica embeds de alerta en canales de Discord.

Esto evita tener dos bots/procesos separados para audio y alertas.

## Comandos slash

### Player y utilidades

- `/live <url>`: reproduce un Space en vivo en tu canal de voz.
- `/rec <url>`: reproduce un Space grabado.
- `/participants`: hace scraping del Space actual y muestra host, co-hosts, speakers y listeners.
- `/dash`: crea/actualiza el panel interactivo del bot.
- `/dc`: desconecta el bot del canal de voz.
- `/mute`: silencia o activa audio del bot.
- `/resume`: reanuda si está en pausa.
- `/forward <minutos>`: adelanta 1, 5, 10, 30 o 60 minutos.
- `/rewind <minutos>`: retrocede 1, 5 o 30 minutos.
- `/skip`: salta al siguiente item de la cola.
- `/cq`: limpia la cola de reproducción.
- `/now`: muestra lo que se está reproduciendo.
- `/queue`: lista la cola actual.
- `/mark`: guarda un bookmark de la posición actual.
- `/bookmarks`: lista bookmarks (`action:list`), elimina uno por `bookmark_id` (`action:delete`) o limpia todos (`action:clear`).
- `/history`: muestra historial reciente de reproducción.
- `/historycsv`: exporta historial a CSV.
- `/diag`: diagnóstico rápido del estado del bot.
- `/health`: snapshot operativo (latencia, uptime, voz, cola, etc.).
- `/alert_add <@handle|id>`: agrega una cuenta X a monitoreo y registra el canal actual para las alertas de esa cuenta.
- `/alert_remove <indice|id|@handle>`: quita la cuenta del canal actual; si ya no queda ningún canal asociado, la elimina del monitoreo.
- `/alert_list`: lista cuentas monitoreadas.
- `/alert_map <id> <handle>`: asocia ID de X con @handle.
- `/alert_interval <segundos>`: cambia intervalo de escaneo.
- `/alert_status`: muestra estado del monitor de alertas.
- `/alert_check`: fuerza un escaneo inmediato.

### Formato de URL soportado

- Válido: `https://x.com/i/spaces/<id>`
- Ejemplo: `https://x.com/i/spaces/1RKjpzpmXpLJw`
- No válido para reproducción: links `.../status/...` u otras rutas de X.

## Configuración de entorno

Mínimo requerido:
- `DISCORD_TOKEN`

Variables principales (opcional):
- `SYNC_GUILD_ID` sincroniza slash commands instantáneamente en un servidor específico.
- `HISTORY_DB_PATH` por defecto `data/history.db`.
- `IDLE_DISCONNECT_SECONDS` por defecto `60`.
- `DISCORD_ALERT_CHANNEL_IDS` lista de canales fallback para alertas (separados por coma).
- `DISCORD_ALERT_CHANNEL_ID` fallback de un solo canal.
- `DISCORD_ADMIN_CHANNEL_ID` canal para avisos de error/parcial de entrega.
- `DISCORD_ALERT_MENTION_EVERYONE` por defecto `true`.
- `ALERT_CONFIG_PATH` por defecto `config.json`.
- `ALERTED_SPACES_PATH` por defecto `alertados.json`.
- `X_AUTH_TOKEN`, `X_CT0`, `X_TWID` cookies de X/Twitter para scraping autenticado.
- Variables avanzadas del scraper (`X_PUBLIC_BEARER`, `X_WEB_BASE_URL`, `X_API_BASE_URL`, `X_GQL_*`, `X_HTTP_TIMEOUT_*`) para ajustar endpoints/query IDs sin cambiar código.

Referencia completa en:
- [`.env.example`](./.env.example)
- [`.env.dev`](./.env.dev)

## Ejecución local (sin Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
python -m akuma_bot.main
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m coverage run -m unittest discover -s tests -p "test_*.py"
python -m coverage report -m
```

## Estructura DDD (resumen)

- `src/akuma_bot/domain/alerts` y `src/akuma_bot/domain/playback`: entidades y reglas de dominio.
- `src/akuma_bot/application/alerts/use_cases` y `src/akuma_bot/application/playback/use_cases`: casos de uso.
- `src/akuma_bot/infrastructure/alerts/services`: monitor/scraper como adaptadores.
- `src/akuma_bot/infrastructure/discord/playback`: gateway de voz + servicios auxiliares.
- `src/akuma_bot/infrastructure/discord/commands`: registro central y módulos de comandos.

## Desarrollo con Docker (aislado de prod)

Este proyecto incluye setup de desarrollo separado para no mezclar estado con producción:
- `docker-compose.dev.yml`
- `.env.dev`
- `config.dev.json`
- `alertados.dev.json`

Comandos:

```bash
docker compose -f docker-compose.dev.yml up --build -d
docker compose -f docker-compose.dev.yml logs -f bot-dev
docker compose -f docker-compose.dev.yml down
```

## Producción con Docker/OCI

1. Preparar servidor (Docker instalado).
2. Crear carpeta de despliegue (por ejemplo `/opt/akuma-bot`).
3. Colocar `docker-compose.yml` + `.env` de producción.
4. Si la imagen es privada en GHCR, autenticar con PAT (`read:packages`).
5. Levantar:

```bash
docker compose down --remove-orphans
docker compose up -d --build
docker compose logs -f bot
```

## Nota sobre sync de comandos

Si defines `SYNC_GUILD_ID`, los slash commands se reflejan casi al instante en ese servidor.
Si no lo defines, el sync es global (puede tardar más).

## Nota de versión

### v0.0.3 (Marzo 2026)

- Validación estricta de URL para reproducción:
  - solo se acepta formato `https://x.com/i/spaces/<id>`.
- Comportamiento de voz actualizado:
  - el bot entra ensordecido al voice channel (escucha desactivada).
- Auto-salida por inactividad:
  - si pasan 5 minutos con solo el bot en VC, se desconecta y cierra sesión con aviso.
- Cierre automático al terminar Space:
  - si el Space termina, el bot sale del VC y publica un resumen (título, host, participantes, listeners, duración y URL).
  
### v0.2.0 (Marzo 2026)

- Nuevo comando `/participants`:
  - consulta participantes del Space actual por scraping;
  - muestra host, co-hosts, speakers y listeners;
  - ahora los `@usuarios` salen con link directo a su perfil en X.
- Mejoras en bookmarks:
  - `/mark` ahora acepta título opcional (`title`);
  - calcula `Position` como diferencia real entre inicio UTC del Space y momento del bookmark;
  - muestra `Space started (UTC)` y `Bookmarked (UTC)`.
- `/bookmarks` extendido con acciones:
  - `action:list` para listar;
  - `action:delete bookmark_id:<id>` para borrar uno;
  - `action:clear` para limpiar todos.
- Simplificación de controles:
  - se eliminaron comandos `/pause`, `/seek`, `/seekback`, `/seekto`;
  - se quitaron botones del panel: `Pause`, `-1m`, `-5m`, `+5m`, `+30m`, `+1h`, `Seek`, `Clear chat`.
- Enfoque solo X Spaces:
  - se retiró soporte de reproducción YouTube.
- Configuración del scraper movida a entorno:
  - query IDs, bearer, endpoints y timeouts ahora se controlan vía `.env`.
