install:
	pip install -r requirements.txt
	pip install -e .

run:
	python -m akuma_bot.main

compile:
	python -m compileall src
