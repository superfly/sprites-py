# Sprites Python SDK

Python SDK for [Sprites](https://sprites.dev) - remote command execution platform.

## Installation

```bash
pip install sprites-py
```

## Quick Start

```python
from sprites import SpritesClient
from sprites.exec import run

# Create a client
client = SpritesClient(token="your-token")

# Create a sprite
sprite_name = "my-sprite"
client.create_sprite(sprite_name)

# Get a sprite handle
sprite = client.sprite(sprite_name)

# Run a command using the standalone run() function
result = run(sprite, "echo", "hello", capture_output=True)
print(result.stdout.decode())  # "hello\n"

# Or use the Go-style API (recommended)
cmd = sprite.command("ls", "-la")
output = cmd.output()
print(output.decode())
```

## API Overview

### SpritesClient

```python
from sprites import SpritesClient

client = SpritesClient(
    token="your-token",
    base_url="https://api.sprites.dev",  # optional
    timeout=30.0,  # optional
)

# Create a sprite
sprite = client.create_sprite("my-sprite")

# Get a sprite handle (doesn't create it)
sprite = client.sprite("my-sprite")

# Delete a sprite
client.delete_sprite("my-sprite")
```

### Sprite

```python
from sprites.exec import run

# Run a command (subprocess.run style)
result = run(sprite, "echo", "hello", capture_output=True, timeout=30)
print(result.returncode)
print(result.stdout)

# Create a command (Go exec.Cmd style - recommended)
cmd = sprite.command("bash", "-c", "echo hello")
output = cmd.output()  # Returns stdout
combined = cmd.combined_output()  # Returns stdout + stderr

# TTY mode
cmd = sprite.command("bash", tty=True, tty_rows=24, tty_cols=80)
cmd.run()
```

### Checkpoints

```python
# List checkpoints
checkpoints = sprite.list_checkpoints()

# Create a checkpoint
stream = sprite.create_checkpoint("my checkpoint")
for msg in stream:
    print(msg.type, msg.data)

# Restore a checkpoint
stream = sprite.restore_checkpoint("checkpoint-id")
for msg in stream:
    print(msg.type, msg.data)
```

### Network Policy

```python
from sprites.types import NetworkPolicy, PolicyRule

# Get current policy
policy = sprite.get_network_policy()

# Update policy
new_policy = NetworkPolicy(rules=[
    PolicyRule(domain="example.com", action="allow"),
])
sprite.update_network_policy(new_policy)
```

## Requirements

- Python 3.11+
- websockets
- httpx

## License

MIT
