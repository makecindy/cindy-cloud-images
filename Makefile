.PHONY: test
test:
	bash -n desktop/install-desktop.sh
	bash -n desktop/install-appearance.sh
	sh -n host/host-keyring.sh
	python3 -B -m unittest discover -s host -p 'test_*.py' -v
	python3 -B -m unittest discover -s common -p 'test_*.py' -v
