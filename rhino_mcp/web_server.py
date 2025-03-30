from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from rhino_mcp.rhino_tools import RhinoTools, RhinoConnection
from typing import Dict, Any
import logging
import json
import argparse

# configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebServer")

# create FastAPI app
app = FastAPI()

# allow cross-domain requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# create MCP instance and tools
mcp = FastMCP("RhinoMCP")
rhino_tools = RhinoTools(mcp)

# add strategy
@mcp.prompt()
def rhino_creation_strategy() -> str:
    """Defines the preferred strategy for creating and managing objects in Rhino"""
    return """When working with Rhino through MCP, follow these guidelines:

    Especially when working with geometry, iterate with smaller steps and check the scene state from time to time.
    Act strategically with a long-term plan, think about how to organize the data and scene objects in a way that is easy to maintain and extend, by using layers and metadata (name, description),
    with the get_objects_with_metadata() function you can filter and select objects based on this metadata. You can access objects, and with the "type" attribute you can check their geometry type and
    access the geometry specific properties (such as corner points etc.) to create more complex scenes with spatial consistency. Start from sparse to detail (e.g. first the building plot, then the wall, then the window etc. - it is crucial to use metadata to be able to do that)

    1. Scene Context Awareness:
       - Always start by checking the scene using get_scene_info() for basic overview
       - Use the capture_viewport to get an image from viewport to get a quick overview of the scene
       - Use get_objects_with_metadata() for detailed object information and filtering
       - The short_id in metadata can be displayed in viewport using capture_viewport()

    2. Object Creation and Management:
       - When creating objects, ALWAYS call add_object_metadata() after creation (The add_object_metadata() function is provided in the code context)   
       - Use meaningful names for objects to help with you with later identification, organize the scenes with layers (but not too many layers)
       - Think about grouping objects (e.g. two planes that form a window)
    
    3. Always check the bbox for each item so that (it's stored as list of points in the metadata under the key "bbox"):
            - Ensure that all objects that should not be clipping are not clipping.
            - Items have the right spatial relationship.

    4. Code Execution:
       - This is Rhino 7 with IronPython 2.7 - no f-strings or modern Python features etc
       - DONT FORGET NO f-strings! No f-strings, No f-strings!
       - Prefer automated solutions over user interaction, unless its requested or it makes sense or you struggle with errors
       - You can use rhino command syntax to ask the user questions e.g. "should i do "A" or "B"" where A,B are clickable options

    5. Best Practices:
       - Keep objects organized in appropriate layers
       - Use meaningful names and descriptions
       - Use viewport captures to verify visual results
    """

# @mcp.prompt()
# def grasshopper_usage_strategy() -> str:
#     """Defines the preferred strategy for working with Grasshopper through MCP"""
#     return """When working with Grasshopper through MCP, follow these guidelines:
#     1. Connection Setup:
#        - Always check if the Grasshopper server is available
#     2. Definition Exploration:
#        - Use get_definition_info() for overview
#     3. Code Execution:
#        - Use IronPython 2.7 compatible code
#        - Can create grasshopper components via code
#        - Can access rhino objects by reference
#     """

# HTTP endpoint
@app.post("/rhino/command")
async def execute_command(command: Dict[str, Any]):
    """execute Rhino command"""
    try:
        result = rhino_tools.execute_command(command)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Command execution error: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/rhino/scene")
async def get_scene():
    """get scene info"""
    try:
        scene_info = rhino_tools.get_scene_info()
        return {"status": "success", "data": scene_info}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/rhino/strategy")
async def get_strategy():
    """get Rhino strategy"""
    return {
        "rhino_strategy": rhino_creation_strategy(),
        "grasshopper_strategy": grasshopper_usage_strategy()
    }

# WebSocket endpoint
@app.websocket("/rhino/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    rhino_conn = RhinoConnection(port=9876)
    
    try:
        # connect to Rhino
        rhino_conn.connect()
        logger.info("Connected to Rhino socket server")
        
        # send initial connection success message
        await websocket.send_json({
            "status": "connected",
            "message": "Connected to Rhino socket server"
        })
        
        # main message loop
        while True:
            try:
                # wait for message
                data = await websocket.receive_json()
                logger.info(f"Received command: {data}")
                
                # send command to Rhino
                result = rhino_conn.send_command(data["type"], data.get("params", {}))
                
                # send result
                await websocket.send_json({
                    "status": "success",
                    "data": result
                })
                
            except json.JSONDecodeError:
                await websocket.send_json({
                    "status": "error",
                    "message": "Invalid JSON format"
                })
            except Exception as e:
                logger.error(f"Command execution error: {str(e)}")
                await websocket.send_json({
                    "status": "error",
                    "message": str(e)
                })
                
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        try:
            await websocket.send_json({
                "status": "error",
                "message": f"Connection error: {str(e)}"
            })
        except:
            pass
            
    finally:
        # clean up connection
        try:
            rhino_conn.disconnect()
            logger.info("Disconnected from Rhino socket server")
            await websocket.close()
        except:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000, help="Web server port")
    parser.add_argument("--host", type=str, default="localhost", help="Web server host")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port) 