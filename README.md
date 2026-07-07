# Sprites Python SDK

Python SDK for [Sprites](https://sprites.dev), providing sprite management,
remote command execution, filesystem access, checkpoints, services, and network
policy controls.

## Installation

```bash
pip install sprites-py
```

## Quick Start

```python
import os

from sprites import SpritesClient

client = SpritesClient(token=os.environ["SPRITE_TOKEN"])
sprite = client.create_sprite(os.environ["SPRITE_NAME"])

# Run a command
result = sprite.run("echo", "hello", capture_output=True)
print(result.stdout.decode())  # "hello\n"

# Or use the Go-style API
cmd = sprite.command("ls", "-la")
output = cmd.output()
print(output.decode())

sprite.destroy()
```

## API Overview

### SpritesClient

```python
from sprites import ListOptions, SpritesClient, URLSettings

client = SpritesClient(
    token="your-token",
    base_url="https://api.sprites.dev",  # optional
    timeout=30.0,  # optional
    control_mode=False,  # optional multiplexed exec transport
)

# Create a sprite
sprite = client.create_sprite(
    "my-sprite",
    url_settings=URLSettings(auth="sprite", private_access="admins"),
    labels=["dev"],
    wait_for_capacity=True,
    runtime="dev",
)

# Get a sprite handle (doesn't create it)
sprite = client.sprite("my-sprite")

# Get a sprite with populated metadata
sprite = client.get_sprite("my-sprite")

# List sprites
page = client.list_sprites(ListOptions(prefix="my-", bulk_load=True))
for item in page.sprites:
    print(item.name, item.status, item.labels)

# Update URL settings and labels
updated = client.update_sprite(
    "my-sprite",
    url_settings=URLSettings(auth="public"),
    labels=["dev", "public-demo"],
)

# Destroy a sprite
client.destroy_sprite("my-sprite")
```

`URLSettings.auth` is `"sprite"` or `"public"`. When `auth="sprite"`,
`private_access` may be `"admins"` or `"org_users"`.

### Sprite

```python
# Run a command (subprocess.run style)
result = sprite.run("echo", "hello", capture_output=True, timeout=30)
print(result.returncode)
print(result.stdout)

# Create a command (Go exec.Cmd style)
cmd = sprite.command("bash", "-c", "echo hello")
output = cmd.output()  # Returns stdout
combined = cmd.combined_output()  # Returns stdout + stderr

# TTY mode
cmd = sprite.command("bash", tty=True, tty_rows=24, tty_cols=80)
cmd.run()

# Attach to an existing session
sessions = sprite.list_sessions()
cmd = sprite.attach_session(sessions[0].id, timeout=2)
cmd.run()
```

Commands use WebSockets. If `control_mode=True` is passed to `SpritesClient`,
new commands use the multiplexed control connection when the sprite supports it
and fall back to the standard exec WebSocket otherwise.

### Filesystem

```python
fs = sprite.filesystem("/app")

(fs / "config.json").write_text('{"debug": true}')
print((fs / "config.json").read_text())

for path in (fs / ".").iterdir():
    print(path.name)
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

### Services

```python
# Create or update a service and stream startup events
stream = sprite.create_service(
    "web",
    cmd="python",
    args=["-m", "http.server", "8000"],
    http_port=8000,
)
for event in stream:
    print(event.type, event.data)

# Inspect and control services
services = sprite.list_services()
web = sprite.get_service("web")
sprite.stop_service("web")
sprite.start_service("web")
```

### Network Policy

```python
from sprites import NetworkPolicy, PolicyRule

# Get current policy
policy = sprite.get_network_policy()

# Update policy
new_policy = NetworkPolicy(rules=[
    PolicyRule(domain="example.com", action="allow"),
])
sprite.update_network_policy(new_policy)
```

## Requirements

- Python 3.9+
- websockets
- httpx

## License

MIT
