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
            temp_dir = tempfile.gettempdir()
            # The HF Space /add_template seems to take ONE image at a time
            # We will send the first one or loop if the space supports it.
            # Based on the API info, it's (image, part_name)
            
            last_result = None
            for i, img in enumerate(images):
                path = os.path.join(temp_dir, f"temp_template_{i}.png")
                img.save(path)
                
                # Call the Gradio endpoint '/add_template'
                last_result = self.client.predict(
                    image=handle_file(path),
                    part_name=name,
                    api_name="/add_template"
                )
            
            return {"success": True, "result": last_result}
        except Exception as e:
            logger.error(f"Error saving template to HF: {e}")
            return {"success": False, "error": str(e)}

    async def list_templates(self) -> List[Dict[str, Any]]:
        """List all templates from the HF Space"""
        if not self.client:
            return []
        
        try:
            result = self.client.predict(api_name="/list_templates")
            # Result is likely a string based on Textbox component
            # If it's a string, we return it as a list of one item for now or parse it
            if isinstance(result, str):
                return [{"name": name.strip()} for name in result.split(",") if name.strip()]
            return []
        except Exception as e:
            logger.error(f"Error listing templates from HF: {e}")
            return []

    async def delete_template(self, name: str) -> bool:
        """Delete a template from the HF Space"""
        # API info doesn't show a delete endpoint, skip for now
        logger.warning(f"Delete template '{name}' requested but endpoint not found on HF Space.")
        return True

    async def detect_part(self, image: Image.Image, threshold: float = 0.7) -> Dict[str, Any]:
        """Run detection on an image using the HF Space model"""
        if not self.client:
            return {"success": False, "error": "HF Client not initialized", "matched": False, "confidence": 0.0}
        
        try:
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, "temp_scan.png")
            image.save(temp_path)
            
            # /detect_part returns [Textbox, Label]
            # Label component usually returns a dict with 'label' and 'confidences'
            result = self.client.predict(
                image=handle_file(temp_path),
                threshold=threshold,
                api_name="/detect_part"
            )
            
            # result[0] is status text, result[1] is label data
            status_text = result[0] if isinstance(result, (list, tuple)) else str(result)
            label_data = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else {}
            
            best_match = label_data.get("label") if isinstance(label_data, dict) else None
            confidences = label_data.get("confidences", []) if isinstance(label_data, dict) else []
            
            # Find the confidence for the best match
            confidence = 0.0
            if confidences:
                for c in confidences:
                    if str(c.get("label")) == str(best_match):
                        confidence = c.get("confidence", 0.0)
                        break
            
            matched = "Perfect" in status_text or "Present" in status_text
            
            return {
                "success": True,
                "matched": matched,
                "confidence": confidence,
                "best_match": best_match,
                "status_text": status_text
            }
