CURRENT_VERSION=$(shell cat server/__init__.py | cut -d \" -f 2)
DOCKER_IMAGE_NAME=dataesr/dataesr-mcp
GHCR_IMAGE_NAME=ghcr.io/$(DOCKER_IMAGE_NAME)

build:
	@echo "Building Docker image $(DOCKER_IMAGE_NAME):$(CURRENT_VERSION)"
	docker build -t $(DOCKER_IMAGE_NAME):$(CURRENT_VERSION) -t $(DOCKER_IMAGE_NAME):latest .
	@echo "Docker image $(DOCKER_IMAGE_NAME):$(CURRENT_VERSION) built successfully"

push:
	@echo "Pushing Docker image $(DOCKER_IMAGE_NAME):$(CURRENT_VERSION)"
	docker push $(DOCKER_IMAGE_NAME):$(CURRENT_VERSION)
	docker push $(DOCKER_IMAGE_NAME):latest
	@echo "Docker image $(DOCKER_IMAGE_NAME):$(CURRENT_VERSION) pushed successfully"

build-push:
	@"$(MAKE)" build
	@"$(MAKE)" push

release:
ifndef VERSION
	$(error VERSION is not defined. Use 'make release VERSION=x.y.z')
endif
	echo '__version__ = "${VERSION}"' > server/__init__.py
	git commit -am '[release] version ${VERSION}'
	git tag v${VERSION}
	@echo "If everything is OK, you can push with tags i.e. git push origin main --tags"
