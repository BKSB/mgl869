# gridd — Dashboard capteurs

Console temps réel des capteurs IoT du campus (température, humidité, CO₂, niveau sonore, occupation), alimentée par le service consommateur Kafka `gridd-kafka-consumer`.

## Prérequis

- Node 22 (voir `Dockerfile`)
- Le backend qui expose `/api/topics`, `/health`, `/api/alerts`, `/ws/alerts` et `/ws/<topic>` sur `http://localhost:8000` (en dev, Vite relaie ces routes ; en prod, nginx)

## Démarrer

```bash
npm ci            # dépendances (une seule police bundlée : @fontsource-variable/inter)
npm run dev       # http://localhost:5173, proxy /api, /health et /ws vers :8000
npm run build     # tsc -b && vite build -> dist/
npm run lint      # oxlint
```

Docker : l'image construit `dist/` puis le sert avec nginx (`nginx.conf` relaie `/api/`, `/health` et `/ws/` vers le service backend du `docker-compose`, et met en cache long les assets hachés).

## Architecture (`src/`)

| Dossier | Rôle |
|---|---|
| `api/` | Appels réseau : `fetchTopics`, `fetchHealth` et `fetchAlerts` (un seul `getJson`, content-type vérifié), `wsUrl` (topics et alertes) |
| `hooks/` | `useTopicStream` (un WebSocket par topic, état étiqueté par topic, capteurs groupés par le `sensor_id` du backend, lots intégrés toutes les 500 ms), `useSeriesStats` (fenêtre, stats, sparkline, fusion k-voies, mémoïsés), `useHealth` (polling 30 s, délai de 10 s par requête, pause onglet caché), `useAlerts` (GET puis WebSocket des alertes, reconnexion 3 s), `useNow` (ticker partagé 5 s), `useTheme`, `useMediaQuery`, `useKeyboardShortcuts` |
| `lib/` | Fonctions pures : `stats` (fenêtre ancrée sur l'horloge des capteurs, `medianInterval`, `freshness`), `format` (fr-CA : virgule décimale, espace fine, `HH:mm:ss`), `ranges`, `metrics` (libellé court, polarité, décimales par topic), `alerts` (tri, application d'un événement, textes des alertes), `stream` (délai de reconnexion, états d'attente du flux), `focus` (focus conservé quand une action démonte le bouton focalisé), `csv`, `labels`, `sensors` |
| `components/` | `AppBar`, `TopicTabs`, `FilterBar` (plage, capteur, vue), `StatTileRow`/`StatTile`, `ChartCard`, `TopicChart` + `ChartTooltip`, `LegendTable`, `DataTable`, `AlertsChip` + `AlertsPanel`, `SeverityIcon`, badges d'état |

Un seul WebSocket par topic, les stats sont dérivées et mémoïsées côté client. Une coupure reste affichée (« Déconnecté · reconnexion toutes les 3 s », bandeau de la carte) pendant toutes les tentatives, sans clignoter ni être ré-annoncée à chaque essai ; au chargement, l'état est « Connexion… », jamais une fausse coupure. `/health` est interrogé toutes les 30 s pour l'état du service et de chaque consommateur Kafka (point sur l'onglet du topic concerné) ; une requête sans réponse après 10 s compte comme un échec (« injoignable » après deux échecs).

## Raccourcis clavier

| Touche | Action |
|---|---|
| `1` à `4` | Plage : 15 min, 1 h, 3 h, tout l'historique |
| `v` | Basculer graphe / tableau |
| `Échap` | Revenir à tous les capteurs |

Les raccourcis sont inactifs dans les champs de saisie et le `<select>`. Le graphe est navigable au clavier (focus puis flèches : le curseur et l'infobulle suivent). Quand une action retire l'élément focalisé (raccourci, « Afficher 300 lignes de plus » sur la dernière page, « Afficher tout », « Réessayer »), le focus passe au bouton coché de la barre de filtres, au tableau ou au contenu principal, jamais à `<body>`.

## Thème

Bascule Système / Clair / Sombre dans la barre d'application, persistée dans `localStorage` (`gridd.theme`) et appliquée par un script inline avant le premier rendu (aucun flash). En mode Système, le thème suit la préférence de l'OS en direct ; `meta[name=theme-color]` est tenue à jour.

## Alertes

Les règles (seuils, hystérésis) vivent côté backend dans `backend/config/alerts.yaml` ; le dashboard ne fait qu'afficher leur état.

- **Données** : `useAlerts` lit `GET /api/alerts` (alertes actives, 200 derniers événements, règles par topic), puis s'abonne à `/ws/alerts` : un `snapshot` des alertes actives à la connexion (et à chaque re-synchronisation), puis un message par événement (`raised`, `escalated`, `deescalated`, `resolved`). Coupure : l'état reste « interrompu » (dernier état connu, coche neutre) pendant les tentatives, toutes les 3 s, jusqu'à une réponse fraîche du backend ; le snapshot re-synchronise ensuite la liste. Sans fichier de règles (`enabled: false`), aucun WebSocket n'est ouvert, la puce affiche « Alertes désactivées » et l'état est revérifié toutes les 30 s (règles ajoutées puis backend redémarré : pas besoin de recharger la page).
- **Textes** : le dashboard compose tous les textes d'alerte à partir des champs structurés (`threshold`, `hysteresis`, `value`, `direction`), avec les libellés et les décimales de chaque topic, comme les tiles ; la valeur garde au besoin des décimales de plus pour ne jamais s'écrire comme le seuil (« Humidité au-dessus de 60 % (60,4 %) »). Le `message` du backend sert aux journaux et aux autres clients de l'API.
- **Puce de l'app bar** : « Aucune alerte » (coche), « Alertes : n » (triangle ambre si seulement des avertissements, octogone rouge dès qu'une alerte est critique). C'est un bouton qui ouvre un panneau non modal : alertes actives (critiques d'abord) avec lieu, texte et durée, bouton « Voir » qui sélectionne le topic et isole le capteur, puis les 10 derniers événements (pour une résolution, le panneau compose « CO₂ de nouveau sous 1 000 ppm (940 ppm) » à partir du seuil et de la valeur). Fermeture par `Échap` (qui ne réinitialise alors pas le filtre capteur), clic extérieur ou bouton Fermer ; chaque nouvel événement est annoncé aux lecteurs d'écran.
- **Topic affiché** : la tile d'un capteur en alerte prend une bordure couleur de statut et une icône de sévérité (message au survol), la ligne de légende porte la même icône, et l'onglet d'un topic qui a des alertes actives porte un indicateur. Le graphe trace une ligne pointillée par règle dont le seuil tombe dans l'échelle (« Seuil critique 1 500 ppm ») ; l'échelle Y n'est jamais élargie pour montrer un seuil.
- **Accessibilité** : la sévérité n'est jamais portée par la couleur seule (forme de l'icône + libellé visible ou lu) ; le texte reste en encre primaire ou secondaire, seule l'icône porte la couleur de statut. `--status-warning` et `--status-critical` sont réservés aux alertes et aux états.

## Méthode dataviz

- Palette validée (8 slots catégoriels, variantes claires et sombres) ; la couleur suit le capteur (ordre alphabétique des `node_id`), jamais sa position dans le filtre.
- Le texte ne porte jamais une couleur de série ni de statut : identité par clé-ligne, statut par couleur + icône + libellé.
- Lignes 2 px, grille et curseur en hairlines solides, aucune animation sur les données, cadre stable au changement de topic (tiles « — », état « Rejeu de l'historique… »).
- Une seule rangée de filtres (plage d'abord) qui scope tiles, graphe, légende et tableau à l'identique ; vue tableau jumelle avec export CSV (Excel fr-CA).
- Chiffres proportionnels sur les grands nombres, tabulaires dans les colonnes.

## Suites possibles

- `downsampleMinMax` sur les séries longues si un flush dépasse 16 ms au profilage (React Profiler sur « Niveau sonore », plage « Tout »).
- Valeurs des seuils d'alerte (`backend/config/alerts.yaml`, indicatives) à valider par les propriétaires des données.
- Endpoint « dernière valeur par topic » côté backend pour peupler les tiles avant le rejeu de l'historique.
