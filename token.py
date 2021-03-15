import smartpy as sp

IPFS_HASH = "QmRun4e1AhpG8rWbz3L8Rv66zao5jS6SaYKDTxYSNPw68Z"
TOKEN_ID_TYPE = sp.TNat
TOKEN_MAX_SUPPLY = 128
PRICE_CONST_C = 900
PRICE_CONST_K = 2
PRICE_DECIMALS = 1000


class ErrorMessage:
    def __init__(self):
        self.prefix = "FA2_"

    def make(self, s): return (self.prefix + s)
    def token_undefined(self): return self.make("TOKEN_UNDEFINED")
    def insufficient_balance(self): return self.make("INSUFFICIENT_BALANCE")
    def not_owner(self): return self.make("NOT_OWNER")
    def operators_unsupported(self): return self.make("OPERATORS_UNSUPPORTED")
    def token_supply_finished(self): return self.make("TOKEN_SUPPLY_FINISHED")


class BatchTransfer:
    def get_transfer_type(self):
        tx_type = sp.TRecord(
            to_=sp.TAddress,
            token_id=TOKEN_ID_TYPE,
            amount=sp.TNat
        )
        tx_type = tx_type.layout(("to_", ("token_id", "amount")))
        transfer_type = sp.TRecord(
            from_=sp.TAddress,
            txs=sp.TList(tx_type)
        ).layout(("from_", "txs"))
        return transfer_type

    def get_type(self):
        return sp.TList(self.get_transfer_type())

    def item(self, from_, txs):
        v = sp.record(from_=from_, txs=txs)
        return sp.set_type_expr(v, self.get_transfer_type())


class LedgerKey:
    def get_type():
        return sp.TRecord(owner=sp.TAddress, token_id=sp.TNat).layout(("owner", "token_id"))

    def make(owner, token_id):
        return sp.set_type_expr(sp.record(owner=owner, token_id=token_id), LedgerKey.get_type())


class BalanceOf:
    def request_type():
        return sp.TRecord(
            owner=sp.TAddress,
            token_id=TOKEN_ID_TYPE).layout(("owner", "token_id"))

    def response_type():
        return sp.TList(
            sp.TRecord(
                request=BalanceOf.request_type(),
                balance=sp.TNat
            )
            .layout(("request", "balance"))
        )

    def entry_point_type():
        return sp.TRecord(
            callback=sp.TContract(BalanceOf.response_type()),
            requests=sp.TList(BalanceOf.request_type())
        ).layout(("requests", "callback"))


class FA2Core(sp.Contract):
    def __init__(self, metadata, **extra_storage):
        self.error_message = ErrorMessage()
        self.batch_transfer = BatchTransfer()
        self.exception_optimization_level = "default-line"
        self.init(
            ledger=sp.big_map(
                tkey=LedgerKey.get_type(),
                tvalue=sp.TNat
            ),
            token_metadata=sp.big_map(
                tkey=sp.TNat,
                tvalue=sp.TPair(sp.TNat, sp.TMap(sp.TString, sp.TBytes))
            ),
            all_tokens=sp.nat(0),
            metadata=metadata,
            **extra_storage
        )

    @sp.entry_point
    def transfer(self, params):
        sp.set_type(params, self.batch_transfer.get_type())
        sp.for transfer in params:
            sp.for tx in transfer.txs:
                sp.if (tx.amount > sp.nat(0)):
                    from_user = LedgerKey.make(transfer.from_, tx.token_id)
                    to_user = LedgerKey.make(tx.to_, tx.token_id)

                    sender_has_token = self.data.ledger.get(from_user, sp.nat(0)) >= tx.amount

                    sp.verify(
                        sender_has_token,
                        message=self.error_message.insufficient_balance()
                    )

                    sp.verify(
                        transfer.from_ == sp.sender,
                        message=self.error_message.not_owner()
                    )

                    self.data.ledger[from_user] = sp.as_nat(self.data.ledger[from_user] - tx.amount)
                    self.data.ledger[to_user] = self.data.ledger.get(to_user, 0) + tx.amount

                    sp.if self.data.ledger.get(from_user, sp.nat(0)) == sp.nat(0):
                        del self.data.ledger[from_user]

    @sp.entry_point
    def balance_of(self, params):
        sp.set_type(params, BalanceOf.entry_point_type())

        responses = sp.local(
            "responses",
            sp.set_type_expr(
                sp.list([]),
                BalanceOf.response_type()
            )
        )
        sp.for request in params.requests:
            responses.value.push(
                sp.record(
                    request=request,
                    balance=self.data.ledger.get(LedgerKey.make(request.owner, request.token_id), 0)
                )
            )

        sp.transfer(responses.value, sp.mutez(0), params.callback)

    @sp.offchain_view(pure=True)
    def get_balance(self, req):
        sp.set_type(
            req, sp.TRecord(
                owner=sp.TAddress,
                token_id=sp.TNat
            ).layout(("owner", "token_id")))
        key = LedgerKey.make(req.owner, req.token_id)
        sp.verify(
            self.data.token_metadata.contains(req.token_id),
            message=self.error_message.token_undefined()
        )
        sp.result(self.data.ledger.get(key, sp.nat(0)))

    @sp.entry_point
    def update_operators(self, params):
        t = sp.TRecord(
            owner=sp.TAddress,
            operator=sp.TAddress,
            token_id=TOKEN_ID_TYPE
        )
        t = t.layout(("owner", ("operator", "token_id")))
        sp.set_type(
            params,
            sp.TList(
                sp.TVariant(
                    add_operator=t,
                    remove_operator=t
                )
            )
        )
        sp.failwith(self.error_message.operators_unsupported())

    def is_administrator(self, sender):
        return sp.bool(False)


class FA2Administrator(FA2Core):
    def is_administrator(self, sender):
        return sender == self.data.administrator

    @sp.entry_point
    def set_administrator(self, params):
        sp.verify(self.is_administrator(sp.sender))
        self.data.administrator = params


class FA2Mint(FA2Core):
    def next_token_id(self):
        return self.data.all_tokens + sp.nat(1)

    @sp.entry_point
    def mint(self):
        token_id = sp.compute(self.next_token_id())

        cost = sp.compute(self.price(token_id))
        sp.verify(
            token_id <= TOKEN_MAX_SUPPLY,
            message=self.error_message.token_supply_finished()
        )

        key = LedgerKey.make(sp.sender, token_id)
        sp.verify(~self.data.ledger.contains(key))
        sp.verify(~self.data.token_metadata.contains(token_id))

        sp.verify(
            sp.amount >= cost,
            message=self.error_message.insufficient_balance()
        )

        sp.send(self.data.administrator, cost)
        sp.if sp.amount > cost:
            sp.send(sp.sender, sp.amount - cost)

        self.data.all_tokens = token_id
        self.data.ledger[key] = sp.nat(1)
        self.data.token_metadata[token_id] = sp.pair(
            token_id,
            TokenMetadata.make_metadata(
                sp.blake2b(
                    sp.concat(
                        [
                            sp.pack(key),
                            sp.pack(sp.level),
                            sp.pack(sp.now)
                        ]
                    )
                )
            )
        )

    @sp.entry_point
    def skip(self):
        sp.verify(
            self.is_administrator(sp.sender),
            message=self.error_message.not_owner()
        )
        token_id = sp.compute(self.data.all_tokens + sp.nat(1))
        sp.verify(
            token_id <= TOKEN_MAX_SUPPLY,
            message=self.error_message.token_supply_finished()
        )
        key = LedgerKey.make(sp.sender, token_id)
        sp.verify(~self.data.ledger.contains(key))
        sp.verify(~self.data.token_metadata.contains(token_id))
        self.data.all_tokens = token_id

    def pow(self, a, b):
        result = sp.nat(1)
        sp.for x in sp.range(0, b):
            result *= a
        return result

    def price(self, number):
        price = self.pow(number, PRICE_CONST_K) * PRICE_CONST_C
        return sp.split_tokens(sp.tez(1), price, PRICE_DECIMALS)

    @sp.offchain_view(pure=True)
    def next_price(self):
        sp.result(
            self.price(self.next_token_id())
        )


class TokenMetadata(FA2Core):
    @sp.offchain_view(pure=True)
    def token_metadata(self, tok):
        sp.set_type(tok, sp.TNat)
        sp.result(self.data.token_metadata[tok])

    @sp.offchain_view(pure=True)
    def minted_tokens_metadata(self):
        metadata = sp.local("metadata", {})
        sp.for token_id in sp.range(0, self.data.all_tokens):
            sp.if self.data.token_metadata.contains(token_id):
                metadata.value[token_id] = sp.snd(
                    self.data.token_metadata[token_id]
                )
        sp.result(metadata.value)

    def make_metadata(seed):
        return sp.map(l={
            "decimals": sp.bytes_of_string("0"),
            "name": sp.bytes_of_string("Strange Token"),
            "seed": sp.slice(seed, 0, 6).open_some(),
            "symbol": sp.bytes_of_string("STRANGE")
        })


class StrangeToken(TokenMetadata, FA2Mint, FA2Administrator, FA2Core):
    @sp.offchain_view(pure=True)
    def count_tokens(self):
        sp.result(self.data.all_tokens)

    @sp.offchain_view(pure=True)
    def does_token_exist(self, tok):
        sp.set_type(tok, sp.TNat)
        sp.result(self.data.token_metadata.contains(tok))

    @sp.offchain_view(pure=True)
    def all_tokens(self):
        sp.result(sp.range(0, self.data.all_tokens))

    @sp.offchain_view(pure=True)
    def total_supply(self, tok):
        sp.set_type(tok, sp.TNat)
        sp.if self.data.token_metadata.contains(tok):
            sp.result(1)
        sp.else:
            sp.result(0)

    @sp.offchain_view(pure=True)
    def is_operator(self, query):
        sp.set_type(
            query,
            sp.TRecord(
                token_id=sp.TNat,
                owner=sp.TAddress,
                operator=sp.TAddress
            ).layout(
                ("owner", ("operator", "token_id"))
            )
        )
        sp.result(False)

    def __init__(self, metadata, admin):
        list_of_views = [
            self.get_balance,
            self.token_metadata,
            self.minted_tokens_metadata,
            self.does_token_exist,
            self.count_tokens,
            self.all_tokens,
            self.is_operator,
            self.next_price
        ]
        metadata_base = {
            "version": "StrangeToken",
            "interfaces": ["TZIP-12", "TZIP-16"],
            "views": list_of_views,
            "permissions": {
                "operator":
                "owner-transfer",
                "receiver": "owner-no-hook",
                "sender": "owner-no-hook"
            }
        }
        self.init_metadata("metadata_base", metadata_base)
        FA2Core.__init__(
            self,
            metadata,
            administrator=admin
        )


class ViewConsumer(sp.Contract):
    def __init__(self, contract):
        self.contract = contract
        self.init(balances={})

    @sp.entry_point
    def reinit(self):
        self.data.balances = {}

    @sp.entry_point
    def receive_balances(self, params):
        sp.set_type(params, BalanceOf.response_type())
        self.data.balances = {}
        sp.for resp in params:
            key = LedgerKey.make(resp.request.owner, resp.request.token_id)
            self.data.balances[key] = resp.balance

    def arguments_for_balance_of(receiver, reqs):
        return sp.record(
            callback=sp.contract(
                BalanceOf.response_type(),
                receiver.address,
                entry_point="receive_balances"
            ).open_some(),
            requests=reqs
        )


@sp.add_test(name="Token")
def test():
    scenario = sp.test_scenario()
    scenario.h1("NFT")
    scenario.table_of_contents()

    admin = sp.test_account("Admin")
    alice = sp.test_account("Alice")
    bob = sp.test_account("Bob")

    scenario.h2("Accounts")
    scenario.show([admin, alice, bob])

    scenario.h2("StrangeToken")
    tok = StrangeToken(
        metadata=sp.metadata_of_url("ipfs://%s" % IPFS_HASH),
        admin=admin.address
    )
    scenario += tok

    scenario.h2("Minting")
    scenario.h3("Mint operation")
    scenario += tok.mint().run(sender=alice, amount=sp.tez(10))
    scenario += tok.mint().run(sender=bob, amount=sp.tez(10))
    scenario += tok.mint().run(sender=alice, amount=sp.tez(0), valid=False)

    scenario.h3("Balances")
    consumer = ViewConsumer(tok)
    scenario += consumer
    scenario += tok.balance_of(ViewConsumer.arguments_for_balance_of(consumer, [
        sp.record(owner=alice.address, token_id=1),
        sp.record(owner=bob.address, token_id=0),
        sp.record(owner=bob.address, token_id=2)
    ]))

    scenario.verify(consumer.data.balances[LedgerKey.make(
        owner=alice.address, token_id=1)] == 1)
    scenario.verify(~consumer.data.balances.contains(LedgerKey.make(
        owner=bob.address, token_id=1)))
    scenario.verify(consumer.data.balances[LedgerKey.make(
        owner=bob.address, token_id=2)] == 1)

    scenario.h2("Skipping")
    scenario += tok.skip().run(sender=alice, amount=sp.tez(0), valid=False)
    scenario += tok.skip().run(sender=admin, amount=sp.tez(0))
    scenario += tok.mint().run(sender=alice, amount=sp.tez(20))

    scenario.h2("Transfer")
    scenario.h3("Bob can transfer his token")
    scenario += tok.transfer(
        [
            tok.batch_transfer.item(
                from_=bob.address,
                txs=[
                    sp.record(
                        to_=alice.address,
                        amount=1,
                        token_id=2
                    )
                ]
            )
        ]
    ).run(sender=bob)

    scenario.h3("Can't transfer more than 1 token")
    scenario += tok.transfer(
        [
            tok.batch_transfer.item(
                from_=alice.address,
                txs=[
                    sp.record(
                        to_=bob.address,
                        amount=2,
                        token_id=2
                    )
                ]
            )
        ]
    ).run(sender=alice, valid=False)

    scenario.h3("Bob can't transfer his token twice")
    scenario += tok.transfer(
        [
            tok.batch_transfer.item(
                from_=bob.address,
                txs=[
                    sp.record(
                        to_=alice.address,
                        amount=1,
                        token_id=2
                    )
                ]
            )
        ]
    ).run(sender=bob, valid=False)

    scenario.h3("Bob can't transfer Alice's token")
    scenario += tok.transfer(
        [
            tok.batch_transfer.item(
                from_=bob.address,
                txs=[
                    sp.record(
                        to_=admin.address,
                        amount=1,
                        token_id=2
                    )
                ]
            )
        ]
    ).run(sender=bob, valid=False)

    scenario.h3("Batch transfers")
    scenario += tok.transfer(
        [
            tok.batch_transfer.item(
                from_=alice.address,
                txs=[
                    sp.record(
                        to_=bob.address,
                        amount=1,
                        token_id=1
                    ),
                    sp.record(
                        to_=bob.address,
                        amount=1,
                        token_id=2
                    )
                ]
            )
        ]
    ).run(sender=alice)


sp.add_compilation_target(
    "StrangeToken",
    StrangeToken(
        metadata=sp.metadata_of_url("ipfs://%s" % IPFS_HASH),
        admin=sp.address("tz1du4E9rp73CNNcjh3tbXNX8GLRoTFR1WjP")
    )
)
