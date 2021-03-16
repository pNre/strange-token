.PHONY: build test originate mint sandbox testnet check-key-alias

build:
	~/smartpy-cli/SmartPy.sh compile token.py build --html

test:
	~/smartpy-cli/SmartPy.sh test token.py build --html
	open ./build/Token/log.html

originate: check-key-alias build
	tezos-client originate contract strange-token \
		transferring 0 from $(KEY_ALIAS) \
		running ./build/StrangeToken/step_000_cont_0_contract.tz \
		--init '$(shell cat ./build/StrangeToken/step_000_cont_0_storage.tz)' \
		--burn-cap 10 \
		--force --no-print-source

mint: check-key-alias
	tezos-client transfer 1000 from $(KEY_ALIAS) to strange-token \
		--entrypoint mint \
		--burn-cap 3

sandbox:
	docker-compose up -d
	sleep 20
	tezos-client config reset
	tezos-client --endpoint http://localhost:8732 bootstrapped
	tezos-client --endpoint http://localhost:8732 config update
	tezos-client import secret key sandbox-alice unencrypted:edsk3QoqBuvdamxouPhin7swCvkQNgq4jP5KZPbwWNnwdZpSpJiEbq --force
	tezos-client import secret key sandbox-bob unencrypted:edsk3RFfvaFaxbHx8BMtEW1rKQcPtDML3LXjNqMNLCzC3wLC1bWbAt --force

testnet:
	tezos-client config reset
	tezos-client --endpoint https://edonet.smartpy.io bootstrapped
	tezos-client --endpoint https://edonet.smartpy.io config update
	tezos-client import keys from mnemonic test-alice with ./testnet/alice.json -f

check-key-alias:
ifndef KEY_ALIAS
	$(error KEY_ALIAS is not set)
endif
