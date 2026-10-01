"""Bounded MCP perception payloads; never mutate the SDK/native snapshot."""
import base64
import io
import json
import time
from urllib.parse import unquote, urlparse


def render_state(state, *, no_img=True, annotate=False, view="text",
                 include_elements=False, image_max_edge=1280):
    started = time.perf_counter()
    result = dict(state)
    if not include_elements:
        result.pop("elements", None)
    if view == "diff" and state.get("diff") and state["diff"] != "(initial baseline tree)":
        result.pop("text", None)
    else:
        result.pop("diff", None)
    images = []
    if not no_img:
        source = (state.get("annotatedScreenshotUrl") if annotate else None) or state.get("screenshotUrl")
        if source:
            try:
                from PIL import Image
                path = unquote(urlparse(source).path) if source.startswith("file://") else source
                with Image.open(path) as original:
                    original_size = original.size
                    preview = original.convert("RGB")
                preview.thumbnail((image_max_edge, image_max_edge))
                buf = io.BytesIO()
                preview.save(buf, format="JPEG", quality=82, optimize=True)
                raw = buf.getvalue()
                images.append({"type": "image", "data": base64.b64encode(raw).decode("ascii"), "mimeType": "image/jpeg"})
                result["imageDelivery"] = {"status": "ready", "sourceSize": original_size,
                                           "previewSize": preview.size, "encodedBytes": len(raw),
                                           "coordinateSpace": "desktop points in windowBounds; preview pixels are scaled"}
            except Exception as exc:
                result["imageDelivery"] = {"status": "unavailable", "error": type(exc).__name__}
        else:
            result["imageDelivery"] = {"status": "unavailable", "error": "No screenshot returned"}
    else:
        result["imageDelivery"] = {"status": "disabled"}
    result["outputProfile"] = {"view": view, "includeElements": include_elements}
    timing = dict(state.get("timingsMs", {}))
    timing["mcpPresentation"] = round((time.perf_counter() - started) * 1000, 3)
    result["timingsMs"] = timing
    content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, separators=(",", ":"))}] + images
    return {"content": content, "isError": state.get("success") is False}
