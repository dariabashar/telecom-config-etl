.PHONY: up load-v1 load-v2 test sample
up:            ## start Postgres and the API
	docker compose up -d --build
load-v1:       ## first export (contains broken rows on purpose)
	docker compose run --rm etl --data-dir data/v1
load-v2:       ## later export: upgrades, a new device, a decommissioned one
	docker compose run --rm etl --data-dir data/v2
sample:        ## regenerate synthetic data
	python scripts/make_sample_data.py
test:          ## needs TEST_DATABASE_URL pointing at an empty throw-away database
	pytest -q
