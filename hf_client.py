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
        """Lazy client initialization"""
        if self._client is None:
            if not self.space_url:
                logger.warning("HF_SPACE_URL not set. HuggingFaceClient will be disabled.")
                return None
            try:
                # Set HF token as environment variable if provided
                if self.hf_token:
                    os.environ["HF_TOKEN"] = self.hf_token
                
                # Initialize client without hf_token parameter
                self._client = Client(self.space_url)
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
            
            # Send each image to add_template endpoint
            last_result = None
            for i, img in enumerate(images):
                path = os.path.join(temp_dir, f"temp_template_{name}_{i}.png")
                img.save(path)
                
                # Call the correct Gradio endpoint
                last_result = self.client.predict(
                    image=handle_file(path),
                    part_name=name,
                    api_name="/add_template"
                )
                
                # Clean up temp file
                try:
                    os.remove(path)
                except Exception:
                    pass
            
            logger.info(f"Template '{name}' saved to HF Space: {last_result}")
            return {"success": True, "result": last_result}
            
        except Exception as e:
            logger.error(f"Error saving template to HF: {e}")
            return {"success": False, "error": str(e)}

    async def list_templates(self) -> List[Dict[str, Any]]:
        """List all templates from the HF Space"""
        if not self.client:
            return []
        
        try:
            # The list_templates function in your Gradio app returns a string
            result = self.client.predict(api_name="/list_templates")
            
            # Parse the string result
            if isinstance(result, str):
                # Format: "- template1\n- template2\n..."
                templates = []
                for line in result.split('\n'):
                    line = line.strip()
                    if line.startswith('- '):
                        name = line[2:].strip()
                        if name and name != "No templates saved yet":
                            templates.append({"name": name})
                return templates
            return []
            
        except Exception as e:
            logger.error(f"Error listing templates from HF: {e}")
            return []

    async def delete_template(self, name: str) -> bool:
        """Delete a template from the HF Space"""
        # Your Gradio app doesn't have a delete endpoint
        logger.warning(f"Delete template '{name}' - endpoint not implemented on HF Space")
        return True

    async def detect_part(self, image: Image.Image, threshold: float = 0.92) -> Dict[str, Any]:
        """Run detection on an image using the HF Space model"""
        if not self.client:
            return {
                "success": False, 
                "error": "HF Client not initialized", 
                "matched": False, 
                "confidence": 0.0
            }
        
        try:
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, "temp_scan.png")
            image.save(temp_path)
            
            # Call the detect endpoint - returns [text_output, label]
            result = self.client.predict(
                image=handle_file(temp_path),
                threshold=threshold,
                api_name="/detect_part"
            )
            
            # Clean up temp file
            try:
                os.remove(temp_path)
            except Exception:
                pass
            
            # Parse result
            # result is a tuple/list: [text_output, label_output]
            status_text = result[0] if isinstance(result, (list, tuple)) else str(result)
            label_data = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else None
            
            # Extract confidence from text
            confidence = 0.0
            best_match = None
            matched = False
            
            # Parse the status text for confidence
            if status_text:
                lines = status_text.split('\n')
                for line in lines:
                    # Handle "Confidence: 95.00%" or "**Confidence**: 95.00%"
                    if 'confidence' in line.lower():
                        try:
                            # Use everything after the last colon
                            val = line.rsplit(':', 1)[-1].strip()
                            # Remove markdown and percent sign
                            val = val.replace('%', '').replace('*', '').replace('`', '').strip()
                            confidence = float(val) / 100.0
                        except Exception as e:
                            logger.debug(f"Failed to parse confidence from line '{line}': {e}")
                            
                    # Handle "Best Match: block" or "**Best Match**: `block`"
                    if 'match' in line.lower() and 'best' in line.lower():
                        try:
                            val = line.rsplit(':', 1)[-1].strip()
                            best_match = val.replace('*', '').replace('`', '').strip()
                        except Exception:
                            pass
                            
                    if 'MATCHED' in line or '✅' in line:
                        matched = True
            
            # Handle label data if it's a dict (Gradio Label object)
            if isinstance(label_data, dict):
                best_match = label_data.get('label', best_match)
                if 'confidences' in label_data and label_data['confidences']:
                    # Get the highest confidence
                    max_conf = 0.0
                    for c in label_data['confidences']:
                        conf_val = c.get('confidence', 0.0)
                        if conf_val > max_conf:
                            max_conf = conf_val
                            if not best_match or c.get('label') == best_match:
                                max_conf = conf_val
                    confidence = max(confidence, max_conf)
            
            logger.info(f"Detection result - Matched: {matched}, Confidence: {confidence:.2%}, Part: {best_match}")
            
            return {
                "success": True,
                "matched": matched,
                "confidence": confidence,
                "best_match": best_match,
                "status_text": status_text,
                "all_results": status_text
            }
            
        except Exception as e:
            logger.error(f"Error during detection on HF: {e}")
            return {
                "success": False,
                "error": str(e),
                "matched": False,
                "confidence": 0.0
            }