import asyncio
import time

from tools.mcp_pool import MCPClientPool


class DummyClient:
    def __init__(self, name: str, *, healthy: bool = True) -> None:
        self.name = name
        self._healthy = healthy
        self.closed = False
        self.health_checks = 0

    async def is_healthy(self) -> bool:  # pragma: no cover - behaviour exercised in tests
        self.health_checks += 1
        return self._healthy

    async def aclose(self) -> None:
        self.closed = True


def test_reuses_clients_until_expired():
    async def _run():
        make_count = 0

        async def factory(server: str):
            nonlocal make_count
            make_count += 1
            return DummyClient(f"{server}:{make_count}")

        pool = MCPClientPool(factory, ttl_seconds=1.0)

        client = await pool.get_client("alpha")
        assert client.name == "alpha:1"
        same = await pool.get_client("alpha")
        assert same is client
        assert make_count == 1

        await pool.shutdown()
        assert client.closed is True

    asyncio.run(_run())


def test_expires_clients_after_ttl(monkeypatch):
    async def _run():
        async def factory(server: str):
            return DummyClient(server)

        pool = MCPClientPool(factory, ttl_seconds=0.01)

        first = await pool.get_client("ttl")

        baseline = time.monotonic()
        monkeypatch.setattr("time.monotonic", lambda: baseline + 0.05)

        second = await pool.get_client("ttl")
        assert second is not first
        assert first.closed is True

    asyncio.run(_run())


def test_replaces_unhealthy_clients():
    async def _run():
        unhealthy = DummyClient("bad", healthy=False)
        clients = iter([unhealthy, DummyClient("good")])

        async def factory(server: str):
            return next(clients)

        pool = MCPClientPool(factory)

        first = await pool.get_client("srv")
        assert first is not None
        second = await pool.get_client("srv")
        assert second is not first
        assert unhealthy.closed is True

    asyncio.run(_run())


def test_concurrent_get_client_single_factory_call():
    async def _run():
        make_count = 0

        async def factory(server: str):
            nonlocal make_count
            make_count += 1
            await asyncio.sleep(0.01)
            return DummyClient(server)

        pool = MCPClientPool(factory)
        results = await asyncio.gather(*[pool.get_client("alpha") for _ in range(5)])

        assert len({id(result) for result in results}) == 1
        assert make_count == 1

    asyncio.run(_run())
