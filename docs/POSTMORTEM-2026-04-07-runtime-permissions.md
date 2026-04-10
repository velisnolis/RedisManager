# Postmortem: Incident de permisos runtime

Data de l'incident: 2026-04-07

## Resum

Després del desplegament dels canvis de hardening derivats de la code review adversarial, alguns sites gestionats per RedisManager van començar a retornar errors `500`.

L'incident va afectar com a mínim:

- `aico.cat`
- `comunitat.congresbit.cat`
- `gibaix.com`

La causa arrel no era Joomla, WordPress ni Redis en si mateix, sinó una incompatibilitat entre el nou model de permisos del control script i el model real d'execució del servei systemd.

## Impacte

- Les instàncies Redis per usuari van deixar d'arrencar correctament.
- Els webs que depenien del socket Unix de Redis per a sessions o cache van començar a fallar amb `500`.
- El símptoma principal a `journalctl` va ser primer `status=203/EXEC` i després errors de `Permission denied`.

## Causa arrel

La unitat systemd real de producció arrenca Redis així:

```ini
ExecStart=/opt/redismanager/bin/redismanager-ctl launch %i
User=%i
Group=%i
```

Per tant, la comanda `launch` s'executa com l'usuari cPanel del compte, no com `root`.

El hardening anterior havia trencat aquest contracte en diversos punts:

- `redismanager-ctl` es va instal·lar amb permisos `750 root:root`
- `state.json` es va restringir a `640`
- `/var/lib/redismanager` i `/var/log/redismanager` es van restringir massa
- el control script va passar a exigir `root` globalment

Això va impedir que el camí `launch` pogués executar-se o llegir l'estat compartit, i les instàncies Redis van deixar de pujar.

## Resolució

Es va aplicar un fix orientat a restaurar la compatibilitat amb el model real d'execució:

- només `launch` pot executar-se sense `root`
- la inicialització global de `state/log` només la fa `root`
- el camí no-root només llegeix l'estat
- les operacions de `chown` es limiten a context `root`
- `redismanager-ctl` es torna a desplegar amb `755`
- `state.json` es torna a deixar llegible amb `644`
- els directoris globals de runtime es deixen compatibles amb el llançament per usuari

Durant la recuperació es va fer també neteja controlada de processos orfes i reinici net de `redis-managed@aico` per recrear correctament `redis.sock`.

## Correcció addicional

Es va detectar un segon problema menor: versions anteriors del plugin havien escrit la configuració de session locking a `.user.ini` sense marcadors, mentre que la versió nova usa un bloc marcat.

Això podia deixar blocs duplicats al mateix fitxer. Es va corregir el control script perquè normalitzi `.user.ini` en format nou i també s'ha netejat el cas real detectat a `aico`.

## Validació

Després del fix i la neteja:

- `aico.cat` respon `200`
- `comunitat.congresbit.cat` respon `200`
- `gibaix.com` respon `200`
- les instàncies Redis gestionades queden `active (running)`
- el socket d'`aico` torna a respondre `PONG`

## Accions de seguiment

- Mantenir el model `launch as account user` com a restricció explícita del disseny.
- Evitar futurs hardenings que assumeixin `root-only` sense revisar abans la unitat systemd real.
- Conservar la compatibilitat amb `.user.ini` legacy mentre hi hagi instal·lacions antigues en producció.
- Revisar i esborrar backups temporals després del període de soak acordat.

## Tancament operatiu

El `2026-04-10`, un cop superat el període de soak sense regressions i amb validació final correcta (`HTTP 200` als tres sites afectats i instàncies Redis `active`), es van eliminar els backups temporals creats durant la resposta a l'incident.

Es van esborrar:

- `/root/redismanager-backup-20260406-104424`
- `/root/redismanager-cleanup-preflight-20260407-082535.txt`
- `/opt/redismanager/bin/redismanager-ctl.bak-20260407-083149`
- `/home/aico/public_html/.user.ini.bak-20260407-083011`

El snapshot del servidor es manté com a còpia de seguretat forta prèvia a la intervenció.
