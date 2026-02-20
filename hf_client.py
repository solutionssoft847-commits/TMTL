import os
import io
import logging
import tempfile
import asyncio
import json
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
    CONFIDENCE_THRESHOLD = 0.70 
    
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

            raise ProcessingError("Connection Terminated: Stream ended without completion data. The model server might be overloaded.")
            
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

    # ─────────────────────────────────────────────────────────────────────────────
    # PUBLIC DOMAIN LOGIC
    # ─────────────────────────────────────────────────────────────────────────────

    async def save_template(self, name: str, images: List[Image.Image]) -> Dict[str, Any]:
        """Registers training samples for a class cluster."""
        try:
            results = []
            with tempfile.TemporaryDirectory() as tmp_dir:
                for idx, img in enumerate(images):
                    path = Path(tmp_dir) / f"sample_{idx}.png"
                    img.save(path, format="PNG")
                    
                    server_path = await self._upload_file(path)
                    payload = [{"path": server_path, "meta": {"_type": "gradio.FileData"}}, name]
                    results.append(await self._call_api("add_sample", payload))
            
            return {"success": True, "result": results[-1] if results else None}
        except Exception as e:
            logger.error(f"Training cluster failed: {e}")
            return {"success": False, "error": str(e)}

    async def detect_part(self, image: Image.Image, threshold: float = 0.92) -> Dict[str, Any]:
        """
        Executes multi-stage detection pipeline.
        
        Logic:
           - Localizes part (Bolt Holes)
           - Extracts high-dimensional features
           - Matches via Cosine Similarity
           - Thresholds for validation (70% standard)
        """
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image.save(tmp.name, format="PNG")
                temp_path = tmp.name
            
            server_path = await self._upload_file(temp_path)
            
            # API Request
            payload = [{"path": server_path, "meta": {"_type": "gradio.FileData"}}, threshold]
            result = await self._call_api("detect_part", payload)
            
            if not result or len(result) < 5:
                raise ProcessingError("Incomplete response from AI model.")
            
            # Parse result tuple: [markdown, label_dict, vis_img, attn_img, edge_img]
            status_text = result[0]
            label_data  = result[1]
            vis_data    = result[2]
            
            # Extract metrics
            confidence = 0.0
            best_match = "UNKNOWN"
            
            if isinstance(label_data, dict) and "confidences" in label_data:
                top = max(label_data["confidences"], key=lambda x: x.get("confidence", 0), default={})
                confidence = top.get("confidence", 0.0)
                best_match = top.get("label", "UNKNOWN")
            
            # Validation logic
            status_lower = str(status_text).lower()
            failures = ["no bolt holes", "localization failed", "insufficient hole"]
            is_valid = not any(f in status_lower for f in failures)
            
            if not is_valid or confidence < self.CONFIDENCE_THRESHOLD:
                best_match = "UNKNOWN"
                matched = False
            else:
                matched = True

            # Assets
            vis_path_remote = vis_data.get("path") if isinstance(vis_data, dict) else None
            local_vis_path = await self._download_asset(vis_path_remote)

            return {
                "success": True,
                "matched": matched,
                "confidence": confidence,
                "best_match": best_match,
                "status_text": status_text,
                "all_results": status_text,
                "visualization": local_vis_path
            }

        except Exception as e:
            logger.error(f"Scan pipeline failed: {e}", exc_info=True)
            return {"success": False, "error": str(e), "matched": False, "confidence": 0.0}
        finally:
            if temp_path and os.path.exists(temp_path):
                try: os.remove(temp_path)
                except: pass

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
                    n = line.split("•", 1)[-1].split(":", 1)[0].strip()
                    if n: classes.append({"name": n})
            return classes
        except: return []
