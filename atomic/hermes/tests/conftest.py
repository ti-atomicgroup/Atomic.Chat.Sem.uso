from gateway.config import Platform

pytest_plugins = ["aiohttp.pytest_plugin"]

# Em produção o plugin system chama register(ctx) antes de instanciar o adapter.
Platform._add_pseudo_member("rocketchat")
