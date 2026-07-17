# Sprites for OpenAI Agents

`sprites-openai-agents` connects [Sprites](https://sprites.dev) to the OpenAI
Agents SDK sandbox interface. It is maintained by the Sprites team and shipped
separately so both `sprites-py` and `openai-agents` remain provider-agnostic.

> [!NOTE]
> The OpenAI Agents SDK sandbox APIs are currently beta. Until they stabilize,
> each adapter release supports a deliberately narrow SDK version range.

## Installation

```bash
pip install sprites-openai-agents
```

Set the credentials used by the SDKs:

```bash
export OPENAI_API_KEY=...
export SPRITES_API_TOKEN=...
```

## Usage

```python
from agents.run import RunConfig
from agents.sandbox import SandboxAgent, SandboxRunConfig
from sprites_openai_agents import SpritesSandboxClient

client = SpritesSandboxClient()
sandbox = await client.create()

agent = SandboxAgent(
    name="Sprite assistant",
    instructions="Inspect the workspace and complete the requested task.",
)
run_config = RunConfig(sandbox=SandboxRunConfig(session=sandbox))

async with sandbox:
    # Pass agent and run_config to Runner.run(...) or Runner.run_streamed(...).
    ...
```

By default, the client creates an ephemeral sprite and deletes it when the
session is cleaned up. To attach to an existing sprite:

```python
from sprites_openai_agents import SpritesSandboxClientOptions

sandbox = await client.create(
    options=SpritesSandboxClientOptions(sprite_name="my-sprite"),
)
```

## Development

From the repository root:

```bash
python -m pip install -e .
python -m pip install -e 'integrations/openai-agents[dev]'
python -m pytest integrations/openai-agents/tests
python -m ruff check --config integrations/openai-agents/pyproject.toml integrations/openai-agents
python -m mypy --config-file integrations/openai-agents/pyproject.toml integrations/openai-agents/src
python -m build integrations/openai-agents
```

The adapter may use public `agents.sandbox` modules but must not import its old
in-tree location under `agents.extensions.sandbox.sprites`.

## Compatibility policy

The adapter imports OpenAI Agents symbols from their shortest documented public
path. A few provider primitives—PTY helpers, runtime helper scripts, workspace
path utilities, materialization types, and provider-facing errors—are documented
as modules but are not re-exported from `agents.sandbox`; those imports therefore
remain module-qualified. The upper bound on `openai-agents` prevents an untested
SDK minor release from silently changing those beta sandbox interfaces.
