# Service consommateur Kafka gridd

Service Python qui se connecte a un cluster Kafka en SSL (verification du
broker par certificat CA) et consomme **chaque topic separement** : un thread
et un consommateur dedies par topic, chacun avec son propre `group.id` et ses
propres offsets. Les messages de chaque topic sont ecrits dans un fichier
JSONL distinct (`<topic>.jsonl`).

## Topics par defaut

Suivant la convention `gridd.<data_category>.<domain>.<data_type>` :

- `gridd.obs.environmental.temperature`
- `gridd.obs.acoustic.sound_level`
- `gridd.derived.environmental.thermal_comfort`
- `gridd.derived.occupancy.estimated_count`
- `gridd.alert.environmental.high_co2`
- `gridd.alert.acoustic.high_sound_level`

Surchargables via `KAFKA_TOPICS` (liste separee par des virgules).

## Configuration (variables d'environnement)

| Variable | Defaut | Description |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9093` | Bootstrap server (`hote:port,...`) |
| `KAFKA_SECURITY_PROTOCOL` | `SASL_SSL` | `SASL_SSL`, `SSL` ou `PLAINTEXT` |
| `KAFKA_SASL_MECHANISM` | `SCRAM-SHA-512` | `SCRAM-SHA-512`, `SCRAM-SHA-256` ou `PLAIN` |
| `KAFKA_USERNAME` | — | Kafka username (requis en SASL) |
| `KAFKA_PASSWORD` | — | Kafka password (requis en SASL) |
| `KAFKA_SSL_CA_HOST_PATH` | — | CA certificate : chemin sur l'hote (monte en volume) |
| `KAFKA_SSL_CA_LOCATION` | `/etc/gridd/kafka/gridd-kafka-ca.crt` | CA certificate : chemin dans le conteneur |
| `KAFKA_TOPICS` | topics gridd ci-dessus | Topics a consommer |
| `KAFKA_GROUP_ID_PREFIX` | `gridd-consumer` | Prefixe du `group.id` par topic |
| `KAFKA_AUTO_OFFSET_RESET` | `earliest` | Position initiale sans offset commite |
| `OUTPUT_DIR` | `/var/lib/gridd/data` | Repertoire des fichiers JSONL |

## Fichiers d'environnement

- `.env.local` : modele versionne sur GitHub, toutes les valeurs vides.
- `.env` : configuration reelle, **non versionnee** (ignoree par `.gitignore`),
  chargee automatiquement par `docker compose` (`env_file`).

```bash
cp .env.local .env   # puis renseigner les valeurs
```

Toute valeur laissee vide dans `.env` retombe sur la valeur par defaut du
tableau ci-dessus.

## Deploiement Docker

Le chemin du certificat CA sur l'hote est defini par
`KAFKA_SSL_CA_HOST_PATH` dans le `.env` ; docker-compose le monte en lecture
seule dans le conteneur au chemin `KAFKA_SSL_CA_LOCATION`
(`/etc/gridd/kafka/gridd-kafka-ca.crt` par defaut), lu par le service.

```bash
docker compose up -d --build
docker logs -f gridd-kafka-consumer
```

Ou sans compose :

```bash
docker build -t gridd-kafka-consumer .
docker run -d --name gridd-kafka-consumer --env-file .env \
  -v /chemin/hote/gridd-kafka-ca.crt:/etc/gridd/kafka/gridd-kafka-ca.crt:ro \
  gridd-kafka-consumer
```

## Execution locale (sans Docker)

```bash
pip install -r requirements.txt
KAFKA_BOOTSTRAP_SERVERS=localhost:9093 \
KAFKA_SSL_CA_LOCATION=/chemin/vers/gridd-kafka-ca.crt \
python -m app.main
```

L'arret se fait proprement sur `SIGINT`/`SIGTERM` : chaque consommateur
commit ses offsets apres traitement de chaque message, puis se ferme.


