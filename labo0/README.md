# Projet gridd — labo0

- `backend/` : service Python qui consomme les topics Kafka du cluster gridd,
  evalue les alertes et construit les vues du jumeau numerique.
- `frontend/` : jumeau numerique Vite + React, trois ecrans (Par piece, Par
  capteur, Alertes) ; aucune logique metier cote client.
- `docker-compose.yml` : orchestration des services.

## Frontend : jumeau numerique

En Docker (avec le reste de la stack) :

```bash
docker compose --env-file backend/.env up -d --build
# Dashboard : http://localhost:8080
```

L'image construit le frontend (Vite) puis le sert via nginx, qui relaie
`/api` et `/ws` vers le backend a l'interieur du reseau compose (meme
origine, pas de CORS, WebSocket upgrade gere).

En developpement (rechargement a chaud) :

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 (le backend doit tourner sur :8000)
npm test        # Vitest : routage par hash et formatage des heures
```

**Principe : le frontend n'applique aucune regle.** Il ouvre un seul
WebSocket (`/ws/dashboard`), lui envoie les parametres de l'ecran affiche
(piece, type de capteur, plage, tri, filtre) et affiche la vue complete que le
backend renvoie, puis repousse a chaque changement de donnees (au plus une fois
par seconde). Pieces, etats, libelles, seuils, nombres formates, tris, comptes
et notifications viennent du backend (voir [Dashboard](#dashboard-jumeau-numerique)) ;
le client ne formate que les heures (fuseau du navigateur) et trace les
sparklines a partir des points fournis. Sa seule action est « Acquitter »
(`POST /api/alerts/<id>/acknowledge`). Details dans `frontend/README.md`.

## Backend : consommateur Kafka

Service Python 100 % asyncio (aiokafka) qui se connecte au cluster Kafka en
SASL_SSL (authentification SCRAM, verification du broker par certificat CA)
et consomme **chaque topic separement** : une tache asyncio et un
consommateur dedies par topic, chacun avec son propre `group.id` et ses
propres offsets. Consommateurs et serveur WebSocket partagent la meme boucle
d'evenements. Les mesures de chaque topic sont archivees par lots dans une
base SQLite (`OUTPUT_DIR/history.sqlite`, 30 jours glissants, voir
[Archive SQLite](#archive-sqlite)), qui fixe aussi le point de reprise du
consommateur.

### Architecture : patron Observateur

L'acquisition (consommateurs et suiveurs Kafka) ne connait qu'un **bus de
records** (`app/data_management/record_bus.py`), le Sujet du patron
Observateur : chaque record lui est publie, et il le transmet a tous les
observateurs inscrits, un par un, dans l'ordre d'inscription. Le hub
WebSocket est le premier observateur, le dashboard (jumeau numerique, voir
[Dashboard](#dashboard-jumeau-numerique)) le deuxieme, le service d'alertes
(voir [Alertes](#alertes)) le troisieme ; un futur service (qualite des
donnees, export) devient un observateur de plus, inscrit dans `app/main.py`,
sans toucher a l'acquisition. L'archivage n'est pas un observateur : le
consommateur ecrit la base avant de publier le lot.

Contrat d'un observateur (protocole `RecordObserver`) :

- une methode `async def on_record(self, topic, record, *, replay)`, appelee
  dans la boucle asyncio : elle doit etre **rapide**, ou deleguer le travail
  lent ou bloquant (`asyncio.to_thread`, file traitee par une tache dediee),
  car elle retarde les observateurs suivants et le commit ;
- **idempotente** : la livraison est "au moins une fois" et le prechauffage
  peut relire des messages deja vus (un record est identifie par `topic`,
  `partition`, `offset` ; `records.OffsetTracker` fournit ce filtre) ;
- `replay=True` signale un record relu au demarrage (queue du suiveur) ou
  anterieur de plus de 5 minutes au demarrage du service (rattrapage d'un
  arret prolonge, ou de toute la retention Kafka quand la base n'a pas de
  curseur) : il sert a reconstruire un etat (historique, registre, alertes
  actives), mais aucun evenement ne doit en sortir (ni notification, ni
  annonce). Le hub traite les deux de la meme facon.

Garanties :

- **au moins une fois** : chaque lot (500 messages au plus) est archive,
  puis notifie a tous les observateurs, puis commite ; un arret pendant le
  traitement fait relire le lot au redemarrage, et la base comme les
  observateurs ignorent les doublons. La position de reprise vient de la
  base (dernier offset archive par partition) ; l'offset commite du groupe
  Kafka ne sert qu'au suivi du retard ;
- **isolation des pannes** : l'exception d'un observateur est journalisee
  (classe, topic, partition, offset) et n'empeche ni les observateurs
  suivants, ni la diffusion WebSocket, ni le commit. Le record n'est pas
  renvoye a l'observateur en echec : s'il ne doit rien perdre, il gere ses
  propres reprises. Une annulation (arret du service) n'est jamais avalee.

### Deux lecteurs par topic

Chaque topic est lu par deux taches (`app/services/streaming_service.py`) :

- le **consommateur** (`data_acquisition/consumer.py`, groupe Kafka) reprend
  apres le dernier offset archive de chaque partition (sans curseur : au debut
  de la retention Kafka, soit une douzaine de jours), archive chaque lot,
  publie ses records puis commite. Pendant un rattrapage il livre le passe,
  dans l'ordre ;
- le **suiveur** (`data_acquisition/live_follower.py`, sans groupe ni commit)
  publie d'abord la queue de chaque partition (`warmup_messages`, comme
  rejouee), puis chaque nouveau message des son arrivee : le frontend recoit
  le temps reel meme pendant un rattrapage de plusieurs jours. Il s'arrete
  de lui-meme quand le consommateur a livre, sur chaque partition, la fin
  relevee a son depart ; en regime etabli il ne reste qu'un lecteur.

Un record livre par les deux est ignore par chaque observateur (hub : cles
par capteur ; alertes : `OffsetTracker` ; jumeau : `SeenOffsets`).

Exemple : un registre de la derniere mesure de chaque capteur.

```python
from app.data_management.records import sensor_id


class SensorRegistry:  # ex. app/services/sensor_registry.py
    def __init__(self) -> None:
        self.latest: dict[tuple[str, str], dict] = {}

    async def on_record(self, topic: str, record: dict, *, replay: bool) -> None:
        # Construit un etat : les records rejoues servent aussi (replay ignore).
        # Capteur identifie comme le hub et les alertes (helper partage sensor_id)
        key = (topic, sensor_id(record))
        # Idempotent : un doublon ou un record plus ancien est sans effet.
        known = self.latest.get(key)
        if known is None or record["timestamp_ms"] >= known["timestamp_ms"]:
            self.latest[key] = record

# app/main.py, dans create_bus() : les observateurs s'inscrivent ici
bus = RecordBus()
bus.subscribe(hub)               # diffusion WebSocket (1er observateur)
bus.subscribe(dashboard)         # jumeau numerique (vues du dashboard)
bus.subscribe(alerts)            # service d'alertes
bus.subscribe(SensorRegistry())  # nouvel observateur, acquisition inchangee
```

Le `StreamingService` recoit ce bus et l'archive
(`StreamingService(settings, hub, bus, store)`) ;
seul `create_bus` y inscrit des observateurs. Le hub doit y etre inscrit,
puisque les abonnements WebSocket du service en dependent : sinon le service
refuse d'etre construit (`ValueError`). Les tests de l'API utilisent le meme
`create_bus`.

### Topics consommes

Definis dans `backend/config/topics.yaml` (seule source de la liste), suivant la convention `gridd.<data_category>.<domain>.<data_type>` :

- `gridd.obs.environmental.temperature`
- `gridd.obs.environmental.humidity`
- `gridd.obs.environmental.co2`
- `gridd.obs.acoustic.sound_level`
- `gridd.obs.occupancy.count`

### Configuration (variables d'environnement)

| Variable | Defaut | Description |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9093` | Bootstrap server (`hote:port,...`) |
| `KAFKA_SECURITY_PROTOCOL` | `SASL_SSL` | `SASL_SSL`, `SSL` ou `PLAINTEXT` |
| `KAFKA_SASL_MECHANISM` | `SCRAM-SHA-256` | `SCRAM-SHA-256`, `SCRAM-SHA-512` ou `PLAIN` |
| `KAFKA_USERNAME` | — | Kafka username (requis en SASL) |
| `KAFKA_PASSWORD` | — | Kafka password (requis en SASL) |
| `KAFKA_SSL_CA_HOST_PATH` | — | CA certificate : chemin sur l'hote (monte en volume) |
| `KAFKA_SSL_CA_LOCATION` | `/etc/gridd/kafka/gridd-kafka-ca.crt` | CA certificate : chemin dans le conteneur |
| `KAFKA_GROUP_ID_PREFIX` | `gridd-consumer` | Prefixe du `group.id` par topic |
| `KAFKA_AUTO_OFFSET_RESET` | `earliest` | Position de repli quand l'offset de reprise est sorti de la retention |
| `OUTPUT_DIR` | `/var/lib/gridd/data` | Repertoire de l'archive SQLite (`history.sqlite` et ses fichiers `-wal`/`-shm`) |
| `TOPICS_CONFIG` | `config/topics.yaml` | Fichier YAML des topics et de leurs historiques |
| `ALERTS_CONFIG` | `config/alerts.yaml` | Fichier YAML des regles d'alerte (absent : alertes desactivees) |

### Configuration des topics (`backend/config/topics.yaml`)

Les topics consommes et leurs reglages se definissent dans un YAML, monte
dans le conteneur (modifiable sans rebuild ; un redemarrage suffit) :

```yaml
defaults:
  history_per_sensor: 100   # messages conserves/rejoues par capteur
  warmup_messages: 1000     # queue relue par partition au demarrage

topics:
  gridd.obs.environmental.temperature: {}      # prend les defauts
  gridd.obs.acoustic.sound_level:
    history_per_sensor: 1800   # publie toutes les 6 s -> ~3 h d'historique
    warmup_messages: 8000      # 4 capteurs x 1800 sur 1 partition
```

`warmup_messages` se dimensionne ainsi : `history_per_sensor x nb de capteurs
du topic / nb de partitions`, arrondi au-dessus. `history_per_sensor` vaut
100 s'il n'est fixe ni sur le topic ni dans `defaults`. Le fichier est
obligatoire : s'il est absent, ne definit aucun topic, contient une cle
dupliquee ou une structure invalide (liste au lieu d'un dictionnaire,
reglage non entier), le service refuse de demarrer et journalise une ligne
qui nomme le fichier (pas de traceback).

### Alertes

Le service d'alertes (`app/services/alert_service.py`) est un observateur du
bus : il evalue chaque mesure temps reel contre les regles de son topic, tient
la liste des alertes actives (une au plus par capteur et par topic) et
diffuse chaque changement de niveau. L'evaluation (seuils, hysteresis,
transitions, messages) est une logique pure, testee isolement, dans
`app/data_management/data_processing/alert_rules.py` ; le formatage francais
des messages (nombres, unites, libelles des topics) vit a cote, dans
`formatting.py`.

**Configuration** : `backend/config/alerts.yaml` (chemin modifiable par
`ALERTS_CONFIG`), monte dans le conteneur comme `topics.yaml` (modifiable sans
rebuild ; un redemarrage suffit).

```yaml
defaults:
  hysteresis: 0            # optionnel : hysteresis des regles qui n'en fixent pas
rules:
  gridd.obs.environmental.co2:
    - { severity: warning, above: 1000, hysteresis: 50 }
    - { severity: critical, above: 1500, hysteresis: 50 }
  gridd.obs.environmental.temperature:
    - { severity: warning, below: 18, hysteresis: 0.5 }
    - { severity: warning, above: 26, hysteresis: 0.5 }
```

Une regle : `severity` (`warning` ou `critical`), une direction (`above` ou
`below`) avec son seuil numerique, et une `hysteresis` optionnelle (>= 0).

- **Fichier absent** : alertes desactivees (avertissement au demarrage), le
  service demarre normalement ; l'API repond `enabled: false`.
- **Fichier invalide** (severite ou direction inconnue, seuil non numerique,
  hysteresis negative, cle inconnue, cle dupliquee -- un topic ou une
  direction ecrits deux fois --, regle sur un topic absent de
  `topics.yaml`) : le service refuse de demarrer et journalise chaque erreur
  avec le fichier, le topic et le numero de la regle (ou la ligne).

Valeurs livrees, **indicatives, a valider avec les responsables des
donnees** :

| Topic | warning | critical | Hysteresis |
|---|---|---|---|
| CO2 | > 1000 ppm | > 1500 ppm | 50 |
| Temperature | < 18 et > 26 degC | < 16 et > 28 degC | 0.5 |
| Humidite | < 25 et > 60 % | < 20 et > 70 % | 2 |
| Niveau sonore | > 65 dB | > 80 dB | 2 |
| Occupation | aucune regle (capacite des salles inconnue ; exemple commente) | | |

**Semantique** :

- **Seuil et hysteresis** : une regle `above` s'active quand la valeur depasse
  *strictement* le seuil (une valeur egale au seuil ne declenche pas) et reste
  active tant que `valeur > seuil - hysteresis` ; `below` est symetrique
  (active si `valeur < seuil`, tant que `valeur < seuil + hysteresis`).
  L'hysteresis evite qu'une valeur qui oscille autour du seuil declenche et
  resolve l'alerte en boucle. Tant qu'une alerte n'est maintenue que par sa
  bande d'hysteresis, son message ne dit plus que le seuil est franchi et
  donne la limite de la bande (ex. "CO2 a 960 ppm (seuil 1 000 ppm), alerte
  maintenue jusqu'a 950 ppm" ; "niveau critique maintenu" pour une regle
  `critical`, qui redescend en `warning` en sortant de sa bande).
- **Severite** : le niveau d'un capteur est la severite maximale de ses
  regles actives (`critical` > `warning` > aucun). Le seuil et la direction
  de l'alerte sont ceux de la regle active la plus severe (a egalite, celle
  que la valeur depasse le plus).
- **Evenements** : aucun -> X `raised` ; warning -> critical `escalated` ;
  critical -> warning `deescalated` ; X -> aucun `resolved` ; acquittement
  par un operateur `acknowledged`. Un passage direct de "trop haut" a "trop
  bas" d'une mesure a l'autre est une autre alerte : `resolved` puis `raised`.
  Sans changement de niveau, l'alerte active est seulement mise a jour
  (valeur, horodatage), sans evenement.
- **Acquittement** : `POST /api/alerts/<id>/acknowledge` avec
  `{ "by": "<nom>" }` (nom optionnel) marque l'alerte active comme acquittee
  (`acknowledged_by`, `acknowledged_ms`) jusqu'a sa resolution, escalade
  comprise ; une nouvelle alerte sur le meme capteur repart non acquittee.
  `404` si aucune alerte active ne porte cet id, `409` si elle est deja
  acquittee. L'acquittement ne change ni la severite ni la resolution, qui
  restent decidees par les mesures.
- **Replay : etat reconstruit, sans evenement** : les records rejoues
  (prechauffage, ou rattrapage anterieur de plus de 5 minutes au demarrage,
  `replay=True`) mettent a jour l'etat des capteurs mais ne produisent aucun
  evenement. Apres un redemarrage, les alertes actives sont donc
  reconstruites a partir de l'historique (debut compris, alertes maintenues
  par l'hysteresis aussi) au lieu d'etre declenchees de nouveau ; un
  rattrapage de plusieurs jours n'annonce pas d'alertes perimees. Si ces
  records changent les alertes actives, les clients WebSocket recoivent un
  `snapshot` (re-synchronisation) ; rien n'est historise ni journalise.
- **Idempotence** : chaque record n'est evalue qu'une fois, dans l'ordre de
  sa partition : un record dont l'offset ne depasse pas le plus haut deja
  evalue sur sa partition (relecture Kafka, suiveur puis consommateur)
  est ignore. L'ordre des offsets fait foi dans une partition : un
  horodatage qui recule ou un record date du futur ne fige jamais un
  capteur. Seule une mesure arrivee par une autre partition et plus
  ancienne que la derniere evaluee pour le capteur est ignoree. Les valeurs
  non numeriques (chaine, `null`) et les topics sans regle sont ignores.
- Chaque evenement est journalise : `WARNING` pour `raised` / `escalated`,
  `INFO` pour `deescalated` / `resolved`.

**Contrat de l'API** :

```text
Alert      { id: "<topic>|<node_id>", topic, node_id, severity: "warning"|"critical",
             direction: "above"|"below", threshold, hysteresis (de la regle
             responsable), value, unit (peut etre ""),
             location (zone.label, sinon space.label, sinon ""),
             since_ms (debut de l'alerte, horodatage de la mesure),
             updated_ms (derniere mesure evaluee),
             message (ex. "CO2 au-dessus de 1 000 ppm (1 120 ppm)"),
             acknowledged_by ("" si non acquittee), acknowledged_ms (null si non acquittee) }
AlertEvent { kind: "raised"|"escalated"|"deescalated"|"resolved"|"acknowledged", at_ms, alert }
AlertRule  { severity, direction, threshold, hysteresis }
```

- `GET /api/alerts` -> `{ enabled, active: [Alert] (critical d'abord, puis du
  plus ancien au plus recent), recent: [AlertEvent] (le plus recent d'abord,
  200 au plus), rules: { "<topic>": [AlertRule] } }`.
- `ws://.../ws/alerts` -> a la connexion `{ "type": "snapshot", "active":
  [Alert] }`, puis `{ "type": "event", "event": AlertEvent }` pour chaque
  evenement. Alertes desactivees : snapshot vide, la connexion reste ouverte.
  Un `snapshot` peut aussi arriver en cours de flux (re-synchronisation). Un
  client trop lent (file pleine) ne perd pas un evenement isole, qui
  fausserait sa liste d'alertes : ses messages en attente sont remplaces par
  un `snapshot` de l'etat courant.
- Pour `resolved`, `alert` est l'etat juste avant la resolution (message
  compris) : seules `value` et `updated_ms` sont celles de la mesure qui
  resout. Le dashboard compose lui-meme le texte de retour a la normale
  (ex. "CO2 de nouveau sous 1 000 ppm (940 ppm)") a partir de `threshold`,
  `direction` et `value`.
- `message` est un texte indicatif en francais, destine aux journaux et aux
  clients de l'API (libelle du topic, virgule decimale, une decimale au plus,
  egalites arrondies en s'eloignant de zero comme `Intl.NumberFormat`, espace
  insecable U+00A0 pour les milliers et espace fine insecable U+202F avant
  l'unite, vrai signe moins U+2212). La valeur garde assez de decimales (3 au
  plus) pour ne jamais s'ecrire comme le seuil : "au-dessus de 26 °C
  (26,04 °C)". Les vues du dashboard appliquent le meme formatage, avec les
  decimales de chaque topic (`formatting.METRICS`).

### Dashboard (jumeau numerique)

Le `DashboardService` (`app/services/dashboard_service.py`) est un observateur
du bus : il alimente le jumeau numerique (`data_processing/digital_twin.py`,
dernier etat de chaque capteur, situe dans sa piece : `metadata.zone`, sinon
`metadata.space`, avec `storey` et `building` ; points bruts des dernieres
24 h et agregats horaires -- nombre, somme, min, max -- des 30 derniers
jours, en memoire bornee) et pousse aux clients de `/ws/dashboard` des vues
pretes a afficher (`data_processing/dashboard_views.py`, logique pure). Le
frontend n'applique aucune regle : etats, libelles (« Normal », « Warning »,
« Erreur »), nombres formates, seuils, tris, comptes et notifications sont
calcules ici.

Chaque record n'est compte qu'une fois (`records.SeenOffsets` : offsets vus
par topic et partition, en intervalles), quel que soit l'ordre d'arrivee du
suiveur et du consommateur. Au demarrage, le jumeau est recharge depuis
l'archive (voir [Archive SQLite](#archive-sqlite)) : 24 h de points bruts,
30 jours d'agregats horaires, dernier record de chaque capteur et offsets
deja archives ; le graphe sur 30 jours survit donc aux redemarrages.

Protocole de `/ws/dashboard` : le client envoie en JSON les parametres de
l'ecran qu'il affiche, le backend repond aussitot par la vue complete, puis la
renvoie a chaque changement de donnees (regroupe, au plus une fois par
seconde) ; une alerte declenchee ou escaladee arrive en plus comme
notification. `GET /api/dashboard?view=...` rend la meme vue sans abonnement
(memes parametres en query string).

```text
Parametres  { view: "rooms",  room?: <id>,     range?: "15m"|"1h"|"24h" }
            { view: "metric", metric?: <id>,   range?, sort?: "severity"|"room"|"value" }
            { view: "alerts", filter?: "active"|"acknowledged"|"resolved"|"all" }
            { view: "chart",  metric: <id>, sensor: <id>, range?: "24h"|"7d"|"30d",
              from?: <ms>, to?: <ms> (fenetre de zoom, bornee a la plage) }
            (valeur absente ou inconnue : defaut ; premiere piece, premier topic)

Vue         { type: "view", site ("Local A-1540" : metadata.space, sinon le batiment),
              people: { count_text, label, updated_ms } | null (somme des capteurs
              d'occupation, datee de la mesure la plus recente),
              alerts_enabled, alerts_active (non acquittees), ranges: [{ id, label }],
              view, ... }
  rooms     rooms: [{ id, name, floor, status }],
            room: { id, name, floor, building, status, status_label, summary, last_ms,
                    range, sensors: [Tuile] } | null (piece inconnue)
  metric    metrics: [{ id, label }] (onglets, ordre de topics.yaml, sans l'occupation :
                                      elle n'apparait que dans people),
            metric: { id, label, unit, thresholds, summary, counts: [{ status, text }],
                      range, sort, sorts: [{ id, label }], sensors: [Tuile] }
  alerts    filter, filters: [{ id, label, count }], summary,
            alerts: [{ id, key, severity, severity_label, room, metric_label, sensor_id,
                       value_text, threshold_text, since_ms, state, state_label,
                       state_ms, can_ack }]
  chart     chart: { metric, label, unit, sensor_id, room, value_text, status, updated_ms,
                     range, range_label, ranges, overview_label, span: [debut, fin],
                     zoom: [debut, fin] | null, thresholds,
                     series: [[debut de case, moyenne, status, moyenne formatee]]
                       (toute la plage : cases de 10 min sur 24 h, horaires au-dela),
                     stats: { scope: "zoom" | libelle de la plage,
                              min/max: { text, status }, mean: { text },
                              alerts: [{ status, text }] (episodes touchant la fenetre,
                              d'apres les 200 derniers evenements) } | null,
                     csv_url } | null (capteur inconnu)
Tuile       { id, metric, label, unit, room: { id, name, floor }, value_text, status,
              status_label, updated_ms,
              thresholds: [{ severity, direction, value, text, short, label }],
              points: [[t_ms, valeur]] (120 au plus), stats_text ("1 h : min … · max …") }
Toast       { type: "toast", id, severity, severity_label, at_ms, title, value_text, text,
              alert_id, room_id }
```

`status` vaut `normal`, `warning` ou `critical` ; l'etat d'une piece est le
pire de ses capteurs. Une alerte est `active`, `acknowledged` ou `resolved`
(les resolues viennent des 200 derniers evenements). Les capteurs sans lieu
(camera d'occupation : `metadata` sans `zone` ni `space`) sont regroupes sous
la piece `_sans_piece` (« Sans pièce »), absente du menu `rooms` mais rendue
quand elle est demandee par son id. Les unites des payloads sont traduites
pour l'affichage (`C` -> `°C`, `person` -> rien).

### Archive SQLite

`data_storage/history_store.py` archive les mesures dans
`OUTPUT_DIR/history.sqlite` (bibliotheque standard `sqlite3`, journal WAL) :

- `measurement` : chaque mesure numerique datee, cle `(topic, partition,
  offset)` ; un lot relu est ignore (`INSERT OR IGNORE`) ;
- `hourly` : agregats horaires (nombre, somme, min, max) par capteur, cumules
  depuis les lignes reellement inserees ;
- `latest` : dernier record JSON de chaque capteur (lieu, unite, valeur) ;
- `cursor` : dernier offset consomme par partition, numerique ou non.

Le consommateur ecrit un lot par transaction, hors de la boucle asyncio
(`asyncio.to_thread`), et purge au plus une fois par heure ce qui a plus de
30 jours. Au demarrage, le dashboard recharge le jumeau depuis la base et le
consommateur repart de `cursor + 1` sur chaque partition ; sans curseur, il
relit toute la retention Kafka (une douzaine de jours) et la base se
constitue au fil de l'eau. Un curseur sorti de la retention est ramene au
debut (`KAFKA_AUTO_OFFSET_RESET`).

A savoir :

- aucune migration : les anciens `<topic>.jsonl` et `dashboard-history.json`
  du volume ne sont pas relus et peuvent etre supprimes ;
- base corrompue ou illisible : le service refuse de demarrer (trace
  `sqlite3`) ; supprimer `history.sqlite*` et redemarrer ;
- topic recree dans Kafka (offsets repartis de zero) : supprimer la base,
  sinon les anciennes lignes masquent les nouvelles ;
- durabilite : `synchronous=NORMAL` resiste a un plantage du processus ;
  seule une panne de la machine peut perdre les derniers lots, que Kafka
  relivre s'ils n'etaient pas commites ;
- place : environ 1,5 Go pour 30 jours au debit actuel (~8 M de lignes) ;
  WAL suppose un systeme de fichiers local (pas de NFS/SMB).

### Fichiers d'environnement

- `backend/.env.local` : modele versionne sur GitHub, toutes les valeurs vides.
- `backend/.env` : configuration reelle, **non versionnee** (ignoree par
  `.gitignore`).

```bash
cp backend/.env.local backend/.env   # puis renseigner les valeurs
```

Toute valeur laissee vide dans `.env` retombe sur la valeur par defaut du
tableau ci-dessus.

### API temps reel (WebSocket)

Chaque topic a son propre flux WebSocket : un client s'abonne a l'URL du
topic qui l'interesse et recoit chaque message Kafka en JSON des sa
reception (en plus de l'archivage SQLite). A la connexion, les derniers
messages de chaque capteur du topic (`history_per_sensor` du YAML,
100 par defaut) sont rejoues en ordre chronologique, puis le flux continue
en temps reel — les dashboards affichent donc une courbe des l'ouverture
pour tous les capteurs, meme les plus lents.

| Endpoint | Description |
|---|---|
| `ws://localhost:8000/ws/<topic>` | Flux temps reel du topic (ex. `/ws/gridd.obs.environmental.temperature`) |
| `ws://localhost:8000/ws/alerts` | Alertes : snapshot des alertes actives, puis chaque evenement (voir [Alertes](#alertes)) |
| `ws://localhost:8000/ws/dashboard` | Vues du jumeau numerique et notifications (voir [Dashboard](#dashboard-jumeau-numerique)) |
| `GET http://localhost:8000/api/topics` | Liste des topics et l'URL WebSocket de chacun |
| `GET http://localhost:8000/api/alerts` | Alertes actives, evenements recents et regles par topic |
| `POST http://localhost:8000/api/alerts/<id>/acknowledge` | Acquitte une alerte active (`{ "by": "<nom>" }`) |
| `GET http://localhost:8000/api/dashboard?view=...` | Une vue du dashboard, sans abonnement |
| `GET http://localhost:8000/api/chart.csv?metric=&sensor=&range=&from=&to=` | Cases du graphe (fenetre de zoom comprise) en CSV |
| `GET http://localhost:8000/health` | Etat du service et de chaque consommateur |

Exemple cote frontend (React) :

```js
const ws = new WebSocket("ws://localhost:8000/ws/gridd.obs.environmental.temperature");
ws.onmessage = (e) => {
  const record = JSON.parse(e.data);   // { topic, partition, offset, timestamp_ms, key, value, sensor_id }
  console.log(record.value);           // { node_id, type, value, unit, metadata... }
  console.log(record.sensor_id);       // identite du capteur, la meme que le node_id des alertes
};
```

### Deploiement Docker

Depuis la racine du projet (le flag `--env-file` est necessaire pour que
compose interpole `KAFKA_SSL_CA_HOST_PATH` dans le montage du certificat) :

```bash
docker compose --env-file backend/.env up -d --build
docker logs -f gridd-kafka-consumer
```

Le certificat CA de l'hote (`KAFKA_SSL_CA_HOST_PATH`) est monte en lecture
seule dans le conteneur au chemin `KAFKA_SSL_CA_LOCATION`, lu par le service.

Le volume `gridd-data` (`OUTPUT_DIR`) contient l'archive `history.sqlite` et
ses fichiers `-wal`/`-shm` ; il survit aux redeploiements. Les anciens
`*.jsonl` et `dashboard-history.json` qui s'y trouvent peuvent etre
supprimes.

### Execution locale (sans Docker)

```bash
cd backend
pip install -r requirements.txt
KAFKA_SSL_CA_LOCATION=/chemin/vers/gridd-kafka-ca.crt python -m app.main
```

L'arret se fait proprement sur `SIGINT`/`SIGTERM` : chaque consommateur
commite ses offsets apres chaque lot traite, puis se ferme ; un lot
interrompu est relu au redemarrage.

### Tests

Tests unitaires (pytest) dans `backend/tests/` : bus de records (patron
Observateur), hub WebSocket, consommateur, suiveur temps reel, archive
SQLite, configuration (topics et alertes), evaluation des regles d'alerte, service
d'alertes (acquittement compris), jumeau numerique, vues et service du
dashboard, couche service, composition root et API. Kafka est simule,
aucun broker n'est necessaire.

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
# avec couverture (comme la CI)
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=90
```

La CI GitHub Actions (`.github/workflows/backend-tests.yml` a la racine du
depot) lance ces tests a chaque push sur `main` et a chaque pull request
touchant `labo0/backend/` ; elle echoue si un test casse ou si la couverture
passe sous 90 %.
