IMAGE_NAME ?= presenterm-wrapper
TAG ?= latest
DOCKERFILE ?= Dockerfile
LOCAL_BIN ?= $(HOME)/.local/bin
COMMAND_NAME ?= presenterm

.PHONY: build
build:
	docker build -f $(DOCKERFILE) -t $(IMAGE_NAME):$(TAG) .

.PHONY: present-test
present-test:
	docker run --rm -it -v "$(PWD):/data" $(IMAGE_NAME):$(TAG) test.md

.PHONY: install
install:
	mkdir -p "$(LOCAL_BIN)"
	install -m 0755 presenterm "$(LOCAL_BIN)/$(COMMAND_NAME)"
	@echo "Installed $(COMMAND_NAME) to $(LOCAL_BIN)"

.PHONY: clean-presenterm-containers
clean-presenterm-containers:
	@ids="$$( \
		{ \
			docker ps -aq --filter label=com.console_presenter.managed=true; \
			docker ps -aq | xargs -r docker inspect --format '{{.Id}} {{.Config.Image}}' | grep -F ' $(IMAGE_NAME):$(TAG)' | cut -d ' ' -f 1; \
		} | awk 'NF' | sort -u \
	)"; \
	if [ -n "$$ids" ]; then \
		echo "$$ids" | while IFS= read -r id; do [ -n "$$id" ] && docker rm -f "$$id"; done; \
	else \
		echo "No containers found for $(IMAGE_NAME):$(TAG)"; \
	fi
