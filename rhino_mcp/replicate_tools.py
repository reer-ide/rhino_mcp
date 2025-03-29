"""Tools for interacting with Replicate's Flux Depth model."""
import os
import requests
import base64
import io
import time
import logging
from mcp.server.fastmcp import Context, Image
from PIL import Image as PILImage

logger = logging.getLogger("ReplicateTools")

class ReplicateTools:
    def __init__(self, app):
        self.app = app
        self.api_token = os.environ.get('REPLICATE_API_TOKEN') or os.environ.get('REPLICATE_TOKEN')
        if not self.api_token:
            logger.warning("No Replicate API token found in environment")
        self.app.tool()(self.render_rhino_scene)
    
    def render_rhino_scene(self, ctx: Context, prompt: str) -> Image:
        """Transform Rhino viewport with AI using the given prompt, ensure to display the result image in chat afterwads"
        
        Args:
            prompt: A prompt to guide the rendering of the scene
        
        Returns:
            An MCP Image object containing the rendered scene
        """
        try:
            # Get Rhino viewport image
            from .rhino_tools import get_rhino_connection
            connection = get_rhino_connection()
            result = connection.send_command("capture_viewport", {
                "layer": None, 
                "show_annotations": False,
                "max_size": 800
            })
            
            if result.get("type") != "image":
                return "Error: Failed to capture viewport"
                
            # Get base64 data and prepare request
            base64_data = result["source"]["data"]
            headers = {
                "Authorization": f"Token {self.api_token}",
                "Content-Type": "application/json",
            }
            
            # Start prediction
            response = requests.post(
                "https://api.replicate.com/v1/predictions",
                json={
                    "version": "black-forest-labs/flux-depth-dev",
                    "input": {
                        "prompt": prompt,
                        "control_image": f"data:image/jpeg;base64,{base64_data}"
                    }
                },
                headers=headers
            )
            prediction = response.json()
            prediction_url = prediction["urls"]["get"]
            
            # Poll until complete (max 60 seconds)
            for _ in range(30):
                time.sleep(2)
                response = requests.get(prediction_url, headers=headers)
                prediction = response.json()
                
                # Check if complete
                if prediction["status"] == "succeeded" and prediction.get("output"):
                    # Get image URL and download it
                    image_url = prediction["output"]
                    if isinstance(image_url, list):
                        image_url = image_url[0]
                        
                    # Download and convert to MCP Image
                    image_data = requests.get(image_url).content
                    img = PILImage.open(io.BytesIO(image_data))
                    
                    # Resize to max 800px while maintaining aspect ratio
                    max_size = 800
                    if img.width > max_size or img.height > max_size:
                        ratio = max_size / max(img.width, img.height)
                        new_size = (int(img.width * ratio), int(img.height * ratio))
                        img = img.resize(new_size, PILImage.Resampling.LANCZOS)
                    
                    # Save with controlled quality
                    buffer = io.BytesIO()
                    img.save(buffer, format="JPEG", quality=70, optimize=True)
                    return Image(data=buffer.getvalue(), format="jpeg")
                    
                # Check for errors
                if prediction["status"] not in ["processing", "starting"]:
                    return f"Error: Model failed with status {prediction['status']}"
                    
            return "Error: Prediction timed out"
            
        except Exception as e:
            return f"Error: {str(e)}" 