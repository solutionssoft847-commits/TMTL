import os
import io
import logging
import tempfile
import asyncio
import json
import re
from typing import List, Dict, Any, Optional, Union
from pathlib import Path

import httpx
from httpx_sse import aconnect_sse
from PIL import Image
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class HuggingFaceClientError(Exception):
    """Base exception for client-side errors."""
    pass

class AIServiceUnavailable(HuggingFaceClientError):
    """Raised when the remote AI service is unreachable."""
    pass

class ProcessingError(HuggingFaceClientError):
    """Raised when the AI model fails to process the input."""
    pass


class HuggingFaceClient:
    

    DEFAULT_BASE_URL = "https://eho69-arch.hf.space"
    CONFIDENCE_THRESHOLD = 0.60  # Softmax probability threshold

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = (base_url or os.getenv("HF_SPACE_URL", self.DEFAULT_BASE_URL)).rstrip("/")
        self.token = token or os.getenv("HF_TOKEN")
        self.timeout = httpx.Timeout(150.0, connect=10.0)
        self.limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        self._async_client: Optional[httpx.AsyncClient] = None

        logger.info(f"HuggingFaceClient initialised → {self.base_url}")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            self._async_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                limits=self.limits,
                follow_redirects=True
            )
        return self._async_client

    async def close(self):
        if self._async_client and not self._async_client.is_closed:
            await self._async_client.aclose()

    # ─────────────────────────────────────────────────────────────────────────────
    # INTERNAL PROTOCOL LAYER
    # ─────────────────────────────────────────────────────────────────────────────

    async def _upload_file(self, file_path: Union[str, Path]) -> str:
        """Uploads a file to Gradio transient storage."""
        try:
            with open(file_path, "rb") as f:
                files = {"files": (os.path.basename(file_path), f, "image/png")}
                response = await self.client.post("/gradio_api/upload", files=files)
                response.raise_for_status()

            data = response.json()
            if isinstance(data, list) and data:
                return data[0] if isinstance(data[0], str) else data[0].get("path", "")
            raise ProcessingError(f"Malformed upload response: {data}")

        except httpx.HTTPError as e:
            logger.error(f"Upload failed: {e}")
            raise AIServiceUnavailable(f"Network error during upload: {e}")

    async def _call_api(self, api_name: str, payload: List[Any]) -> List[Any]:
        """
        State-machine for Gradio SSE protocol.
        Handles job initiation and subscription to the event stream.
        """
        api_path = f"/gradio_api/call/{api_name.lstrip('/')}"

        try:
            # 1. Dispatch the job
            response = await self.client.post(api_path, json={"data": payload})
            response.raise_for_status()
            event_id = response.json().get("event_id")

            if not event_id:
                raise ProcessingError("Protocol Error: No event_id returned by server.")

            # 2. Subscribe to the event stream
            result_url = f"{api_path}/{event_id}"
            logger.debug(f"Awaiting result from {result_url}")

            async with aconnect_sse(self.client, "GET", result_url) as event_source:
                async for event in event_source.aiter_sse():
                    if event.event == "error":
                        raise ProcessingError(f"Remote engine error: {event.data}")

                    if not event.data:
                        continue

                    try:
                        data = json.loads(event.data)

                        # Handle case where server returns a direct list of results
                        if isinstance(data, list):
                            return data

                        if not isinstance(data, dict):
                            continue

                        msg = data.get("msg")

                        # Gradio 4 completion event
                        if msg == "process_completed":
                            output = data.get("output", {})
                            if output.get("error"):
                                raise ProcessingError(f"Model Inference Error: {output['error']}")
                            return output.get("data", [])

                        # Fail-safe for dictionary responses with 'data' field
                        if not msg and "data" in data:
                            return data["data"]

                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE line: {event.data}")
                        continue

            raise ProcessingError("Connection Terminated: Stream ended without completion data.")

        except httpx.HTTPError as e:
            logger.error(f"API communication failure: {e}")
            raise AIServiceUnavailable(f"Remote server unreachable: {e}")

    async def _download_asset(self, remote_path: str) -> Optional[str]:
        """Resolves a remote Gradio file path to a local temporary file."""
        if not remote_path:
            return None

        url = remote_path if remote_path.startswith("http") else f"{self.base_url}/file={remote_path}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()

            fd, local_path = tempfile.mkstemp(suffix=".png", prefix="hf_result_")
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(response.content)
            return local_path
        except Exception as e:
            logger.warning(f"Visualization download failed: {e}")
            return None

    @staticmethod
    def _cleanup_temp_file(path: Optional[str]) -> None:
        """Safely remove a temporary file, suppressing all errors."""
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    # ─────────────────────────────────────────────────────────────────────────────
    # RESULT PARSING HELPERS
    # ─────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_label_data(label_data: Any) -> tuple[str, float, dict]:
        """
        Parse the Gradio Label component output.
        
        Gradio Label returns:
          {"label": "Perfect", "confidences": [
              {"label": "Perfect", "confidence": 0.73},
              {"label": "Defected", "confidence": 0.27}
          ]}
        
        The confidences are now softmax probabilities (proper 0-1 range),
        NOT raw cosine similarities.
        
        Returns: (best_match, confidence, all_scores)
        """
        best_match = "UNKNOWN"
        confidence = 0.0
        all_scores = {}

        if not isinstance(label_data, dict):
            return best_match, confidence, all_scores

        # Gradio Label format with confidences array
        if "confidences" in label_data:
            confidences = label_data["confidences"]
            if isinstance(confidences, list) and confidences:
                # Sort by confidence descending
                sorted_conf = sorted(confidences, key=lambda x: x.get("confidence", 0), reverse=True)
                top = sorted_conf[0]
                best_match = top.get("label", "UNKNOWN")
                confidence = float(top.get("confidence", 0.0))
                all_scores = {c.get("label", ""): float(c.get("confidence", 0.0)) for c in sorted_conf}

        # Direct dict format: {"Perfect": 0.73, "Defected": 0.27}
        elif all(isinstance(v, (int, float)) for v in label_data.values()):
            if label_data:
                sorted_items = sorted(label_data.items(), key=lambda x: x[1], reverse=True)
                best_match = sorted_items[0][0]
                confidence = float(sorted_items[0][1])
                all_scores = {k: float(v) for k, v in sorted_items}

        # Fallback: use "label" key directly
        elif "label" in label_data:
            best_match = label_data["label"]
            confidence = float(label_data.get("confidence", 0.0))

        return best_match, confidence, all_scores

    @staticmethod
    def _parse_status_text(status_text: str) -> dict:
        
        info = {"confidence_pct": None, "raw_similarity": None, "status_line": None}

        if not isinstance(status_text, str):
            return info

        for line in status_text.split("\n"):
            if "**Confidence**" in line:
                match = re.search(r"([\d.]+)%", line)
                if match:
                    info["confidence_pct"] = float(match.group(1)) / 100.0

            elif "**Raw Similarity**" in line:
                match = re.search(r"([\d.]+)", line.split(":")[-1])
                if match:
                    info["raw_similarity"] = float(match.group(1))

            elif "**Status**" in line:
                info["status_line"] = line.split("**Status**:")[-1].strip() if ":" in line else line

        return info

    # ─────────────────────────────────────────────────────────────────────────────
    # PUBLIC DOMAIN LOGIC
    # ─────────────────────────────────────────────────────────────────────────────

    async def save_template(self, name: str, images: List[Image.Image]) -> Dict[str, Any]:
        
        try:
            accepted = 0
            rejected = 0
            rejected_reasons = []

            with tempfile.TemporaryDirectory() as tmp_dir:
                for idx, img in enumerate(images):
                    # Save as high-quality PNG — no aggressive preprocessing
                    path = Path(tmp_dir) / f"sample_{idx}.png"
                    img.save(path, format="PNG")

                    server_path = await self._upload_file(path)
                    payload = [
                        {"path": server_path, "meta": {"_type": "gradio.FileData"}},
                        name
                    ]
                    result = await self._call_api("add_sample", payload)

                    # Backend returns [status_text, roi_image]
                    # status_text contains ❌/⚠️ if bolt detection failed
                    status_text = str(result[0]) if result and len(result) > 0 else ""

                    if "❌" in status_text or "⚠️" in status_text:
                        rejected += 1
                        rejected_reasons.append(f"Sample {idx+1}: {status_text.split(chr(10))[0]}")
                        logger.warning(f"Sample {idx+1}/{len(images)} REJECTED for '{name}': {status_text[:100]}")
                    else:
                        accepted += 1
                        logger.info(f"Sample {idx+1}/{len(images)} accepted for '{name}'")

            if accepted == 0 and rejected > 0:
                return {
                    "success": False,
                    "error": f"All {rejected} image(s) rejected — no bolt holes detected",
                    "accepted": 0,
                    "rejected": rejected,
                    "rejected_reasons": rejected_reasons
                }

            return {
                "success": True,
                "accepted": accepted,
                "rejected": rejected,
                "rejected_reasons": rejected_reasons,
            }
        except Exception as e:
            logger.error(f"Training cluster failed: {e}")
            return {"success": False, "error": str(e), "accepted": 0, "rejected": 0}

    async def detect_part(self, image: Image.Image, threshold: float = 0.70) -> Dict[str, Any]:
        
        temp_path = None
        local_vis_path = None
        local_attn_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image.save(tmp.name, format="PNG")
                temp_path = tmp.name

            server_path = await self._upload_file(temp_path)

            # Send threshold to backend — it uses this for the matched/unmatched decision
            payload = [
                {"path": server_path, "meta": {"_type": "gradio.FileData"}},
                threshold
            ]
            result = await self._call_api("detect_part", payload)

            if not result or len(result) < 5:
                raise ProcessingError("Incomplete response from AI model.")

            # Parse result tuple: [markdown, label_dict, vis_img, attn_img, edge_img]
            status_text = result[0]
            label_data  = result[1]
            vis_data    = result[2]
            attn_data   = result[3]
            edge_data   = result[4]

            # ── Extract confidence from label data ───────────────────────────
            best_match, confidence, all_scores = self._parse_label_data(label_data)

            # ── Fallback: parse from status text if label parsing failed ─────
            if confidence == 0.0 and isinstance(status_text, str):
                parsed = self._parse_status_text(status_text)
                if parsed["confidence_pct"] is not None:
                    confidence = parsed["confidence_pct"]

            # ── Validation logic ─────────────────────────────────────────────
            # Trust the backend's matched/confidence decision. 
            # We only mark as UNKNOWN if localization failed.
            status_lower = str(status_text).lower()
            failures = ["no bolt holes", "localization failed", "insufficient hole"]
            is_valid = not any(f in status_lower for f in failures)

            matched = result[1].get("matched", False) if isinstance(result[1], dict) else True
            if not is_valid:
                best_match = "UNKNOWN"
                matched = False

            # ── Download visualization assets ─────────────────────────────────
            # Files are downloaded to temp, read to bytes, then immediately deleted
            # to prevent unbounded accumulation of temp files on disk.
            vis_path_remote = vis_data.get("path") if isinstance(vis_data, dict) else None
            local_vis_path = await self._download_asset(vis_path_remote)

            attn_path_remote = attn_data.get("path") if isinstance(attn_data, dict) else None
            local_attn_path = await self._download_asset(attn_path_remote)

            logger.info(
                f"Detection result: {best_match} | confidence={confidence:.3f} | "
                f"matched={matched} | scores={all_scores}"
            )

            # Return the local file path; the CALLER (main.py) converts to base64
            # and must delete the temp files afterwards.
            return {
                "success": True,
                "matched": matched,
                "confidence": confidence,
                "best_match": best_match,
                "status_text": status_text,
                "all_results": status_text,
                "all_scores": all_scores,
                "visualization": local_vis_path,
                "attention_map": local_attn_path,
                # Internal flag so the caller knows which paths to clean up
                "_temp_paths": [p for p in [local_vis_path, local_attn_path] if p],
            }

        except Exception as e:
            logger.error(f"Scan pipeline failed: {e}", exc_info=True)
            # Clean up any partially-downloaded assets on failure
            self._cleanup_temp_file(local_vis_path)
            self._cleanup_temp_file(local_attn_path)
            return {"success": False, "error": str(e), "matched": False, "confidence": 0.0}
        finally:
            # Always clean up the input temp file
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    async def delete_template(self, name: str) -> Dict[str, Any]:
        """Deactivates a class cluster."""
        try:
            res = await self._call_api("delete_class", [name])
            return {"success": True, "result": res[0] if res else ""}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def list_classes(self) -> List[Dict[str, Any]]:
        """Queries the trained part registry."""
        try:
            res = await self._call_api("list_classes", [])
            status = res[0] if res else ""
            classes = []
            for line in str(status).split("\n"):
                if "•" in line and ":" in line:
                    parts = line.split("•", 1)[-1].split(":", 1)
                    name = parts[0].strip()
                    count_str = parts[1].strip() if len(parts) > 1 else ""
                    count_match = re.search(r"(\d+)", count_str)
                    count = int(count_match.group(1)) if count_match else 0
                    if name:
                        classes.append({"name": name, "sample_count": count})
            return classes
        except Exception:
            return []
