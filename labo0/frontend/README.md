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
| `#/metrics/<id>` | **Par capteur** : un type de capteur dans | type, plage, tri (sévérité, pièce, valeur) |
| `#/alerts` | **Alertes** : table des alertes avec état | filtre (actives, acquittées, résolues, toutes) |
| `#/chart/<métrique>/<capteur>` | **Graphe plein écran** (clic sur une tuile de pièce) : série, seuils, statistiques et alertes de la fenêtre, aperçu avec fenêtre de zoom, export CSV | plage (24 h, 7 j, 30 j), fenêtre de zoom (`from`, `to`) |

La barre affiche le local (`site`), le nombre de personnes présentes
(`people`, somme des capteurs d'occupation, avec l'âge de la dernière mesure),
le badge « Alertes » (alertes actives non acquittées) et l'état du WebSocket.
Les notifications (toasts) arrivent du backend pour chaque alerte déclenchée
ou escaladée. L'occupation n'a ni pièce dans le menu (la caméra n'a pas de
lieu) ni onglet dans Par capteur : elle n'existe que dans l'en-tête.

## Fonctionnement

- `useDashboard.ts` ouvre un seul WebSocket (`/ws/dashboard`), lui envoie les
  paramètres de l'écran courant à chaque changement (et à chaque reconnexion,
  toutes les 3 s) et remplace l'état affiché par chaque vue reçue. Le backend
  renvoie la vue complète : pièces, états, libellés, seuils, nombres formatés,
  tris, comptes (voir le README du projet, section « Dashboard »).
- Le client ne calcule que le rendu : les heures et dates (`format.ts`,
  fuseau du navigateur), les coordonnées des sparklines et du graphe
  (`Sparkline.tsx`, `TimeChart.tsx`, à partir des points et des seuils
  fournis) et les graduations des axes (`ticks.ts`). Le zoom du graphe
  (glisser sur le graphe, fenêtre de l'aperçu `Overview.tsx`, boutons ±) ne
  fait que filtrer la série affichée ; ses bornes sont envoyées au backend, qui
  renvoie les statistiques et le nombre d'alertes de la fenêtre.
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
| `ticks.ts`, `useWidth.ts` | Graduations « rondes » des axes ; largeur rendue des graphes SVG |
| `components/` | `Header`, `RoomsView`, `MetricView`, `AlertsView`, `ChartView` (+ `TimeChart`, `Overview`), `SensorTile`, `Sparkline`, `Toasts`, badges et contrôles (`StatusBadge.tsx`) |
| `index.css` | Thème sombre (maquettes), aucune ressource externe |
