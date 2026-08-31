# Omnia Image Builder — developer tasks
#
# Usage: make <target>
# Run `make help` to see all targets.

COLLECTION_NS    := omnia
COLLECTION_NAME  := image_builder
VERSION          := $(shell grep '^version:' galaxy.yml | awk '{print $$2}')
TARBALL          := $(COLLECTION_NS)-$(COLLECTION_NAME)-$(VERSION).tar.gz
BUILDER_IMAGE    := ghcr.io/dell/omnia-image-builder:latest

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Testing ──────────────────────────────────────────────────────────
.PHONY: test
test: ## Run the pytest test suite
	python3 -m pytest tests/ -v

.PHONY: test-quiet
test-quiet: ## Run tests with minimal output
	python3 -m pytest tests/ -q

.PHONY: lint
lint: lint-yaml lint-ansible ## Run all linters

.PHONY: lint-yaml
lint-yaml: ## Lint YAML files
	@command -v yamllint >/dev/null 2>&1 || { echo "yamllint not installed: pip install yamllint"; exit 1; }
	yamllint -c .yamllint roles/ playbooks/ examples/ argo/ galaxy.yml

.PHONY: lint-ansible
lint-ansible: ## Lint Ansible playbooks and roles
	@command -v ansible-lint >/dev/null 2>&1 || { echo "ansible-lint not installed: pip install ansible-lint"; exit 1; }
	ansible-lint playbooks/ roles/

# ── Building ─────────────────────────────────────────────────────────
.PHONY: build
build: ## Build the Ansible collection tarball
	ansible-galaxy collection build --force

.PHONY: install
install: build ## Build and install the collection locally
	ansible-galaxy collection install $(TARBALL) --force
	ansible-galaxy collection install containers.podman

.PHONY: builder-image
builder-image: ## Build the Argo builder container image
	podman build -t $(BUILDER_IMAGE) -f argo/Containerfile .

# ── Running ──────────────────────────────────────────────────────────
.PHONY: build-rocky
build-rocky: install ## Build a Rocky 10 image (example)
	ansible-playbook $(COLLECTION_NS).$(COLLECTION_NAME).build_x86_64 -e @examples/rocky_x86_64.yml

.PHONY: build-alma
build-alma: install ## Build an AlmaLinux 10 image (example)
	ansible-playbook $(COLLECTION_NS).$(COLLECTION_NAME).build_x86_64 -e @examples/almalinux_x86_64.yml

.PHONY: build-fedora
build-fedora: install ## Build a Fedora 42 image (example)
	ansible-playbook $(COLLECTION_NS).$(COLLECTION_NAME).build_x86_64 -e @examples/fedora_x86_64.yml

# ── Argo deployment ──────────────────────────────────────────────────
.PHONY: argo-deploy
argo-deploy: ## Deploy Argo manifests to current kube context
	kubectl apply --server-side -k argo/

.PHONY: argo-submit
argo-submit: ## Submit a build workflow
	argo submit argo/workflow.yaml -n image-builder --watch

# ── Cleanup ──────────────────────────────────────────────────────────
.PHONY: clean
clean: ## Remove build artifacts
	rm -f $(COLLECTION_NS)-$(COLLECTION_NAME)-*.tar.gz
	rm -rf tests/__pycache__ tests/.pytest_cache
	find . -name '*.pyc' -delete

.PHONY: clean-output
clean-output: ## Remove built images from the default work_dir
	rm -rf /var/lib/image-builder/output /var/lib/image-builder/installroot

.PHONY: version
version: ## Print the collection version
	@echo $(VERSION)
