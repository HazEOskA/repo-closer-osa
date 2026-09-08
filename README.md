# OSA Repo Closer

Standalone **OSA Autonomous Maintenance Engine** uruchamiany na żądanie.

## Pipeline

`CREATED → MAPPING → AUDITING → PLANNING → AWAITING_FIX_APPROVAL → FIXING → REVIEWING → AWAITING_PR_APPROVAL → PUBLISHING_PR → PR_OPEN → MERGING → MERGED → BUILDING → AWAITING_DEPLOY_APPROVAL → DEPLOYING → VERIFYING → COMPLETED`

Każda operacja write jest poza LLM i przechodzi przez policy/approval binding. Repo, README, kod i workflow są niezaufanymi danymi.

## Sterowanie

- `POST /runs` — read-only audit + plan
- `POST /runs/{id}/approve-fix` — zgoda na konkretny scope i komendy
- `POST /runs/{id}/approve-pr` — publikacja zatwierdzonego diffu
- `POST /runs/{id}/approve-merge` — merge wyłącznie gdy CI dla zatwierdzonego head SHA jest green
- `POST /runs/{id}/build` — Cloud Build canonical merge SHA; obraz jest tagowany SHA i zapisywany jako immutable `image@sha256:digest`
- `POST /runs/{id}/approve-deploy` — deploy wyłącznie obrazu i targetu zapisanych przez poprzedni BUILD; request nie może podmienić artefaktu
- `POST /runs/{id}/stop` — STOP
- `GET /runs/{id}` — stan + evidence
- `GET /health` — publiczny healthcheck

Endpointy sterujące wymagają `Authorization: Bearer $MAINTENANCE_API_TOKEN`.

## Runtime

- GitHub read/write przez osobne adaptery; write wymaga `GITHUB_TOKEN`.
- Fixer: Vertex AI przez ADC (`google-genai`), domyślnie `gemini-2.5-flash`.
- Persistence produkcyjne: Firestore; lokalnie można ustawić `MAINTENANCE_STORE=json`.
- Testy/komendy: wyłącznie jawnie zatwierdzona lista argv, `shell=False`.
- Merge: osobny approval binding, dokładny `head_sha`, zgodny base branch i wymagane zakończone green GitHub check-runs.
- Build/deploy: `gcloud` w kontenerze; build jest wykonywany z canonical `merge_sha`, a deploy wymaga immutable `image@sha256:digest`.

## Deploy silnika

`cloudbuild.yaml` tworzy Artifact Registry, service account i sekrety API/approval, buduje obraz, wdraża Cloud Run i robi smoke `/health`.

Dla prywatnych repo utwórz przed użyciem sekret `repo-closer-github-token` z minimalnym tokenem GitHub do wymaganych repo. Bez niego health i publiczne repo działają, a prywatne operacje GitHub pozostają zablokowane.
