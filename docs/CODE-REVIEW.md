# Revisió de codi — RedisManager

Document de conclusions d’una revisió orientada a **seguretat** i **qualitat de codi** (Bash, Perl CGI WHM, hooks, cron, plantilles). Basada en lectura del codi del repositori; sense proves d’execució al servidor.

**Data de la revisió:** març 2026

---

## Resum executiu

El disseny general (Redis per socket, WHM només per a root, validació d’usuari al CGI) és sòlid per a l’entorn cPanel/CloudLinux previst. Els punts més rellevants a tractar són: **validació consistent del nom d’usuari** (CLI i hooks vs CGI), **concurrencia sobre `state.json`**, possible **bug de doble parse CGI** a la configuració global, i **alineació** entre `REDIS_BINARY` i la unitat systemd.

---

## Fortaleses

| Àrea | Observació |
|------|------------|
| **WHM** | `Whostmgr::ACLS::hasroot()` abans de la lògica; el plugin assumeix accés root. |
| **Validació al CGI** | Patró `^[a-z][a-z0-9_]{0,30}$` abans d’executar `redismanager-ctl` via backticks; redueix risc d’injecció. |
| **Redis** | Socket Unix, sense TCP exposat; permisos de socket 600; mode cache sense persistència explícita a la plantilla. |
| **Scripts** | `set -euo pipefail` als scripts principals; menys fallades silencioses. |
| **Pressupost de memòria** | `check_budget` i `TOTAL_BUDGET_MB` limiten el compromís global de RAM. |

---

## Seguretat — punts a millorar

### 1. Interpolació d’usuari en fragments Python (CLI i hooks)

A `bin/redismanager-ctl` i `hooks/redismanager-hooks`, el nom d’usuari s’embeu dins de `python3 -c '...'`. Caràcters com `'` o contingut inesperat podrien trencar la cadena o comportar-se de forma imprevista.

- El **CGI** restringeix el format; la **CLI** no aplica el mateix regex.
- **Recomanació:** validar el mateix format d’usuari (o el que cPanel garanteixi oficialment) abans de qualsevol ús en Python o en comandes construïdes dinàmicament.

### 2. Hook WHM i confiança en el JSON d’entrada

El `USERNAME` extret del JSON del hook acaba en comandes shell i en més Python embeut. cPanel sol ser font de confiança, però **validar el format d’usuari** abans d’usar-lo tanca la porta a casos límit o canvis futurs del format del hook.

### 3. Instal·lació remota (`curl | bash`)

El flux documentat al README és el patró habitual de **cadena de subministrament sense verificació** (checksum, tag signat, etc.). És un risc operatiu conegut; convé que la documentació ho mencioni explícitament com a trade-off.

### 4. XSS al WHM (prioritat baixa en context admin)

Missatges d’èxit/error i dades mostrades (domini, usuari, sortida d’errors) podrien, en teoria, incloure caràcters HTML si alguna capa retorna text no confiable. En un panel només accessible a root el risc és **baix**, però és bona pràctica **escapar** sortida HTML (`HTML::Entities` o equivalent al CGI).

### 5. Integritat de `state.json` sense bloqueig

Escriptures concurrents (cron, WHM, CLI) poden **corrompre** el fitxer o perdre actualitzacions. No és una CVE típica, però afecta **integritat de dades**.

- **Recomanació:** `flock` en lectura/escriptura, o escriptura atòmica (fitxer temporal + `rename`).

### 6. `REDIS_BINARY` vs unitat systemd

`etc/redismanager.conf` permet canviar `REDIS_BINARY`, però `templates/redis-managed.service` té el camí del binari **fix** (`/opt/alt/redis/bin/redis-server`). `redismanager-ctl` valida el binari de la conf, però el servei systemd pot seguir un altre executable fins que no es reinstal·li o sincronitzi la unitat — especialment rellevant en migracions Redis → Valkey.

---

## Qualitat de codi i possibles bugs

### 1. `get_redis_info` al CGI (codi mort + error latent)

A `whm/addon_redismanager.cgi`, la subrutina `get_redis_info` referencia `%conf` fora d’àmbit si s’usés tal com està. **Actualment no es crida** enlloc (codi mort). Si es reactiva, cal passar la configuració o tornar a llegir el fitxer.

### 2. `save_global_config` i doble `CGI->new`

Dins `handle_action`, per a `save-config` es crida `save_global_config`, que instancia un **segon** `CGI->new`. Sovint el cos POST ja s’ha consumit amb el primer objecte CGI; el segon pot **no rebre els paràmetres** del formulari.

- **Recomanació:** verificar amb una petició POST real a “Save” de la configuració global; si falla, passar els `cfg_*` des del primer parse.

### 3. Inconsistència límit de memòria WHM vs CLI

El WHM limita memòria (p. ex. 16–512 MB en accions concretes); la CLI `enable` depèn sobretot del pressupost global sense els mateixos límits per defecte. Pot ser intencional (flexibilitat per a root); convé **documentar-ho** o alinear criteris.

### 4. Neteja menor als hooks

A `hooks/redismanager-hooks`, la variable `CONTEXT` es defineix però no s’utilitza; només s’usa `cp_hook_event`. Es pot eliminar o documentar per claredat.

---

## Taula ràpida

| Tema | Gravetat percebut | Acció suggerida |
|------|-------------------|-----------------|
| Validació d’usuari CLI/hooks | Mitjana (defensa en profunditat) | Regex compartit amb el CGI |
| `state.json` concurrent | Mitjana (dades) | `flock` o escriptura atòmica |
| Doble CGI a `save_global_config` | Alta si el formulari falla | Provar i corregir parse únic |
| Systemd vs `REDIS_BINARY` | Mitjana (operacions) | Plantilla dinàmica o documentació |
| XSS / escape HTML | Baixa (WHM root) | Escapar sortida |
| `get_redis_info` | Baixa | Eliminar o arreglar abans d’usar |
| `curl \| bash` | Operativa | Documentar risc; opcionalment checksums |

---

## Conclusió

El projecte és coherent amb el seu objectiu (Redis aïllat per compte en entorn cPanel). Les millores més valuoses són **robustesa del fitxer d’estat**, **validació uniforme d’usuaris** als punts d’entrada, **correcció del flux CGI** si la configuració global no es desa bé, i **claredat** entre binari configurat i el que executa systemd.

---

*Aquest document no substitueix una auditoria de seguretat professional ni proves en entorn de staging/producció.*
