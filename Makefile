PY ?= python3
TF ?= terraform

.PHONY: install test build tf-init tf-validate tf-fmt plan deploy destroy

install:        ## local test dependencies
	$(PY) -m pip install -r requirements-dev.txt

test:           ## pytest + moto (no AWS account needed)
	$(PY) -m pytest -q

build:          ## build Lambda packages into ./build (no AWS calls)
	PYTHON=$(PY) ./scripts/build_lambdas.sh

tf-init:
	cd terraform && $(TF) init -input=false

tf-validate:    ## static validation only - never touches AWS
	cd terraform && $(TF) init -backend=false -input=false && $(TF) validate && $(TF) fmt -check -recursive

tf-fmt:
	cd terraform && $(TF) fmt -recursive

plan: build tf-init  ## READS your AWS account; changes nothing
	cd terraform && $(TF) plan -out=tfplan

deploy: plan    ## CREATES REAL AWS RESOURCES (costs money) - only run on purpose
	cd terraform && $(TF) apply tfplan

destroy:        ## DELETES everything this project created (incl. bucket contents)
	cd terraform && $(TF) destroy
