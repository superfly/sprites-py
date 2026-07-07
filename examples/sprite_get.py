# Example: Get Sprite
# Endpoint: GET /v1/sprites/{name}

import json
import os

from sprites import SpritesClient

token = os.environ["SPRITE_TOKEN"]
sprite_name = os.environ["SPRITE_NAME"]

client = SpritesClient(token)

sprite = client.get_sprite(sprite_name)

result = {"name": sprite.name}
if sprite.id:
    result["id"] = sprite.id
if sprite.status:
    result["status"] = sprite.status
if sprite.url:
    result["url"] = sprite.url
if sprite.url_settings:
    result["url_settings"] = {
        "auth": sprite.url_settings.auth,
        "private_access": sprite.url_settings.private_access,
    }
if sprite.labels:
    result["labels"] = sprite.labels

print(json.dumps(result, indent=2))
