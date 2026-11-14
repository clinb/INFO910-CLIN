# Distributed Task Manager

TP d'Introduction DevOps — Master 2 Informatique  
**Benjamin CLIN** — Projet réalisé individuellement

## Présentation

Distributed Task Manager est une petite application permettant de lancer des calculs en arrière-plan. Pour ce TP, le calcul consiste à compter le nombre de nombres premiers inférieurs ou égaux à une valeur `n` (entre 0 et 10 000 000).

L'application repose sur trois composants :

- **API Python (FastAPI)** : reçoit les demandes et permet de consulter les résultats.
- **PostgreSQL** : stocke les tâches, leur état et leur résultat.
- **Workers Python** : récupèrent les tâches en attente et effectuent les calculs.

Les tâches passent par les états `PENDING`, `RUNNING`, `COMPLETED` ou `FAILED`. Plusieurs workers peuvent travailler en parallèle. L'attribution des tâches est gérée avec des transactions PostgreSQL et `FOR UPDATE SKIP LOCKED` pour éviter qu'une même tâche soit récupérée par deux workers.

## Lancement avec Docker Compose

Il faut disposer de Docker et de Docker Compose. Depuis la racine du dépôt :

```powershell
docker compose up -d --build --scale worker=3
```

Cette commande construit l'image de l'application et lance PostgreSQL, l'initialisation de la base, l'API et trois workers.

La documentation interactive de l'API est accessible à l'adresse : **http://127.0.0.1:8001/docs**.

On peut par exemple créer une tâche puis consulter son résultat depuis PowerShell :

```powershell
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/tasks -ContentType 'application/json' -Body '{"n":1000000}'
Invoke-RestMethod -Uri "http://127.0.0.1:8001/tasks/$($task.id)"
```

Le résultat attendu est `78498` une fois le calcul terminé. On peut également suivre les workers avec `docker compose logs worker`.

Pour arrêter l'application sans effacer les données :

```powershell
docker compose down
```

Les données PostgreSQL sont conservées dans un volume Docker. Ne pas ajouter `-v` à la commande d'arrêt si l'on souhaite les conserver.

## Déploiement sur Kubernetes

Le projet contient les manifestes Kubernetes dans le dossier `k8s/`, regroupés avec Kustomize. Ils définissent notamment :

- un **StatefulSet PostgreSQL** avec stockage persistant ;
- un **Job** pour initialiser la base ;
- deux **Deployments** pour l'API et les workers ;
- les **Services**, **ConfigMap** et **Secret** nécessaires.

### Prérequis

Il faut un cluster Kubernetes accessible avec `kubectl`, ainsi qu'une StorageClass par défaut permettant de créer un volume persistant de 1 Gio.

Sur Docker Desktop, on peut utiliser le cluster Kubernetes intégré. Vérifier d'abord qu'il fonctionne :

```powershell
kubectl get nodes
kubectl get storageclass
```

Construire ensuite l'image utilisée par l'API et les workers :

```powershell
docker build -t distributed-task-api:dev .
```

Cette image était directement accessible sur le cluster Docker Desktop utilisé pour le TP. Sur un autre cluster, il faudra la charger dans les nœuds ou la publier dans un registre, puis adapter `k8s/kustomization.yaml` si nécessaire.

### Installation

Depuis la racine du dépôt :

```powershell
kubectl apply -k k8s
kubectl -n dtm rollout status statefulset/postgres --timeout=180s
kubectl -n dtm wait --for=condition=complete job/init-db --timeout=180s
kubectl -n dtm rollout status deployment/api --timeout=180s
kubectl -n dtm rollout status deployment/worker --timeout=180s
kubectl -n dtm get pods,services,pvc,jobs
```

Pour accéder à l'API depuis le PC, ouvrir un terminal et laisser cette commande en cours d'exécution :

```powershell
kubectl -n dtm port-forward service/api 8002:8000
```

La documentation est alors disponible sur **http://127.0.0.1:8002/docs**. Les requêtes présentées plus haut fonctionnent également en remplaçant le port `8001` par `8002`.

### Quelques tests

On peut augmenter le nombre de workers avec :

```powershell
kubectl -n dtm scale deployment/worker --replicas=3
kubectl -n dtm get pods -l app=worker
```

On peut aussi supprimer un pod worker pour voir le Deployment le recréer, ou supprimer `postgres-0` pour vérifier que les tâches restent enregistrées grâce au volume persistant.

Les tests réalisés ont permis de vérifier l'exécution des calculs avec plusieurs workers, le remplacement des pods et la conservation des données après recréation de PostgreSQL.

**Limite connue :** si un worker est interrompu pendant un calcul, la tâche peut rester dans l'état `RUNNING`. Kubernetes recrée le pod, mais la reprise automatique du calcul n'a pas été implémentée.

Pour supprimer les ressources du TP :

```powershell
kubectl delete -k k8s
```

**Attention :** cette suppression inclut le namespace et peut entraîner la perte des volumes et des données associées.

## Organisation du dépôt

- `app/` : API, accès à PostgreSQL, calculs et workers.
- `tests/` : tests applicatifs et test de fonctionnement complet.
- `Dockerfile` et `compose.yaml` : construction et lancement avec Docker.
- `k8s/` : manifestes de déploiement Kubernetes.

Le projet est destiné à un environnement de TP local. Les identifiants de démonstration ne doivent pas être utilisés pour une mise en production ni exposés sur Internet.
