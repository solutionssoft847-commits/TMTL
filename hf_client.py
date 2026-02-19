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
                
                # Initialize client
                self._client = Client(self.space_url)
                logger.info(f"Connected to HF Space: {self.space_url}")
            except Exception as e:
                logger.error(f"Failed to connect to HF Space: {e}")
                return None
        return self._client

    async def save_template(self, name: str, images: List[Image.Image]) -> Dict[str, Any]:
        """Save a new part sample to a class cluster on HF Space"""
        if not self.client:
            return {"success": False, "error": "HF Client not initialized"}
        
        try:
            temp_dir = tempfile.gettempdir()
            
            # Send each image to add_sample endpoint
            last_result = None
            for i, img in enumerate(images):
                path = os.path.join(temp_dir, f"temp_sample_{name}_{i}.png")
                img.save(path)
                
                # Call the correct Gradio endpoint (add_sample)
                # Parameters in index.py: add_sample(image, class_name)
                last_result = self.client.predict(
                    image=handle_file(path),
                    class_name=name,
                    api_name="/add_sample"
                )
                
                # Clean up temp file
                try:
                    os.remove(path)
                except Exception:
                    pass
            
            logger.info(f"Template '{name}' added to HF Space cluster: {last_result}")
            return {"success": True, "result": last_result}
            
        except Exception as e:
            logger.error(f"Error saving template to HF: {e}")
            return {"success": False, "error": str(e)}

    async def list_classes(self) -> List[Dict[str, Any]]:
        """List all trained classes from the HF Space"""
        if not self.client:
            return []
        
        try:
            # list_classes returns (string_list, None_or_image)
            result = self.client.predict(api_name="/list_classes")
            
            # Result is a list/tuple: [text_list, roi_preview]
            status_text = result[0] if isinstance(result, (list, tuple)) else str(result)
            
            if isinstance(status_text, str):
                # Format: "Total: X class(es)\n───\n  • name: Y samples"
                classes = []
                for line in status_text.split('\n'):
                    line = line.strip()
                    if '•' in line and ':' in line:
                        name = line.split('•', 1)[-1].split(':', 1)[0].strip()
                        if name:
                            classes.append({"name": name})
                return classes
            return []
            
        except Exception as e:
            logger.error(f"Error listing classes from HF: {e}")
            return []

    async def delete_template(self, name: str) -> Dict[str, Any]:
        """Delete a class cluster from the HF Space"""
        if not self.client:
            return {"success": False, "error": "HF Client not initialized"}
        
        try:
            # Call the delete_class endpoint we just added to index.py
            result = self.client.predict(
                class_name=name,
                api_name="/delete_class"
            )
            
            # Result is [status_text, roi_view]
            status_text = result[0] if isinstance(result, (list, tuple)) else str(result)
            
            if "✅" in status_text:
                logger.info(f"Template '{name}' deleted from HF Space")
                return {"success": True, "result": status_text}
            else:
                logger.warning(f"Failed to delete template '{name}' from HF: {status_text}")
                return {"success": False, "error": status_text}
                
        except Exception as e:
            logger.error(f"Error deleting template from HF: {e}")
            return {"success": False, "error": str(e)}

    async def detect_part(self, image: Image.Image, threshold: float = 0.70) -> Dict[str, Any]:
        """Run multi-stage detection on an image using the HF Space model"""
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
            
            # Call the detect_part endpoint
            # Returns [text_output, label_dict, vis, attn, edges]
            logger.info(f"Sending detection request (threshold={threshold}) to HF api_name='/detect_part'")
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
            status_text = result[0] if isinstance(result, (list, tuple)) else str(result)
            label_data = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else None
            vis_image = result[2] if isinstance(result, (list, tuple)) and len(result) > 2 else None
            
            confidence = 0.0
            best_match = None
            matched = False
            
            # Parse the new status text format
            raw_error = None
            if status_text:
                if "⚠️" in status_text or "❌" in status_text:
                    raw_error = status_text.strip()
                    logger.warning(f"Feature match warning from HF: {raw_error}")

                lines = status_text.split('\n')
                for line in lines:
                    # Handle "Cosine Similarity: 95.00%" or "**Cosine Similarity**: 95.00%"
                    if 'cosine similarity' in line.lower():
                        try:
                            val = line.rsplit(':', 1)[-1].strip()
                            val = val.replace('%', '').replace('*', '').replace('`', '').strip()
                            confidence = float(val) / 100.0
                        except Exception:
                            pass
                            
                    # Handle "Top Prediction: Perfect" or "**Top Prediction**: `Perfect`"
                    if 'top prediction' in line.lower():
                        try:
                            val = line.rsplit(':', 1)[-1].strip()
                            best_match = val.replace('*', '').replace('`', '').strip()
                        except Exception:
                            pass
                            
                    if 'CLASSIFIED AS' in line or '✅' in line:
                        matched = True
            
            # Priority to label_data (Gradio Label object)
            if isinstance(label_data, dict):
                # Gradio label dict looks like {"label": "class_name", "confidences": [{"label": "A", "value": 0.9}, ...]}
                best_match = label_data.get('label', best_match)
                conf_list = label_data.get('confidences', [])
                if conf_list:
                    max_conf = 0.0
                    for c in conf_list:
                        # value is standard for Label component
                        conf_val = c.get('value', c.get('confidence', 0.0))
                        if conf_val > max_conf:
                            max_conf = conf_val
                    confidence = max(confidence, max_conf)
            
            # If we have an error but no match, report it as the best match info
            if not matched and raw_error:
                best_match = raw_error if not best_match else f"{best_match} ({raw_error})"

            logger.info(f"Multi-Stage Result - Predicted: {best_match}, Confidence: {confidence:.2%}")
            
            return {
                "success": True,
                "matched": matched,
                "confidence": confidence,
                "best_match": best_match,
                "status_text": status_text,
                "all_results": status_text,
                "visualization": vis_image
            }
            
        except Exception as e:
            logger.error(f"Error during detection on HF: {e}")
            return {
                "success": False,
                "error": str(e),
                "matched": False,
                "confidence": 0.0
            }
