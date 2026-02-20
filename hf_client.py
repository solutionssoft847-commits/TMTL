import os
import io
import logging
import tempfile
import asyncio
import base64
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Tuple
from pathlib import Path

import httpx
from httpx_sse import aconnect_sse
from PIL import Image
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging to integrate with the main app's logging system
logger = logging.getLogger(__name__)

class HuggingFaceClientError(Exception):
    """Base exception for HuggingFaceClient errors."""
    pass

class AIServiceUnavailable(HuggingFaceClientError):
    """Raised when the remote AI service is unreachable or returns 503."""
    pass

class ProcessingError(HuggingFaceClientError):
    """Raised when the AI model fails to process the input."""
    pass

class HuggingFaceClient:
    
    DEFAULT_BASE_URL = "https://eho69-arch.hf.space"
    CONFIDENCE_THRESHOLD = 0.70  # Industrial standard for "Unknown" classification
    
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        
        self.base_url = (base_url or os.getenv("HF_SPACE_URL", self.DEFAULT_BASE_URL)).rstrip("/")
        self.token = token or os.getenv("HF_TOKEN")
        
        # Configuration for stability
        self.timeout = httpx.Timeout(120.0, connect=10.0)
        self.limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        
        # Initialise shared async client lazily to ensure it runs in the correct event loop
        self._async_client: Optional[httpx.AsyncClient] = None
        
        logger.info(f"HuggingFaceClient initialised | Target: {self.base_url}")

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
        """Cleanly close the underlying HTTP session."""
        if self._async_client and not self._async_client.is_closed:
            await self._async_client.aclose()
            logger.debug("HuggingFaceClient session closed.")

    # ─────────────────────────────────────────────────────────────────────────────
    # CORE COMMUNICATION LAYER
    # ─────────────────────────────────────────────────────────────────────────────

    async def _upload_file(self, file_path: Union[str, Path]) -> str:
        """
        Uploads a file to the Gradio server and returns the internal server path.
        """
        client = self.client
        path = Path(file_path)
        
        try:
            with open(path, "rb") as f:
                logger.debug(f"Uploading file: {path.name}")
                files = {"files": (path.name, f, "image/png")}
                response = await client.post("/gradio_api/upload", files=files)
                response.raise_for_status()
                
            data = response.json()
            # Gradio typically returns a list of paths or dicts
            if isinstance(data, list) and data:
                entry = data[0]
                return entry if isinstance(entry, str) else entry.get("path", "")
                
            raise ProcessingError(f"Unexpected upload response format: {data}")
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Upload failed (HTTP {e.response.status_code}): {e.response.text}")
            raise AIServiceUnavailable(f"Remote storage unreachable: {e}")
        except Exception as e:
            logger.error(f"File upload exception: {e}")
            raise HuggingFaceClientError(f"Local file I/O or network error: {e}")

    async def _call_api(self, api_name: str, payload: List[Any]) -> List[Any]:
        client = self.client
        api_path = f"/gradio_api/call{api_name if api_name.startswith('/') else '/' + api_name}"
        
        try:
            # 1. Start the job
            response = await client.post(api_path, json={"data": payload})
            response.raise_for_status()
            event_id = response.json().get("event_id")
            
            if not event_id:
                raise ProcessingError("Failed to initiate processing: No event_id returned.")

            # 2. Listen for completion via Server-Sent Events
            result_url = f"{api_path}/{event_id}"
            logger.debug(f"Awaiting result from {result_url}")
            
            async with aconnect_sse(client, "GET", result_url) as event_source:
                async for event in event_source.aiter_sse():
                    if event.event == "error":
                        raise ProcessingError(f"Remote engine error: {event.data}")
                    
                    if event.data:
                        try:
                            data = json.loads(event.data)
                            # Look for the completion message or the final data payload
                            if isinstance(data, dict):
                                if data.get("msg") == "process_completed":
                                    return data.get("output", {}).get("data", [])
                                elif "data" in data and not data.get("msg"):
                                    # Fallback for simpler responses
                                    return data["data"]
                        except json.JSONDecodeError:
                            continue

            raise ProcessingError("Stream ended without completion event.")
            
        except httpx.HTTPError as e:
            logger.error(f"API Call failed: {e}")
            raise AIServiceUnavailable(f"AI engine communication failure: {e}")

    async def _download_asset(self, remote_path: str) -> Optional[str]:
        """
        Downloads a remote asset to a local temporary file.
        This is critical because the main application expects local file paths for processing.
        """
        if not remote_path:
            return None
            
        client = self.client
        # Build full URL if it's a relative path from the server
        url = remote_path if remote_path.startswith("http") else f"{self.base_url}/file={remote_path}"
        
        try:
            logger.debug(f"Downloading visualization: {url}")
            response = await client.get(url)
            response.raise_for_status()
            
            # Save to an industrial-grade temporary file
            suffix = Path(remote_path).suffix or ".png"
            fd, local_path = tempfile.mkstemp(suffix=suffix, prefix="hf_vis_")
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(response.content)
            
            return local_path
        except Exception as e:
            logger.warning(f"Failed to download visualization asset: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────────
    # PUBLIC DOMAIN LOGIC
    # ─────────────────────────────────────────────────────────────────────────────

    async def save_template(self, name: str, images: List[Image.Image]) -> Dict[str, Any]:
        """
        Registers new training samples for a specific part class.
        
        Args:
            name: The class name (e.g., "Perfect").
            images: List of PIL images to upload.
        """
        try:
            logger.info(f"Registering {len(images)} samples for class '{name}'")
            last_result = None
            
            with tempfile.TemporaryDirectory() as tmp_dir:
                for idx, img in enumerate(images):
                    local_path = Path(tmp_dir) / f"sample_{idx}.png"
                    # Use high quality for feature extraction
                    img.save(local_path, format="PNG", optimize=True)
                    
                    # Upload and notify the model
                    server_path = await self._upload_file(local_path)
                    payload = [{"path": server_path, "meta": {"_type": "gradio.FileData"}}, name]
                    last_result = await self._call_api("add_sample", payload)
            
            return {"success": True, "result": last_result}
            
        except Exception as e:
            logger.error(f"Template registration failed for {name}: {e}")
            return {"success": False, "error": str(e)}

    async def detect_part(self, image: Image.Image, threshold: float = 0.92) -> Dict[str, Any]:
       
        temp_path = None
        try:
            # 1. Prepare and Upload
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image.save(tmp.name, format="PNG")
                temp_path = tmp.name
            
            server_path = await self._upload_file(temp_path)
            
            # 2. Inference
            payload = [{"path": server_path, "meta": {"_type": "gradio.FileData"}}, threshold]
            result_list = await self._call_api("detect_part", payload)
            
            if not result_list or len(result_list) < 5:
                raise ProcessingError(f"Model returned incomplete result set (len={len(result_list)})")
            
            # Parse Gradio 5-tuple: [markdown, label_dict, vis_img, attn_img, edge_img]
            status_text = result_list[0]
            label_data  = result_list[1]
            vis_data    = result_list[2]
            
            # 3. Decision Logic (The 70% Confidence Gate)
            confidence = 0.0
            best_match = "UNKNOWN"
            
            if isinstance(label_data, dict) and "confidences" in label_data:
                # Extract highest confidence from label component
                conf_entries = label_data["confidences"]
                if conf_entries:
                    top_entry = max(conf_entries, key=lambda x: x.get("confidence", 0))
                    confidence = top_entry.get("confidence", 0)
                    best_match = top_entry.get("label", "UNKNOWN")
            elif isinstance(label_data, dict) and "label" in label_data:
                # Fallback for simple label format
                best_match = label_data.get("label", "UNKNOWN")
                confidence = 1.0 # Boolean match if no confidence provided
                
            # 4. Semantic Validation
            status_lower = str(status_text).lower()
            critical_failures = ["no bolt holes", "localization failed", "insufficient hole", "unconfigured"]
            
            is_valid_detection = not any(fail in status_lower for fail in critical_failures)
            
            # Final confidence gate
            if not is_valid_detection or confidence < self.CONFIDENCE_THRESHOLD:
                logger.warning(f"Detection gated → valid={is_valid_detection}, conf={confidence:.2%}")
                best_match = "UNKNOWN"
                matched = False
            else:
                matched = True
                logger.info(f"Detection verified → {best_match} ({confidence:.2%})")

            # 5. Visualization Handling (Download for local processing)
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
            logger.error(f"Detection pipeline failed: {e}", exc_info=True)
            return {"success": False, "error": str(e), "matched": False, "confidence": 0.0}
            
        finally:
            # Local cleanup
            if temp_path and os.path.exists(temp_path):
                try: os.remove(temp_path)
                except: pass

    async def delete_template(self, name: str) -> Dict[str, Any]:
        """Removes a class cluster from the remote model."""
        try:
            result = await self._call_api("delete_class", [name])
            result_str = str(result[0]) if result else ""
            if "✅" in result_str:
                return {"success": True, "result": result_str}
            return {"success": False, "error": result_str}
        except Exception as e:
            logger.error(f"Deactivation failed for {name}: {e}")
            return {"success": False, "error": str(e)}

    async def list_classes(self) -> List[Dict[str, Any]]:
        """Queries the current registry of trained parts."""
        try:
            result = await self._call_api("list_classes", [])
            status_text = result[0] if result else ""
            
            classes = []
            # Parse the bulleted list from markdown
            for line in str(status_text).split("\n"):
                if "•" in line and ":" in line:
                    name = line.split("•", 1)[-1].split(":", 1)[0].strip()
                    if name:
                        classes.append({"name": name})
            return classes
        except Exception as e:
            logger.error(f"Class discovery failed: {e}")
            return []
