import os
import io
import logging
import tempfile
from typing import List, Dict, Any
from PIL import Image
from gradio_client import Client, handle_file
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class HuggingFaceClient:
    def __init__(self):
        self.space_url = os.getenv("HF_SPACE_URL")
        self.hf_token = os.getenv("HF_TOKEN")
        self._client = None
        
    @property
    def client(self):
        if self._client is None:
            if not self.space_url:
                logger.warning("HF_SPACE_URL not set. HuggingFaceClient will be disabled.")
                return None
            try:
                self._client = Client(self.space_url, token=self.hf_token)
                logger.info(f"Connected to HF Space: {self.space_url}")
            except Exception as e:
                logger.error(f"Failed to connect to HF Space: {e}")
                return None
        return self._client

    async def save_template(self, name: str, images: List[Image.Image]) -> Dict[str, Any]:
        """Save a new part template to the HF Space"""
        if not self.client:
            return {"success": False, "error": "HF Client not initialized"}
        
        try:
            # Convert PIL images to paths/buffers that Gradio Client can handle
            temp_paths = []
            temp_dir = tempfile.gettempdir()
            for i, img in enumerate(images):
                path = os.path.join(temp_dir, f"temp_template_{i}.png")
                img.save(path)
                temp_paths.append(handle_file(path))
            
            # Call the Gradio endpoint 'save_template'
            result = self.client.predict(
                name=name,
                images=temp_paths,
                api_name="/save_template"
            )
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"Error saving template to HF: {e}")
            return {"success": False, "error": str(e)}

    async def list_templates(self) -> List[Dict[str, Any]]:
        """List all templates from the HF Space"""
        if not self.client:
            return []
        
        try:
            result = self.client.predict(api_name="/list_templates")
            return result # Assuming it returns a list of template info
        except Exception as e:
            logger.error(f"Error listing templates from HF: {e}")
            return []

    async def delete_template(self, name: str) -> bool:
        """Delete a template from the HF Space"""
        if not self.client:
            return False
        
        try:
            self.client.predict(name=name, api_name="/delete_template")
            return True
        except Exception as e:
            logger.error(f"Error deleting template from HF: {e}")
            return False

    async def detect_part(self, image: Image.Image, threshold: float = 0.7) -> Dict[str, Any]:
        """Run detection on an image using the HF Space model"""
        if not self.client:
            return {"success": False, "error": "HF Client not initialized", "matched": False, "confidence": 0.0}
        
        try:
            # Save PIL image to temp file for Gradio
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, "temp_scan.png")
            image.save(temp_path)
            
            result = self.client.predict(
                img=handle_file(temp_path),
                threshold=threshold,
                api_name="/predict"
            )
            
            # Expected result format based on main.py usage:
            # { "matched": bool, "confidence": float, "best_match": str, "all_results": list }
            return result
        except Exception as e:
            logger.error(f"Error during detection on HF: {e}")
            return {"success": False, "error": str(e), "matched": False, "confidence": 0.0}