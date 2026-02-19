import os
import io
import logging
import tempfile
import requests
import time
import base64
from typing import List, Dict, Any
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Gradio REST API Client  (no gradio_client dependency)
# Connects via:
#   • POST  /gradio_api/upload          → upload files
#   • POST  /gradio_api/call/<api_name> → start prediction
#   • GET   /gradio_api/call/<api_name>/<hash> → get result (SSE stream)
# ─────────────────────────────────────────────────────────────────────────────

# Confidence gate – everything below this is labelled UNKNOWN
CONFIDENCE_THRESHOLD = 0.70  # 70%


class HuggingFaceClient:
    """Connects to the Gradio HF Space at eho69-arch.hf.space via REST API."""

    BASE_URL = "https://eho69-arch.hf.space"
    UPLOAD_URL = f"{BASE_URL}/gradio_api/upload"

    def __init__(self):
        self.space_url = os.getenv("HF_SPACE_URL", self.BASE_URL)
        self.hf_token = os.getenv("HF_TOKEN")
        self._session = requests.Session()
        if self.hf_token:
            self._session.headers["Authorization"] = f"Bearer {self.hf_token}"
        logger.info(f"HuggingFaceClient initialised → {self.space_url}")

    # ── keep the old .client property alive so startup warmup doesn't crash ──
    @property
    def client(self):
        """Compatibility shim – returns self so `_ = hf_client.client` works."""
        return self

    # ══════════════════════════════════════════════════════════════════════════
    # LOW-LEVEL HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _upload_file(self, file_path: str) -> str:
        """Upload a file via POST /gradio_api/upload and return its server path."""
        upload_url = f"{self.space_url}/gradio_api/upload"
        with open(file_path, "rb") as f:
            files = [("files", (os.path.basename(file_path), f, "image/png"))]
            resp = self._session.post(upload_url, files=files, timeout=60)
            resp.raise_for_status()
        data = resp.json()
        # Response is a list like [ "/path/on/server/filename.png" ] or [{"path": "..."}]
        if isinstance(data, list) and len(data) > 0:
            entry = data[0]
            if isinstance(entry, str):
                return entry
            elif isinstance(entry, dict):
                return entry.get("path", entry.get("name", ""))
        raise RuntimeError(f"Unexpected upload response: {data}")

    def _call_api(self, api_name: str, payload: dict, timeout: int = 120) -> Any:
        """
        POST /gradio_api/call/<api_name> → get event hash
        GET  /gradio_api/call/<api_name>/<hash> → stream SSE until 'complete'
        Returns the parsed 'data' list from the result.
        """
        import json

        call_url = f"{self.space_url}/gradio_api/call{api_name}"
        logger.info(f"Calling Gradio API: POST {call_url}")

        # Step 1: Initiate the call
        resp = self._session.post(call_url, json={"data": payload}, timeout=timeout)
        resp.raise_for_status()
        event_info = resp.json()
        event_id = event_info.get("event_id")
        if not event_id:
            raise RuntimeError(f"No event_id in response: {event_info}")

        # Step 2: Stream results via SSE
        result_url = f"{call_url}/{event_id}"
        logger.info(f"Streaming result: GET {result_url}")
        sse_resp = self._session.get(result_url, stream=True, timeout=timeout)
        sse_resp.raise_for_status()
        
        result_data = None
        for raw_line in sse_resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                try:
                    parsed = json.loads(data_str)
                    result_data = parsed
                except json.JSONDecodeError:
                    pass
            elif line.startswith("event:") and "error" in line.lower():
                logger.error(f"SSE error event: {line}")

        if result_data is None:
            raise RuntimeError("No data received from SSE stream")
        return result_data

    def _image_to_payload(self, server_path: str) -> dict:
        """Build the Gradio ImageData dict for an uploaded file."""
        return {
            "path": server_path,
            "meta": {"_type": "gradio.FileData"},
        }

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIC API  (async signature kept for compatibility with main.py)
    # ══════════════════════════════════════════════════════════════════════════

    async def save_template(self, name: str, images: List[Image.Image]) -> Dict[str, Any]:
        """Upload training samples to a class cluster (/add_sample)."""
        try:
            temp_dir = tempfile.gettempdir()
            last_result = None

            for i, img in enumerate(images):
                path = os.path.join(temp_dir, f"temp_sample_{name}_{i}.png")
                img.save(path)

                # 1) Upload file
                server_path = self._upload_file(path)
                logger.info(f"Uploaded sample {i} → {server_path}")

                # 2) Call /add_sample  (image, class_name)
                payload = [self._image_to_payload(server_path), name]
                last_result = self._call_api("/add_sample", payload)

                # Cleanup temp
                try:
                    os.remove(path)
                except Exception:
                    pass

            logger.info(f"Template '{name}' saved: {last_result}")
            return {"success": True, "result": last_result}

        except Exception as e:
            logger.error(f"Error saving template: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def list_classes(self) -> List[Dict[str, Any]]:
        """Retrieve the current trained classes (/list_classes)."""
        try:
            result = self._call_api("/list_classes", [])
            status_text = result[0] if isinstance(result, list) and result else str(result)
            classes = []
            if isinstance(status_text, str):
                for line in status_text.split("\n"):
                    line = line.strip()
                    if "•" in line and ":" in line:
                        name = line.split("•", 1)[-1].split(":", 1)[0].strip()
                        if name:
                            classes.append({"name": name})
            return classes
        except Exception as e:
            logger.error(f"Error listing classes: {e}")
            return []

    async def delete_template(self, name: str) -> Dict[str, Any]:
        """Delete a class cluster (/delete_class)."""
        try:
            result = self._call_api("/delete_class", [name])
            status_text = result[0] if isinstance(result, list) and result else str(result)
            if "✅" in str(status_text):
                return {"success": True, "result": status_text}
            return {"success": False, "error": status_text}
        except Exception as e:
            logger.error(f"Error deleting template: {e}")
            return {"success": False, "error": str(e)}

    async def detect_part(self, image: Image.Image, threshold: float = 0.70) -> Dict[str, Any]:
        """
        Run multi-stage detection via /detect_part.

        Confidence logic:
            • confidence < 70 %  → UNKNOWN (not matched)
            • confidence ≥ 70 %  → matched with the top class (Perfect / Defect)
        """
        try:
            # Save image to temp file
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, "temp_scan.png")
            image.save(temp_path)

            # 1) Upload
            server_path = self._upload_file(temp_path)
            logger.info(f"Scan image uploaded → {server_path}")

            # 2) Call /detect_part  (image, threshold)
            payload = [self._image_to_payload(server_path), threshold]
            result = self._call_api("/detect_part", payload)

            # Cleanup
            try:
                os.remove(temp_path)
            except Exception:
                pass

            # ── Parse the 5-tuple: [markdown, label_dict, vis_img, attn_img, edge_img]
            status_text = result[0] if isinstance(result, list) and len(result) > 0 else ""
            label_data  = result[1] if isinstance(result, list) and len(result) > 1 else None
            vis_data    = result[2] if isinstance(result, list) and len(result) > 2 else None
            attn_data   = result[3] if isinstance(result, list) and len(result) > 3 else None
            edge_data   = result[4] if isinstance(result, list) and len(result) > 4 else None

            confidence = 0.0
            best_match = None
            matched = False

            # Parse status text for cosine similarity and top prediction
            if status_text:
                for line in str(status_text).split("\n"):
                    lower = line.lower()
                    if "cosine similarity" in lower:
                        try:
                            val = line.rsplit(":", 1)[-1].strip()
                            val = val.replace("%", "").replace("*", "").replace("`", "").strip()
                            confidence = float(val) / 100.0
                        except Exception:
                            pass
                    if "top prediction" in lower:
                        try:
                            val = line.rsplit(":", 1)[-1].strip()
                            best_match = val.replace("*", "").replace("`", "").strip()
                        except Exception:
                            pass

            # Priority to label_data (Gradio Label component dict)
            if isinstance(label_data, dict):
                best_match = label_data.get("label", best_match)
                conf_list = label_data.get("confidences", [])
                if conf_list:
                    max_conf = max(
                        (c.get("confidence", c.get("value", 0.0)) for c in conf_list),
                        default=0.0,
                    )
                    confidence = max(confidence, max_conf)

            # ── BLANK / NO-PIECE DETECTION ───────────────────────────────
            # If the backend flagged an error (no bolt holes, no classes, etc.)
            # treat the result as UNKNOWN regardless of confidence.
            status_str = str(status_text).lower()
            is_blank_or_no_piece = any(marker in status_str for marker in [
                "no bolt holes",
                "no trained classes",
                "unconfigured",
                "localization failed",
                "insufficient hole",
                "roi selection failed",
            ])
            # Also treat it as blank if status only contains error/warning icons
            if "❌" in str(status_text) and "✅" not in str(status_text):
                is_blank_or_no_piece = True

            # ── CONFIDENCE GATE ──────────────────────────────────────────
            if is_blank_or_no_piece or confidence < CONFIDENCE_THRESHOLD:
                # Blank screen / no piece / below 70 %  →  UNKNOWN
                matched = False
                best_match = "UNKNOWN"
                reason = "blank/no-piece" if is_blank_or_no_piece else f"confidence {confidence:.2%} < {CONFIDENCE_THRESHOLD:.0%}"
                logger.info(f"Marking UNKNOWN → {reason}")
            else:
                # ≥ 70 %  →  match against Perfect / Defect classes
                matched = True
                # Normalise the label so it maps cleanly to PASS / FAIL downstream
                if best_match:
                    label_lower = best_match.lower()
                    if "perfect" in label_lower:
                        best_match = "Perfect"
                    elif "defect" in label_lower:
                        best_match = "Defect"
                    # else keep whatever the model returned
                logger.info(f"Confidence {confidence:.2%} ≥ {CONFIDENCE_THRESHOLD:.0%} → matched '{best_match}'")

            # ── Visualization URL ────────────────────────────────────────
            vis_url = None
            if isinstance(vis_data, dict):
                vis_url = vis_data.get("url") or vis_data.get("path")

            logger.info(f"Detection result → match={best_match}, conf={confidence:.2%}, matched={matched}")

            return {
                "success": True,
                "matched": matched,
                "confidence": confidence,
                "best_match": best_match,
                "status_text": status_text,
                "all_results": status_text,
                "visualization": vis_url,
            }

        except Exception as e:
            logger.error(f"Error during detection: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "matched": False,
                "confidence": 0.0,
            }

