# Example: Update Sprite
# Endpoint: PUT /v1/sprites/{name}

import os

from sprites import SpritesClient, URLSettings

token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]

client = SpritesClient(token)

sprite = client.update_sprite(
    sprite_name,
    url_settings=URLSettings(auth="public"),
    labels=["example", "public-demo"],
)

print(f"Sprite '{sprite.name}' updated")
