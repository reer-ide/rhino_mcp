"""Tools for interacting with Grasshopper through socket connection."""
from mcp.server.fastmcp import FastMCP, Context, Image
import logging
from typing import Dict, Any, List, Optional
import json
import socket
import time
import base64
import io
from PIL import Image as PILImage
import requests
from urllib3.exceptions import InsecureRequestWarning
import urllib3

# Disable insecure HTTPS warnings
urllib3.disable_warnings(InsecureRequestWarning)

# Configure logging
logger = logging.getLogger("GrasshopperTools")

class GrasshopperConnection:
    def __init__(self, host='localhost', port=9999):  # Using port 9999 to match gh_socket_server.py
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.timeout = 30.0  # 30 second timeout
    
    def check_server_available(self) -> bool:
        """Check if the Grasshopper server is running and available.
        
        Returns:
            bool: True if the server is available, False otherwise
        """
        try:
            response = requests.get(self.base_url, timeout=2.0)
            response.raise_for_status()
            logger.info("Grasshopper server is available at {0}".format(self.base_url))
            return True
        except Exception as e:
            logger.warning("Grasshopper server is not available: {0}".format(str(e)))
            return False
    
    def connect(self):
        """Connect to the Grasshopper script's HTTP server"""
        # Check if server is available
        if not self.check_server_available():
            raise Exception("Grasshopper server not available at {0}. Make sure the GHPython component is running and the toggle is set to True.".format(self.base_url))
        logger.info("Connected to Grasshopper server")
    
    def disconnect(self):
        """No need to disconnect for HTTP connections"""
        pass
    
    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to the Grasshopper script and wait for response"""
        try:
            # Special handling for execute_code command
            if command_type == "execute_code" and isinstance(params, dict) and "code" in params:
                data = {
                    "type": command_type,
                    "code": params["code"]
                }
            else:
                data = {
                    "type": command_type,
                    "params": params or {}
                }

            logger.info("Sending command to Grasshopper: {0}".format(data))
            
            # Use a session to handle connection properly
            with requests.Session() as session:
                response = session.post(
                    self.base_url,
                    json=data,
                    timeout=self.timeout,
                    headers={'Content-Type': 'application/json'},
                    stream=True  # Use streaming to ensure proper connection handling
                )
                response.raise_for_status()
                
                # Read the response content
                result = response.json()
                logger.info("Received response from Grasshopper: {0}".format(result))
                
                # Check for error response
                if result.get("status") == "error":
                    raise Exception(result.get("message", "Unknown error"))
                    
                return result
                
        except Exception as e:
            error_msg = "Error communicating with Grasshopper script: {0}".format(str(e))
            logger.error(error_msg)
            raise

# Global connection instance
_grasshopper_connection = None

def get_grasshopper_connection() -> GrasshopperConnection:
    """Get or create the Grasshopper connection"""
    global _grasshopper_connection
    if _grasshopper_connection is None:
        _grasshopper_connection = GrasshopperConnection()
    return _grasshopper_connection

class GrasshopperTools:
    """Collection of tools for interacting with Grasshopper."""
    
    def __init__(self, app):
        self.app = app
        self._register_tools()
    
    def _register_tools(self):
        """Register all Grasshopper tools with the MCP server."""
        self.app.tool()(self.is_server_available)
        self.app.tool()(self.execute_code_in_gh)
        self.app.tool()(self.get_gh_context)
    
    def is_server_available(self, ctx: Context) -> bool:
        """Check if the Grasshopper server is available.
        
        This is a quick check to see if the Grasshopper socket server is running
        and available for connections.
        
        Returns:
            bool: True if the server is available, False otherwise
        """
        try:
            connection = get_grasshopper_connection()
            return connection.check_server_available()
        except Exception as e:
            logger.error("Error checking Grasshopper server availability: {0}".format(str(e)))
            return False
    

    def execute_code_in_gh(self, ctx: Context, code: str, description: str) -> str:
        """Execute arbitrary Python code in Grasshopper with a description.
        
        IMPORTANT: 
        - Uses IronPython 2.7 - no f-strings or modern Python features
        - Always include ALL required imports in your code
        - Use 'result = value' to return data (don't use return statements)
        
        Example - Adding components to canvas:
        ```python
        import scriptcontext as sc
        import clr
        import Rhino
        import System.Drawing as sd
        import Grasshopper
        import Grasshopper.Kernel.Special as GHSpecial

        doc = ghenv.Component.OnPingDocument()
        
        # Create and position a Pipeline
        pipe = GHSpecial.GH_GeometryPipeline()
        if pipe.Attributes is None: pipe.CreateAttributes()
        pipe.Attributes.Pivot = sd.PointF(100, 100)
        doc.AddObject(pipe, False)

        # Create and connect a Panel
        pan = GHSpecial.GH_Panel()
        if pan.Attributes is None: pan.CreateAttributes()
        pan.Attributes.Pivot = sd.PointF(300, 100)
        doc.AddObject(pan, False)
        pan.AddSource(pipe)
        
        result = "Components created successfully"
        ```
        
        Args:
            code: The Python code to execute
            description: A short description of what the code is doing
        
        Returns:
            The result of the code execution
        """
        try:
            # Make sure code ends with a result variable if it doesn't have one
            if "result =" not in code and "result=" not in code:
                # Extract the last line if it starts with "return"
                lines = code.strip().split("\n")
                if lines and lines[-1].strip().startswith("return "):
                    return_value = lines[-1].strip()[7:].strip() # Remove "return " prefix
                    # Replace the return with a result assignment
                    lines[-1] = "result = " + return_value
                    code = "\n".join(lines)
                else:
                    # Append a default result if no return or result is present
                    code += "\n\n# Auto-added result assignment\nresult = \"Code executed successfully\""
            
            logger.info("Sending code execution request to Grasshopper with description: {0}".format(description))
            connection = get_grasshopper_connection()
            
            # Use execute_code command type to match gh_socket_server.py
            result = connection.send_command("execute_code", {
                "code": code
            })
            
            logger.info("Received response from Grasshopper: {0}".format(result))
            
            # Error handling based on server response format
            if result.get("status") == "error":
                error_msg = "Error: {0}".format(result.get("result", "Unknown error"))
                logger.error("Code execution error: {0}".format(error_msg))
                return error_msg
            else:
                response = result.get("result", "Code executed successfully")
                logger.info("Code execution successful: {0}".format(response))
                return response
                
        except Exception as e:
            error_msg = "Error executing code: {0}".format(str(e))
            logger.error(error_msg)
            return error_msg

    def get_gh_context(self, ctx: Context, description: str) -> str:
        """Get current Grasshopper document state and Rhino canvas data.
        
        Returns a JSON string containing:
        - Component graph (connections between components)
        - Component info (guid, name, type)
        - Canvas state (selected objects, viewport)
        - ReplicateAI render settings

        Example response:
        ```json
        {
            "instanceGuid": "component_guid",
            "name": "Panel",
            "kind": "panel",
            "sources": ["source_guid1"], # inputs
            "targets": ["target_guid1"]  # outputs
        }
        ```
        
        Args:
            description: Why we're getting the context (e.g., "For automation")
        
        Returns:
            JSON string with component graph and canvas state
        """
        try:
            logger.info("Getting Grasshopper context with description: {0}".format(description))
            connection = get_grasshopper_connection()
            # Use get_context command type to match gh_socket_server.py
            result = connection.send_command("get_context", {
                "description": description
            })
            
            if result.get("status") == "error":
                error_msg = "Error: {0}".format(result.get("result", {}).get("error", "Unknown error"))
                logger.error("Context retrieval error: {0}".format(error_msg))
                return error_msg
            else:
                return json.dumps(result.get("result", {}).get("graph", {}), indent=2)
                
        except Exception as e:
            error_msg = "Error getting context: {0}".format(str(e))
            logger.error(error_msg)
            return error_msg
