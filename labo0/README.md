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

### Topics par defaut

Suivant la convention `gridd.<data_category>.<domain>.<data_type>` :

- `gridd.obs.environmental.temperature`
- `gridd.obs.environmental.humidity`
- `gridd.obs.environmental.co2`
- `gridd.obs.acoustic.sound_level`
- `gridd.obs.occupancy.count`

Surchargables via `KAFKA_TOPICS` (liste separee par des virgules).

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
| `KAFKA_TOPICS` | topics gridd ci-dessus | Topics a consommer |
| `KAFKA_GROUP_ID_PREFIX` | `gridd-consumer` | Prefixe du `group.id` par topic |
| `KAFKA_AUTO_OFFSET_RESET` | `earliest` | Position initiale sans offset commite |
| `OUTPUT_DIR` | `/var/lib/gridd/data` | Repertoire des fichiers JSONL |
| `TOPICS_CONFIG` | `config/topics.yaml` | Fichier YAML des topics et de leurs historiques |
| `HISTORY_PER_SENSOR` | `100` | Defaut d'historique par capteur quand le YAML ne le fixe pas |
| `WARMUP_MESSAGES` | `1000` | Defaut de prechauffage quand le YAML ne le fixe pas |

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
du topic / nb de partitions`, arrondi au-dessus. Si le fichier est absent, le
service retombe sur `KAFKA_TOPICS` et les defauts d'environnement.

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
messages de chaque capteur du topic (`HISTORY_PER_SENSOR` par capteur,
100 par defaut) sont rejoues en ordre chronologique, puis le flux continue
en temps reel — les dashboards affichent donc une courbe des l'ouverture
pour tous les capteurs, meme les plus lents.

| Endpoint | Description |
|---|---|
| `ws://localhost:8000/ws/<topic>` | Flux temps reel du topic (ex. `/ws/gridd.obs.environmental.temperature`) |
| `GET http://localhost:8000/api/topics` | Liste des topics et l'URL WebSocket de chacun |
| `GET http://localhost:8000/health` | Etat du service et de chaque consommateur |

Exemple cote frontend (React) :

```js
const ws = new WebSocket("ws://localhost:8000/ws/gridd.obs.environmental.temperature");
ws.onmessage = (e) => {
  const record = JSON.parse(e.data);   // { topic, partition, offset, timestamp_ms, key, value }
  console.log(record.value);           // { node_id, type, value, unit, metadata... }
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
