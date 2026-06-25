import io
import json
import posixpath
from typing import Any

from PIL import Image


FORMAT = "paragon-fe14-icon-bch"
VERSION = 1
ICON_PATH = "icon/Icon.bch.lz"
JSON_PATH = ICON_PATH + ".json"
FILES_DIR = ICON_PATH + ".files"


def save_icon_bch_json(data) -> int:
    from paragon import paragon as pgn

    raw_bch = bytes(data.read_file(ICON_PATH))
    textures = pgn.read_bch(raw_bch)

    manifest: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "game": "FE14",
        "path": ICON_PATH,
        "textures": [],
    }

    for texture in textures:
        png_filename = _png_filename(texture.filename)
        png_path = posixpath.join(FILES_DIR, png_filename)
        data.write_file(png_path, _texture_to_png(texture))
        manifest["textures"].append(
            {
                "name": texture.filename,
                "width": texture.width,
                "height": texture.height,
                "png": png_path,
            }
        )

    raw_manifest = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    data.write_file(JSON_PATH, raw_manifest)
    return len(textures)


def _png_filename(texture_name: str) -> str:
    sanitized = texture_name.replace("\\", "_").replace("/", "_")
    return sanitized + ".png"


def _texture_to_png(texture) -> bytes:
    image = Image.frombytes(
        "RGBA",
        (texture.width, texture.height),
        bytes(texture.pixel_data),
        "raw",
        "RGBA",
    )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
