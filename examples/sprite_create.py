# Example: Create Sprite
# Endpoint: POST /v1/sprites

import os

from sprites import SpritesClient, URLSettings

token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]

client = SpritesClient(token)

client.create_sprite(
    sprite_name,
    url_settings=URLSettings(auth="sprite", private_access="admins"),
    labels=["example"],
)

print(f"Sprite '{sprite_name}' created")
