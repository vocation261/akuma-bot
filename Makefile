install:
	pip install -r requirements.txt
	pip install -e .

.PHONY: install run compile test coverage prod-rebuild

run:
	python -m akuma_bot.main

compile:
	python -m compileall src

test:
	python -m unittest discover -s tests -p "test_*.py"

coverage:
	python -m coverage run -m unittest discover -s tests -p "test_*.py"
	python -m coverage report -m

prod-rebuild:
	docker compose -f docker-compose.yml down --remove-orphans
	docker compose -f docker-compose.yml build --no-cache bot
	docker compose -f docker-compose.yml up -d --force-recreate
	docker compose -f docker-compose.yml logs --tail=120 bot
