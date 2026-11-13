# Distributed Task Manager

TP Introduction DevOps, Master 2 Informatique.

Auteur : **Benjamin CLIN**. Projet realise individuellement.

## Demarrage rapide avec Docker Compose

Prerequis : Docker avec moteur Linux et plugin Docker Compose.
Depuis la racine du projet :

```powershell
docker compose up -d --build --scale worker=3
docker compose ps -a
```

API et documentation : http://127.0.0.1:8001/docs.
Disponibilite : http://127.0.0.1:8001/ready.
Le port 8001 evite le conflit avec l'ancien conteneur manuel `dtm-api` sur 8000.
Compose utilise son propre reseau et le volume `dtm-compose_pgdata`, sans reutiliser
ni supprimer le volume manuel `dtm-pgdata`.

La pile comprend PostgreSQL, une initialisation ponctuelle du schema, l'API et
les workers. `init-db` termine avec le code 0 : c'est normal. PostgreSQL doit etre
sain avant cette initialisation ; API et workers attendent sa reussite.

L'API et le worker utilisent la meme image : le worker remplace sa commande par
`python -m app.worker`. Il ne necessite ni serveur HTTP ni Service Kubernetes.
Le port affiche pour le worker dans Docker provient du `EXPOSE` de l'image ; cela
ne signifie pas qu'un serveur y ecoute ou que le port est publie sur Windows.

```powershell
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/tasks -ContentType 'application/json' -Body '{"n":1000000}'
Invoke-RestMethod -Uri "http://127.0.0.1:8001/tasks/$($task.id)"
docker compose logs --tail 30 worker
```

Configuration facultative dans un fichier `.env` local, jamais committe :

```dotenv
API_PORT=8001
POSTGRES_PASSWORD=tp-local-only
```

Le mot de passe par defaut est public et reserve au TP local. Ne pas utiliser sur
Internet. Le changer apres l'initialisation du volume ne modifie pas le mot de
passe du role PostgreSQL existant. L'API utilise les variables libpq `PGHOST`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD` ; un eventuel `DATABASE_URL` est prioritaire.
Ces variables separent les valeurs et evitent d'encoder un mot de passe dans une URL.

Arreter en conservant les donnees :

```powershell
docker compose down
```

Ne pas ajouter `--volumes` sauf pour effacer volontairement les donnees du TP.
Les anciens conteneurs manuels `dtm-api` et `dtm-db` sont independants de Compose.

## Fonctionnement

FastAPI enregistre des demandes de comptage des nombres premiers inferieurs ou
egaux a `n`. PostgreSQL conserve les taches et leurs resultats. Des workers Python
independants interrogent la base et executent les calculs. L'API ne calcule pas.

Etats : `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`.
La borne `n` doit etre un entier entre 0 et 10 000 000 inclus.

L'attribution utilise `SELECT ... FOR UPDATE SKIP LOCKED` dans une requete qui
passe aussi la tache a `RUNNING`. Le verrou et la mise a jour sont atomiques : les
autres workers ignorent les lignes verrouillees. La transaction se termine avant
le calcul pour ne pas garder un verrou pendant son execution.

Limite volontaire : une interruption du worker ou une panne de la base apres
l'attribution peut laisser une tache `RUNNING`. Kubernetes peut remplacer le
worker mais ne reprend pas automatiquement le calcul. Pas de heartbeat ni de bail.

## Organisation

- `app/api.py` : API REST et validation.
- `app/db.py`, `app/schema.sql` : connexions, schema et attribution atomique.
- `app/compute.py` : crible d'Eratosthene.
- `app/worker.py` : polling, calcul et enregistrement du resultat.
- `tests/test_app.py` : tests unitaires et integration PostgreSQL optionnelle.
- `tests/smoke.py` : verification HTTP avec de vrais workers.
- `Dockerfile`, `compose.yaml` : image partagee et execution locale multi-conteneurs.
- `k8s/` : ressources Kubernetes assemblees avec Kustomize.

## Installation locale Windows

Prerequis : Python 3.11 ou plus et une base PostgreSQL accessible.
Depuis la racine du projet, dans PowerShell :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Dans chaque terminal applicatif, definir la connexion avec les valeurs de votre
base. Le mot de passe ci-dessous est uniquement un exemple local :

```powershell
$env:DATABASE_URL = 'postgresql://tasks:local-example@localhost:5432/tasks'
```

Ne jamais committer de vrais identifiants. Les caracteres reserves dans une URL
doivent etre encodes. Aucun fichier `.env` n'est charge automatiquement.

Initialiser le schema une fois, avant de lancer l'API et les workers :

```powershell
.\.venv\Scripts\python.exe -m app.db
```

Cette commande cree les objets absents ; ce n'est pas un outil de migration.
Dans un terminal, lancer l'API :

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Dans un autre terminal ayant aussi `DATABASE_URL`, lancer un worker :

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Pour plusieurs workers, lancer cette commande dans plusieurs terminaux. Chaque
processus obtient un identifiant distinct. `WORKER_ID` permet de le choisir et
`POLL_INTERVAL` regle l'attente en secondes lorsqu'aucune tache n'est disponible
(defaut : 1, intervalle autorise : ]0, 60]). Les erreurs de connexion du worker
sont journalisees et provoquent une nouvelle tentative apres cette attente.
Ctrl+C demande l'arret apres le calcul en cours.

## Utilisation

Documentation interactive : http://127.0.0.1:8000/docs.

```powershell
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/tasks -ContentType 'application/json' -Body '{"n":1000000}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/tasks/$($task.id)"
Invoke-RestMethod -Uri http://127.0.0.1:8000/tasks
```

Le resultat attendu pour 1 000 000 est `78498`. Le resultat reste `null` tant que
le calcul n'est pas termine. `GET /tasks?limit=100` retourne les dernieres taches
(100 par defaut, 1 000 maximum).

`GET /health` verifie que l'API repond, sans interroger PostgreSQL.
`GET /ready` verifie que la base et la table sont accessibles, sinon retourne 503.
Les autres endpoints necessitent une base disponible. Pas d'authentification :
application de TP destinee a un environnement local, pas a une exposition publique.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

Les tests PostgreSQL sont ignores sans `TEST_DATABASE_URL`. Pour les activer,
specifier une base de test accessible dont l'utilisateur peut creer des schemas :

```powershell
$env:TEST_DATABASE_URL = 'postgresql://tasks:local-example@localhost:5432/tasks'
.\.venv\Scripts\python.exe -m unittest discover -v
```

Chaque test d'integration cree puis supprime son propre schema aleatoire, sans
modifier les tables applicatives existantes. Les tests couvrent le parcours API,
l'execution concurrente, l'absence de doubles attributions et le statut `FAILED`.

## Verification de bout en bout

Avec la pile Compose demarree et Python local disponible :

```powershell
python -m tests.smoke --min-workers 3
```

Ce test soumet 30 calculs par HTTP, attend au maximum 120 secondes et verifie les
resultats et le nombre de workers distincts. La repartition n'est pas forcement
equitable : les workers prennent les taches disponibles, sans tour de role garanti.
Les taches de demonstration sont conservees en base pour pouvoir les consulter.

Verifier la persistance apres remplacement du conteneur PostgreSQL :

```powershell
docker compose up -d --force-recreate --no-deps db
docker compose ps
Invoke-RestMethod -Uri "http://127.0.0.1:8001/tasks/$($task.id)"
```

Attendre que la base soit saine avant la derniere commande. Le resultat doit etre
identique. Le volume conserve les donnees, ce n'est pas le conteneur qui les conserve.

Modifier le nombre de workers :

```powershell
docker compose up -d --scale worker=1
docker compose up -d --scale worker=3
```

Compose ne fournit pas le controleur de reconciliation de Kubernetes : il ne faut
pas confondre sa politique de redemarrage avec le remplacement automatique d'un pod.

## Deploiement Kubernetes

### Prerequis et image

Un cluster accessible avec `kubectl`, des noeuds Linux et une StorageClass par
defaut capable de fournir le PVC de 1 Gio sont necessaires. Aucun cluster n'est
installe par ce projet. Docker Desktop Kubernetes constitue une option locale :
l'activer dans les reglages Docker Desktop, puis verifier :

```powershell
kubectl config get-contexts
kubectl config use-context docker-desktop
kubectl get nodes
kubectl get storageclass
docker build -t distributed-task-api:dev .
```

Ne selectionner `docker-desktop` que si ce contexte existe. Les noeuds doivent
etre `Ready`. Selon le provisionneur, Kubernetes peut ne pas partager le magasin
d'images de Docker Desktop. Chaque noeud doit pouvoir utiliser notre image.
Sur l'environnement teste (Docker Desktop, mode Kind, Kubernetes v1.36.1),
l'image locale etait directement accessible : aucun registre ni chargement manuel
n'a ete necessaire. Les commandes suivantes sont des alternatives pour un cluster
Kind ou Minikube independant, pas des etapes obligatoires pour Docker Desktop.
Avec un cluster Kind deja configure, charger l'image :

```powershell
kind load docker-image distributed-task-api:dev
```

ou, uniquement pour Minikube :

```powershell
minikube image load distributed-task-api:dev
```

Pour un cluster distant ou un magasin d'images separe, publier l'image dans un
registre accessible aux noeuds. Exemple a adapter a votre propre registre public
ou avec un `imagePullSecret` si prive :

```powershell
docker tag distributed-task-api:dev votre-registre/distributed-task-api:tp1
docker push votre-registre/distributed-task-api:tp1
```

Ajouter alors a `k8s/kustomization.yaml` :

```yaml
images:
  - name: distributed-task-api
    newName: votre-registre/distributed-task-api
    newTag: tp1
```

Utiliser un nouveau tag pour chaque version publiee. Avec `IfNotPresent`,
reconstruire le meme tag ne remplace pas les images deja en cache sur les noeuds.

### Ressources

- Namespace `dtm` : isole les ressources du TP.
- ConfigMap : configuration non sensible de la base et du polling.
- Secret : mot de passe d'exemple, transmis aux processus par environnement.
- StatefulSet PostgreSQL : une instance avec identite stable `postgres-0`.
- PVC genere par `volumeClaimTemplates` : conserve les donnees independamment du pod.
- Service PostgreSQL headless : fournit le DNS interne `postgres` et l'identite reseau du StatefulSet.
- Job `init-db` : initialise le schema, avec nouvelles tentatives si la base n'est pas prete.
- Deployments API et worker : maintiennent le nombre de pods demande.
- Init containers : attendent le schema avant le demarrage applicatif, avec nouvelles tentatives Kubernetes.
- Service API `ClusterIP` : point d'acces stable interne au cluster.
- Probes API : startup et liveness sur `/health`, readiness sur `/ready`.

La liveness ne depend pas de PostgreSQL pour eviter de redemarrer l'API a chaque
panne de base. La readiness la retire du trafic si la base est indisponible.
Pas de probe HTTP artificielle pour le worker : Kubernetes surveille son processus.
Les demandes et limites CPU/memoire sont adaptees au TP, pas a une charge de production.

Le Secret contient **des identifiants publics de demonstration**, pas un vrai
secret de production. Ses deux mots de passe doivent rester identiques. Un Secret
Kubernetes n'est pas automatiquement chiffre dans etcd ; ne pas y committer de
veritables identifiants. Changer ce fichier ne change pas le role d'une base deja
initialisee dans un PVC.

### Installation

Le port local 8002 est reserve ici a Kubernetes ; Compose peut rester sur 8001.
Les deux deploiements possedent des bases et des stockages independants : les
taches de l'un n'apparaissent pas dans l'autre.

```powershell
kubectl kustomize k8s
kubectl apply -k k8s
kubectl -n dtm rollout status statefulset/postgres --timeout=180s
kubectl -n dtm wait --for=condition=complete job/init-db --timeout=180s
kubectl -n dtm rollout status deployment/api --timeout=180s
kubectl -n dtm rollout status deployment/worker --timeout=180s
kubectl -n dtm get pods,services,pvc,jobs
```

`kustomize` assemble les fichiers, sans deployer. `apply -k` cree ou met a jour les
ressources. L'ordre de demarrage est gere par les nouvelles tentatives du Job et
les init containers, pas simplement par l'ordre des fichiers YAML.

Dans un terminal dedie, ouvrir un acces local a l'API :

```powershell
kubectl -n dtm port-forward service/api 8002:8000 --address=127.0.0.1
```

Acces : http://127.0.0.1:8002/docs. `port-forward` reste au premier plan ; Ctrl+C
ferme le tunnel mais ne supprime pas le deploiement. Le Service reste interne.
Un `NodePort` exposerait un port sur les noeuds ; `LoadBalancer` demanderait une
integration de load balancer. Ils ne sont pas necessaires pour ce TP local.

```powershell
python -m tests.smoke --url http://127.0.0.1:8002
```

Pour diagnostiquer un echec :

```powershell
kubectl -n dtm get pods
kubectl -n dtm describe pod NOM_DU_POD
kubectl -n dtm logs job/init-db
kubectl -n dtm logs deployment/api
kubectl -n dtm logs -l app=worker --prefix --tail=30
```

`get` resume l'etat, `describe` affiche notamment les evenements, `logs` affiche
les sorties des processus. Un PVC `Pending` demande de verifier la StorageClass.
`ImagePullBackOff` demande de verifier l'image et son acces depuis les noeuds.
Un init container en echec peut simplement attendre la base ou le schema ; consulter
ses logs avec `kubectl -n dtm logs NOM_DU_POD -c wait-schema`.

### Experiences Kubernetes

Scalabilite :

```powershell
kubectl -n dtm scale deployment/worker --replicas=3
kubectl -n dtm rollout status deployment/worker --timeout=180s
kubectl -n dtm get pods -l app=worker
python -m tests.smoke --url http://127.0.0.1:8002 --min-workers 2
```

La commande `scale` modifie le nombre de replicas demande. Le Deployment cree les
pods manquants. `worker_id` permet de voir qui a traite chaque tache. Un nouvel
`apply -k k8s` remettra les replicas a la valeur du manifeste (1).

Persistance : creer une tache, attendre `COMPLETED`, puis remplacer PostgreSQL :

```powershell
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/tasks -ContentType 'application/json' -Body '{"n":1000000}'
Invoke-RestMethod -Uri "http://127.0.0.1:8002/tasks/$($task.id)"
```

Repeter la consultation jusqu'a `COMPLETED`, puis :

```powershell
kubectl -n dtm delete pod postgres-0
kubectl -n dtm rollout status statefulset/postgres --timeout=180s
kubectl -n dtm get pods,pvc
Invoke-RestMethod -Uri "http://127.0.0.1:8002/tasks/$($task.id)"
```

Verifier ensuite que la meme tache est encore accessible. Le StatefulSet recree
le pod et rattache son PVC. Le service peut etre temporairement indisponible.

Resilience : apres les calculs, choisir un nom retourne par `get pods`, puis :

```powershell
kubectl -n dtm delete pod NOM_DU_POD_WORKER
kubectl -n dtm get pods -l app=worker -w
```

Le Deployment remplace le pod supprime. Ctrl+C arrete uniquement l'observation.
Cette experience ne prouve pas la reprise d'une tache interrompue. Si le worker
est tue avant la sauvegarde, la tache peut rester `RUNNING`. L'arret normal laisse
jusqu'a 60 secondes au worker pour terminer son calcul courant.

### Nettoyage et mises a jour

```powershell
kubectl delete -k k8s
```

**Attention : cette commande supprime aussi le namespace `dtm`, donc ses PVC.**
Les donnees peuvent alors etre detruites selon la politique du stockage. Pour
conserver les donnees, ne pas supprimer le namespace ou les PVC ; on peut reduire
API/worker a zero replicas et supprimer seulement le StatefulSet, dont les PVC
sont conserves par defaut. Ne pas confondre persistance et sauvegarde.

Le Job termine n'est pas relance par un simple `apply`. Si une reinitialisation
du schema est necessaire, supprimer uniquement le Job puis reappliquer :

```powershell
kubectl -n dtm delete job init-db
kubectl apply -k k8s
```

Le schema est idempotent mais ne gere pas les migrations de tables existantes.

## Etat des verifications

- Docker : telechargement, execution, arret et suppression d'un conteneur verifies.
- Tests applicatifs : 9 tests reussis, y compris les 3 tests d'integration sur PostgreSQL reel.
- Compose : API et PostgreSQL sains, initialisation terminee avec code 0.
- Calcul distribue : 30 taches a 1 000 000 traitees par 3 conteneurs workers, resultat 78 498.
- Persistance Compose : resultat conserve apres remplacement du conteneur PostgreSQL.
- Scalabilite Compose : passage de 3 a 1 puis de 1 a 3 workers verifie.
- Kubernetes : deploiement reel reussi le 13 novembre 2026 sur Docker Desktop, mode Kind, un noeud `Ready`, Kubernetes v1.36.1 et stockage dynamique `standard`.
- Communication Kubernetes : API disponible via Service et port-forward, schema initialise par le Job, calculs recuperes et resultats enregistres dans PostgreSQL.
- Scalabilite Kubernetes : 5 taches avec un worker, puis 30 taches avec 3 workers (repartition 13/13/4), toutes terminees avec le resultat 78 498.
- Persistance Kubernetes : pod `postgres-0` remplace, UID du pod modifie, meme PVC `data-postgres-0` et resultat de la tache 1 conserve.
- Resilience Kubernetes : suppression d'un worker au repos, remplacement automatique par le Deployment, retour a 3 pods disponibles.
- Apres remplacement PostgreSQL et worker : nouveau lot de 30 calculs reussi, repartition 12/9/9 incluant le nouveau worker.

Le test de remplacement d'un worker ne valide pas la reprise d'une tache
interrompue : cette fonctionnalite reste volontairement non implementee.

Avant remise : publier les livrables sur la branche principale du depot.
Aucun commit, depot distant ou envoi a l'enseignant n'est
automatise. La verification locale ne remplace pas une verification de l'acces a
l'image et du stockage sur le cluster d'un autre utilisateur.
