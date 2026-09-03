SHELL := /bin/bash
BASE_URL ?= http://127.0.0.1:8000
PROFILE ?= simnet
LANGUAGE ?= auto

.PHONY: help install start stop restart status logs health capabilities transcribe check full-check

help:
	@printf '%s\n' \
	  'make install                    # dependencies + supervisor + health' \
	  'make start|stop|restart|status' \
	  'make health|capabilities' \
	  'make logs                       # follow server log' \
	  'make transcribe FILE=call.mp3   # profile=simnet language=auto' \
	  'make full-check                 # service/GPU/CUDA/disk/log diagnostics'

install:
	bash ./setup-transcriber.sh

start:
	bash ./start.sh

stop:
	bash ./stop.sh

restart:
	bash ./restart.sh

status:
	bash ./status.sh

logs:
	tail -f logs/server.log

health:
	curl -fsS $(BASE_URL)/health | jq .

capabilities:
	curl -fsS $(BASE_URL)/capabilities | jq .

transcribe:
	@test -n "$(FILE)" || (echo 'Usage: make transcribe FILE=call.mp3 [PROFILE=simnet] [LANGUAGE=auto]' >&2; exit 2)
	bash ./transcribe.sh "$(FILE)" "$(PROFILE)" "$(LANGUAGE)"

check:
	python3 -m py_compile app.py smoke_test.py
	bash -n start.sh stop.sh restart.sh status.sh transcribe.sh setup-transcriber.sh diagnostic.sh simnet-transcriber-supervisor.sh

full-check:
	SIMNET_TRANSCRIBER_URL="$(BASE_URL)" bash ./diagnostic.sh
