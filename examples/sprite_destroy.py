# Example: Destroy Sprite
# Endpoint: DELETE /v1/sprites/{name}

import os

from sprites import SpritesClient

token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]

client = SpritesClient(token)

client.destroy_sprite(sprite_name)

print(f"Sprite '{sprite_name}' destroyed")
