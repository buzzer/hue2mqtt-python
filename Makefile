.PHONY: all clean lint type test test-cov broker-start broker-stop

CMD:=poetry run
PYMODULE:=hue2mqtt
TESTS:=tests
EXTRACODE:=

all: type test lint

lint:
	$(CMD) ruff $(PYMODULE) $(TESTS) $(EXTRACODE)
	$(CMD) ruff format --check $(PYMODULE) $(TESTS) $(EXTRACODE)

lint-fix:
	$(CMD) ruff --fix $(PYMODULE) $(TESTS) $(EXTRACODE)
	$(CMD) ruff format $(PYMODULE) $(TESTS) $(EXTRACODE)

type:
	$(CMD) mypy $(PYMODULE) $(TESTS) $(EXTRACODE)

test:
	$(CMD) pytest --cov=$(PYMODULE) $(TESTS)

test-cov:
	$(CMD) pytest --cov=$(PYMODULE) $(TESTS) --cov-report html

# The wrapper tests need an MQTT broker on localhost:1883.
broker-start:
	docker run -d --rm --name hue2mqtt-test-broker -p 1883:1883 eclipse-mosquitto:2 \
		sh -c 'printf "listener 1883\nallow_anonymous true\n" > /tmp/m.conf && mosquitto -c /tmp/m.conf'

broker-stop:
	docker stop hue2mqtt-test-broker

clean:
	git clean -Xdf # Delete all files in .gitignore
