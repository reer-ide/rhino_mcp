"""Rhino integration through the Model Context Protocol."""
from mcp.server.fastmcp import FastMCP, Context, Image
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional
from pathlib import Path

# Try to load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        logging.info(f"Loaded environment variables from {env_path}")
except ImportError:
    logging.warning("python-dotenv not installed. Install it to use .env files: pip install python-dotenv")

# Import our tool modules
from rhino_mcp.rhino_tools import RhinoTools, get_rhino_connection
# from rhino_mcp.grasshopper_tools import GrasshopperTools

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RhinoMCPServer")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    rhino_conn = None
    
    try:
        logger.info("RhinoMCP server starting up")
        
        # Try to connect to Rhino script
        try:
            rhino_conn = get_rhino_connection()
            rhino_conn.connect()
            logger.info("Successfully connected to Rhino")
        except Exception as e:
            logger.warning("Could not connect to Rhino: {0}".format(str(e)))

        yield {}
    finally:
        logger.info("RhinoMCP server shut down")
        
        # Clean up connections
        if rhino_conn:
            try:
                rhino_conn.disconnect()
                logger.info("Disconnected from Rhino")
            except Exception as e:
                logger.warning("Error disconnecting from Rhino: {0}".format(str(e)))

# Create the MCP server with lifespan support
mcp = FastMCP(
    "RhinoMCP",
    instructions="Rhino integration through the Model Context Protocol",
    lifespan=server_lifespan
)

# Initialize tool collections
rhino_tools = RhinoTools(mcp)
# grasshopper_tools = GrasshopperTools(mcp)

@mcp.prompt()
def rhino_creation_strategy() -> str:
    """Defines the preferred strategy for creating and managing objects in Rhino"""
    return """When working with Rhino through MCP, follow these guidelines:

    Especially when working with geometry, iterate with smaller steps and check the scene state from time to time.
    Act strategically with a long-term plan, think about how to organize the data and scene objects in a way that is easy to maintain and extend, by using layers and metadata (name, description),
    with the get_rhino_objects_with_metadata() function you can filter and select objects based on this metadata. You can access objects, and with the "type" attribute you can check their geometry type and
    access the geometry specific properties (such as corner points etc.) to create more complex scenes with spatial consistency. Start from sparse to detail (e.g. first the building plot, then the wall, then the window etc. - it is crucial to use metadata to be able to do that)

    1. Scene Context Awareness:
       - Always start by checking the scene using get_rhino_scene_info() for basic overview
       - Use the capture_rhino_viewport to get an image from viewport to get a quick overview of the scene
       - Use get_rhino_objects_with_metadata() for detailed object information and filtering
       - The short_id in metadata can be displayed in viewport using capture_rhino_viewport()

    2. Object Creation and Management:
       - When creating objects, ALWAYS call add_rhino_object_metadata() after creation (The add_rhino_object_metadata() function is provided in the code context)   
       - Use meaningful names for objects to help with you with later identification, organize the scenes with layers (but not too many layers)
       - Think about grouping objects (e.g. two planes that form a window)
    
    3. Always check the bbox for each item so that (it's stored as list of points in the metadata under the key "bbox"):
        - Ensure that all objects that should not be clipping are not clipping.
        - Items have the right spatial relationship.

    4. Code Execution:
       - This is Rhino 7 with IronPython 2.7 - no f-strings or modern Python features etc
       - rhinoscriptsyntax is already imported as rs
       - scriptcontext is already imported as sc
       - json is already imported as json
       - time is already imported as time
       - datetime is already imported as datetim
       - DONT FORGET NO f-strings! No f-strings, No f-strings!
       - Prefer automated solutions over user interaction, unless its requested or it makes sense or you struggle with errors
       - You can always use the look_up_RhinoScriptSyntax() function to look up the documentation for a RhinoScriptSyntax function directly from the Rhino3D developer website.

    5. Best Practices:
       - Always show the user the code you are executing, for example show the input to the execute_rhino_code() function in { `code`: `...`}   
       - Keep objects organized in appropriate layers
       - Use meaningful names and descriptions
       - Use viewport captures to verify visual results
       - When encouonter errors related to RhinoScriptSyntax, make sure to search the web for the correct syntax from the RhinoScriptSyntax API documentation
    """

@mcp.prompt()
def grasshopper_usage_strategy() -> str:
    """Defines the preferred strategy for working with Grasshopper through MCP"""
    return """When working with Grasshopper through MCP, follow these guidelines:
    Grasshooper is closely itnergrated with rhino, you can access rhino objects by referencing them, you can 
    see grasshopper generted geometry in rhino viewport.

    1. Connection Setup:
       - Always check if the Grasshopper server is available by using is_server_available()

    2. Definition Exploration:
       - Use get_definition_info() to get an overview of components and parameters in the definition

    4. Code Execution Guidelines:
       - Always use IronPython 2.7 compatible code (no f-strings, no walrus operator, etc.)
       - you can create grashopper componetns via code 
       - you can access rhino objects by referencing them

    """

def main():
    """Run the MCP server"""
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()