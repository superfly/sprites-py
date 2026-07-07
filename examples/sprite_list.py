# Example: List Sprites
# Endpoint: GET /v1/sprites

import json
import os

from sprites import ListOptions, SpritesClient

token = os.environ["SPRITE_TOKEN"]

client = SpritesClient(token)

sprites = client.list_sprites(ListOptions(bulk_load=True))

result = []
for s in sprites.sprites:
    item = {"name": s.name}
    if s.id:
        item["id"] = s.id
    if s.status:
        item["status"] = s.status
    if s.url:
        item["url"] = s.url
    if s.labels:
        item["labels"] = s.labels
    result.append(item)

print(json.dumps({
    "sprites": result,
    "has_more": sprites.has_more,
    "next_continuation_token": sprites.next_continuation_token,
    "running": sprites.running,
    "warm": sprites.warm,
    "cold": sprites.cold,
}, indent=2))
