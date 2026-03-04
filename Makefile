install:
	pip install -r requirements.txt
	pip install -e .

run:
	python -m akuma_bot.main

compile:
	python -m compileall src

test:
	python -m unittest discover -s tests -p "test_*.py"

coverage:
	python -m coverage run -m unittest discover -s tests -p "test_*.py"
	python -m coverage report -m
