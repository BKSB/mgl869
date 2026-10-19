# Projet gridd — labo0

- `backend/` : service Python qui consomme les topics Kafka du cluster gridd.
- `frontend/` : dashboard Vite + React (selection du topic, donnees par capteur).
- `docker-compose.yml` : orchestration des services.

## Frontend : dashboard temps reel

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
```

Le dashboard charge la liste des topics (`GET /api/topics`), s'abonne au flux
WebSocket du topic selectionne et affiche une carte par capteur (`node_id`) :
derniere valeur, zone, et courbe des 120 derniers points. Le proxy Vite
(`vite.config.ts`) redirige `/api` et `/ws` vers le backend — pas de CORS a
gerer en dev.

## Backend : consommateur Kafka

Service Python 100 % asyncio (aiokafka) qui se connecte au cluster Kafka en
SASL_SSL (authentification SCRAM, verification du broker par certificat CA)
et consomme **chaque topic separement** : une tache asyncio et un
consommateur dedies par topic, chacun avec son propre `group.id` et ses
propres offsets. Consommateurs et serveur WebSocket partagent la meme boucle
d'evenements. Les messages de chaque topic sont ecrits dans un fichier JSONL
distinct (`<topic>.jsonl`).

### Architecture : patron Observateur

L'acquisition (consommateurs Kafka, prechauffage d'historique) ne connait
qu'un **bus de records** (`app/data_management/record_bus.py`), le Sujet du
patron Observateur : chaque record lui est publie, et il le transmet a tous
les observateurs inscrits, un par un, dans l'ordre d'inscription. Le hub
WebSocket est le premier observateur, le service d'alertes (voir
[Alertes](#alertes)) le deuxieme ; un futur service (registre des capteurs,
historique en base, qualite des donnees) devient un observateur de plus,
inscrit dans `app/main.py`, sans toucher a l'acquisition.

Contrat d'un observateur (protocole `RecordObserver`) :

- une methode `async def on_record(self, topic, record, *, replay)`, appelee
  dans la boucle asyncio : elle doit etre **rapide**, ou deleguer le travail
  lent ou bloquant (`asyncio.to_thread`, file traitee par une tache dediee),
  car elle retarde les observateurs suivants et le commit ;
- **idempotente** : la livraison est "au moins une fois" et le prechauffage
  peut relire des messages deja vus (un record est identifie par `topic`,
  `partition`, `offset`) ;
- `replay=True` signale un record relu au demarrage (prechauffage) ou
  anterieur de plus de 5 minutes au demarrage du service (rattrapage d'un
  arret prolonge, ou de toute la retention quand le groupe n'a pas d'offset
  commite) : il sert a reconstruire un etat (historique, registre, alertes
  actives), mais aucun evenement ne doit en sortir (ni notification, ni
  annonce). Le hub traite les deux de la meme facon.

Garanties :

- **au moins une fois** : l'offset n'est commite qu'apres la notification de
  tous les observateurs ; un arret pendant le traitement fait relire le
  message au redemarrage ;
- **isolation des pannes** : l'exception d'un observateur est journalisee
  (classe, topic, partition, offset) et n'empeche ni les observateurs
  suivants, ni la diffusion WebSocket, ni le commit. Le record n'est pas
  renvoye a l'observateur en echec : s'il ne doit rien perdre, il gere ses
  propres reprises. Une annulation (arret du service) n'est jamais avalee.

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
bus.subscribe(alerts)            # service d'alertes
bus.subscribe(SensorRegistry())  # nouvel observateur, acquisition inchangee
```

Le `StreamingService` recoit ce bus (`StreamingService(settings, hub, bus)`)
et y inscrit lui-meme son hub s'il ne l'est pas deja : ses abonnements
WebSocket en dependent. Les tests de l'API utilisent le meme `create_bus`.

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
| `KAFKA_AUTO_OFFSET_RESET` | `earliest` | Position initiale sans offset commite |
| `OUTPUT_DIR` | `/var/lib/gridd/data` | Repertoire des fichiers JSONL |
| `TOPICS_CONFIG` | `config/topics.yaml` | Fichier YAML des topics et de leurs historiques |
| `ALERTS_CONFIG` | `config/alerts.yaml` | Fichier YAML des regles d'alerte (absent : alertes desactivees) |

### Configuration des topics (`backend/config/topics.yaml`)

Les topics consommes et leurs reglages se definissent dans un YAML, monte
dans le conteneur (modifiable sans rebuild ; un redemarrage suffit) :

```yaml
defaults:
  history_per_sensor: 100   # messages conserves/rejoues par capteur
  warmup_messages: 1000     # relus par partition au demarrage

topics:
  gridd.obs.environmental.temperature: {}      # prend les defauts
  gridd.obs.acoustic.sound_level:
    history_per_sensor: 1800   # publie toutes les 6 s -> ~3 h d'historique
    warmup_messages: 8000      # 4 capteurs x 1800 sur 1 partition
```

`warmup_messages` se dimensionne ainsi : `history_per_sensor x nb de capteurs
du topic / nb de partitions`, arrondi au-dessus. `history_per_sensor` vaut
100 s'il n'est fixe ni sur le topic ni dans `defaults`. Le fichier est
obligatoire : s'il est absent, ne definit aucun topic ou contient une cle
dupliquee, le service refuse de demarrer.

### Alertes

Le service d'alertes (`app/services/alert_service.py`) est un observateur du
bus : il evalue chaque mesure temps reel contre les regles de son topic, tient
la liste des alertes actives (une au plus par capteur et par topic) et
diffuse chaque changement de niveau. L'evaluation (seuils, hysteresis,
transitions, messages) est une logique pure, testee isolement, dans
`app/data_management/data_processing/alert_rules.py`.

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
  critical -> warning `deescalated` ; X -> aucun `resolved`. Un passage direct
  de "trop haut" a "trop bas" d'une mesure a l'autre est une autre alerte :
  `resolved` puis `raised`. Sans changement de niveau, l'alerte active est
  seulement mise a jour (valeur, horodatage), sans evenement.
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
  evalue sur sa partition (relecture Kafka, prechauffage puis consommateur)
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
             message (ex. "CO2 au-dessus de 1 000 ppm (1 120 ppm)") }
AlertEvent { kind: "raised"|"escalated"|"deescalated"|"resolved", at_ms, alert }
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
  (26,04 °C)". Le dashboard compose ses propres textes a partir des champs
  structures, avec les decimales de chaque topic.

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
reception (en plus de l'archivage JSONL). A la connexion, les derniers
messages de chaque capteur du topic (`history_per_sensor` du YAML,
100 par defaut) sont rejoues en ordre chronologique, puis le flux continue
en temps reel — les dashboards affichent donc une courbe des l'ouverture
pour tous les capteurs, meme les plus lents.

| Endpoint | Description |
|---|---|
| `ws://localhost:8000/ws/<topic>` | Flux temps reel du topic (ex. `/ws/gridd.obs.environmental.temperature`) |
| `ws://localhost:8000/ws/alerts` | Alertes : snapshot des alertes actives, puis chaque evenement (voir [Alertes](#alertes)) |
| `GET http://localhost:8000/api/topics` | Liste des topics et l'URL WebSocket de chacun |
| `GET http://localhost:8000/api/alerts` | Alertes actives, evenements recents et regles par topic |
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

### Execution locale (sans Docker)

```bash
cd backend
pip install -r requirements.txt
KAFKA_SSL_CA_LOCATION=/chemin/vers/gridd-kafka-ca.crt python -m app.main
```

L'arret se fait proprement sur `SIGINT`/`SIGTERM` : chaque consommateur
commit ses offsets apres traitement de chaque message, puis se ferme.

### Tests

Tests unitaires (pytest) dans `backend/tests/` : bus de records (patron
Observateur), hub WebSocket, consommateur, prechauffage d'historique,
configuration (topics et alertes), evaluation des regles d'alerte, service
d'alertes, couche service, composition root et API. Kafka est simule,
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
