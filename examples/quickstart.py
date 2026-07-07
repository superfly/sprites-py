# Example: Quick Start
# Endpoint: quickstart

# step: Install
# pip install sprites-py

# step: Setup client
import os
from sprites import SpritesClient
client = SpritesClient(os.environ["SPRITE_TOKEN"])

# step: Create a sprite
client.create_sprite(os.environ["SPRITE_NAME"])

# step: Run Python
result = client.sprite(os.environ["SPRITE_NAME"]).run(
    "python",
    "-c",
    "print(2+2)",
    capture_output=True,
)
print(result.stdout.decode(), end="")

# step: Clean up
client.destroy_sprite(os.environ["SPRITE_NAME"])
