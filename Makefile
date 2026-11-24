.PHONY: dev api web test images k8s-up k8s-down port-forward

VENV ?= .venv
PY := $(VENV)/bin/python

# ---- local dev (no Docker needed: SQLite + in-memory queue + subprocess executor) ----
$(VENV):
	python3 -m venv $(VENV) && $(VENV)/bin/pip install -r backend/requirements-dev.txt

api: $(VENV)
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm install && npm run dev

test: $(VENV)
	cd backend && ../$(PY) -m pytest -q
	cd frontend && npx vitest run

# ---- Kubernetes (kind) ----
images:
	docker build -t mlops-backend:latest -f backend/Dockerfile .
	docker build -t mlops-trainer:latest trainer
	docker build -t mlops-dashboard:latest frontend

k8s-up: images
	kind get clusters | grep -q '^mlops$$' || kind create cluster --config deploy/k8s/kind-cluster.yaml
	kind load docker-image mlops-backend:latest mlops-trainer:latest mlops-dashboard:latest --name mlops
	kubectl apply -f deploy/k8s/00-namespace.yaml
	kubectl -n mlops create configmap prometheus-alerts --from-file=deploy/prometheus/alerts.yml --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n mlops create configmap grafana-datasources --from-literal=prometheus.yml="$$(sed 's#http://prometheus:9090#http://prometheus.mlops:9090#' deploy/grafana/provisioning/datasources/prometheus.yml)" --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n mlops create configmap grafana-providers --from-file=deploy/grafana/provisioning/dashboards/dashboards.yml --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n mlops create configmap grafana-dashboards --from-file=deploy/grafana/dashboards/mlops.json --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -f deploy/k8s/
	kubectl -n mlops rollout status deploy/mlops-api --timeout=180s

port-forward:
	kubectl -n mlops port-forward svc/mlops-dashboard 8080:80 & \
	kubectl -n mlops port-forward svc/grafana 3000:3000 & \
	kubectl -n mlops port-forward svc/prometheus 9090:9090 & wait

k8s-down:
	kind delete cluster --name mlops
