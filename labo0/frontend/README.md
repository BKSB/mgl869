# gridd — Jumeau numérique

Interface du jumeau numérique des capteurs du campus (pièces, capteurs,
alertes), alimentée par le service `gridd-kafka-consumer`. **Le frontend ne
contient aucune logique métier** : il navigue, envoie ses contrôles au backend
et affiche ce qu'il reçoit.

## Démarrer

```bash
npm ci            # une seule dépendance d'exécution bundlée : @fontsource-variable/inter
npm run dev       # http://localhost:5173, proxy /api, /health et /ws vers :8000
npm run build     # tsc -b && vite build -> dist/
npm run lint      # oxlint
npm test          # vitest : route.ts et format.ts
```

Docker : l'image construit `dist/` puis le sert avec nginx (`nginx.conf`
relaie `/api/`, `/health` et `/ws/` vers le backend du `docker-compose`).

## Écrans

| Route | Écran | Contrôles envoyés au backend |
|---|---|---|
| `#/rooms/<id>` | **Par pièce** : liste des pièces (état, étage), détail de la pièce choisie, une tuile par capteur | pièce, plage (15 min, 1 h, 24 h) |
| `#/metrics/<id>` | **Par capteur** : un type de capteur dans toutes les pièces | type, plage, tri (sévérité, pièce, valeur) |
| `#/alerts` | **Alertes** : table des alertes avec état | filtre (actives, acquittées, résolues, toutes) |

Le badge « Alertes » de la barre compte les alertes actives non acquittées ;
la pastille de droite indique l'état du WebSocket. Les notifications (toasts)
arrivent du backend pour chaque alerte déclenchée ou escaladée.

## Fonctionnement

- `useDashboard.ts` ouvre un seul WebSocket (`/ws/dashboard`), lui envoie les
  paramètres de l'écran courant à chaque changement (et à chaque reconnexion,
  toutes les 3 s) et remplace l'état affiché par chaque vue reçue. Le backend
  renvoie la vue complète : pièces, états, libellés, seuils, nombres formatés,
  tris, comptes (voir le README du projet, section « Dashboard »).
- Le client ne calcule que deux choses : les heures (`format.ts`, fuseau du
  navigateur : `HH:mm:ss`, « il y a 2 s ») et les coordonnées des sparklines
  (`Sparkline.tsx`, à partir des points et des seuils fournis).
- Une seule action : « Acquitter » (`api.ts`, `POST /api/alerts/<id>/acknowledge`).
  Le nom de l'opérateur est demandé une fois puis gardé dans `localStorage`
  (`gridd.operator`). Le backend décide du déclenchement, de la sévérité et de
  la résolution.

## Fichiers (`src/`)

| Fichier | Rôle |
|---|---|
| `App.tsx` | Route (hash), contrôles locaux (plage, tri, filtre), assemblage |
| `route.ts` | `#/rooms/<id>`, `#/metrics/<id>`, `#/alerts` |
| `useDashboard.ts`, `useNow.ts` | WebSocket du dashboard ; horloge des « il y a n s » |
| `types.ts` | Forme des vues et des notifications reçues |
| `components/` | `Header`, `RoomsView`, `MetricView`, `AlertsView`, `SensorTile`, `Sparkline`, `Toasts`, badges et contrôles (`StatusBadge.tsx`) |
| `index.css` | Thème sombre (maquettes), aucune ressource externe |
