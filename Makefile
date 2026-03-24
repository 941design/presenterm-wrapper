IMAGE_NAME ?= presenterm-wrapper
TAG ?= latest
DOCKERFILE ?= Dockerfile
LOCAL_BIN ?= $(HOME)/.local/bin
COMMAND_NAME ?= presenterm
TARGETARCH ?= amd64

.PHONY: build-presenterm-amd64
build-presenterm-amd64:
	cd presenterm-src && cargo build --release --target x86_64-unknown-linux-musl
	mkdir -p build
	cp presenterm-src/target/x86_64-unknown-linux-musl/release/presenterm build/presenterm-amd64

.PHONY: build-presenterm-arm64
build-presenterm-arm64:
	command -v cross >/dev/null || cargo install cross
	cd presenterm-src && cross build --release --target aarch64-unknown-linux-musl
	mkdir -p build
	cp presenterm-src/target/aarch64-unknown-linux-musl/release/presenterm build/presenterm-arm64

.PHONY: build-presenterm
build-presenterm: build-presenterm-amd64 build-presenterm-arm64
	@echo "Built presenterm binaries for amd64 and arm64"

.PHONY: build
build: build-presenterm
	docker build -f $(DOCKERFILE) -t $(IMAGE_NAME):$(TAG) .

.PHONY: present-test
present-test:
	docker run --rm -it -v "$(PWD):/data" $(IMAGE_NAME):$(TAG) README.md

.PHONY: present-test-kitty
present-test-kitty:
	./presenterm README.md

.PHONY: install
install:
	mkdir -p "$(LOCAL_BIN)"
	install -m 0755 presenterm "$(LOCAL_BIN)/$(COMMAND_NAME)"
	@echo "Installed $(COMMAND_NAME) to $(LOCAL_BIN)"

.PHONY: clean-presenterm-src
clean-presenterm-src:
	cd presenterm-src && cargo clean
	rm -rf build/presenterm-*

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
