# =============================
# 🧠 TopScorers Makefile (K8s)
# =============================

# --- CONFIG ---
REGISTRY     = ghcr.io/drokenhorisk
NS           = topscorers

IMAGE_BACK   = $(REGISTRY)/topscorers-backend
IMAGE_FRONT  = $(REGISTRY)/topscorers-frontend
IMAGE_BOT    = $(REGISTRY)/topscorers-discord-bot

GIT_SHA      := $(shell git rev-parse --short HEAD)
DATE_TAG     := $(shell date +%Y%m%d%H%M%S)

# --- UTILS ---
define restart_deploy
	@echo "🔄 Restarting deployment $(1)..."
	kubectl -n $(NS) rollout restart deploy/$(1)
	kubectl -n $(NS) rollout status  deploy/$(1)
endef

# --- TARGETS ---

.PHONY: all build-backend build-frontend build-bot push restart generate check pvc-clean

all: build-backend push restart generate check

# 🏗️ BUILD IMAGES
build-backend:
	@echo "🏗️ Building backend image..."
	docker build --no-cache -t $(IMAGE_BACK):latest -f backend/Dockerfile .

build-frontend:
	@echo "🏗️ Building frontend image..."
	docker build --no-cache -t $(IMAGE_FRONT):latest -f frontend/Dockerfile .

build-bot:
	@echo "🏗️ Building Discord bot image..."
	docker build --no-cache -t $(IMAGE_BOT):latest -f discordbot/Dockerfile .

# 📤 PUSH IMAGES
push:
	@echo "📤 Pushing all images..."
	docker push $(IMAGE_BACK):latest
	docker push $(IMAGE_FRONT):latest
	docker push $(IMAGE_BOT):latest

# 🚀 RESTART DEPLOYMENTS
restart:
	$(call restart_deploy,topscorers-backend)
	$(call restart_deploy,topscorers-frontend)
	$(call restart_deploy,topscorers-discord-bot)

# ⚙️ GENERATE DASHBOARD
generate:
	@echo "🧮 Regenerating dashboard in backend..."
	kubectl -n $(NS) exec deploy/topscorers-backend -- python -m topscorers_dashboard || true
	@echo "✅ Dashboard regenerated."

# 🔍 CHECK DASHBOARD
check:
	@echo "🔎 Checking dashboard files (backend + frontend PVC)..."
	@PODB=$$(kubectl -n $(NS) get pod -l app=topscorers-backend -o jsonpath='{.items[0].metadata.name}'); \
	 kubectl -n $(NS) exec -it $$PODB -- ls -lah /data | tail -n 5
	@PODF=$$(kubectl -n $(NS) get pod -l app=topscorers-frontend -o jsonpath='{.items[0].metadata.name}'); \
	 kubectl -n $(NS) exec -it $$PODF -- ls -lah /usr/share/nginx/html | tail -n 5

# 🧹 CLEAN OLD DASHBOARD
pvc-clean:
	@echo "🧹 Cleaning dashboard file from PVC..."
	kubectl -n $(NS) exec deploy/topscorers-backend -- rm -f /data/dashboard_topscorers.html || true
