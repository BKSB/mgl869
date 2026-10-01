FROM python:3.12-slim

# Utilisateur non root
RUN groupadd -r gridd && useradd -r -g gridd gridd

WORKDIR /srv/gridd

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY config/ config/

# Repertoire de sortie des donnees (un fichier JSONL par topic)
RUN mkdir -p /var/lib/gridd/data && chown -R gridd:gridd /var/lib/gridd

USER gridd

# Le certificat CA est monte en volume a l'execution :
#   /etc/gridd/kafka/gridd-kafka-ca.crt
ENV KAFKA_SSL_CA_LOCATION=/etc/gridd/kafka/gridd-kafka-ca.crt

# API HTTP + WebSocket (un flux par topic sur /ws/<topic>)
EXPOSE 8000

ENTRYPOINT ["python", "-m", "app.main"]
