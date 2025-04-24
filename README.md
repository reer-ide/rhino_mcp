# RhinoMCP - Rhino Model Context Protocol Integration

RhinoMCP connects Rhino, Grasshopper and more to Claude AI through the Model Context Protocol (MCP), allowing Claude to directly interact with and control Rhino. This integration enables prompt-assisted 3D modeling, scene creation, and manipulation. (inspired by [blender_mcp](https://github.com/ahujasid/blender-mcp))

## Features

#### Rhino

- **Two-way communication**: Connect Claude AI to Rhino through a socket-based server
- **Object manipulation and management**: Create and modify 3D objects in Rhino including metadata
- **Layer management**: View and interact with Rhino layers
- **Scene inspection**: Get detailed information about the current Rhino scene (incl. screencapture)
- **Code execution**: Run arbitrary Python code in Rhino from Claude

#### Grasshopper

- **Code execution**: Run arbitrary Python code in Grasshopper from Claude - includes the generation of gh components
- **Gh canvas inspection**: give the LLM an Idea of your grasshopper code - or ask it about your code.
- **non-blocking two-way communication**: .. via a ghpython script

note: this is not very stable right now

## Components

The system consists of two main components:

1. **Rhino-side Script (`rhino_script.py`)**: A Python script that runs inside Rhino to create a socket server that receives and executes commands
2. **MCP Server (`rhino_mcp/server.py`)**: A Python server that implements the Model Context Protocol and connects to the Rhino script

## Installation

### Prerequisites

- Rhino 7 or newer
- Python 3.10 or newer
- Conda (for environment management)

### Setting up the Python Environment

1. Create a new conda environment with Python 3.10:

   ```bash
   conda create -n rhino_mcp python=3.10
   conda activate rhino_mcp
   ```

2. Install the `uv` package manager:

   ```bash
   pip install uv
   ```

3. Install the package in development mode:
   ```bash
   uv pip install -e .
   ```

### Installing the Rhino-side Script

1. Open Rhino 7
2. Open the Python Editor:
   - Click on the "Tools" menu
   - Select "Python Editor" (or press Ctrl+Alt+P / Cmd+Alt+P)
3. In the Python Editor:
   - Click "File" > "Open"
   - Navigate to and select `rhino_script.py`
   - Click "Run" (or press F5)
4. The script will start automatically and you should see these messages in the Python Editor:
   ```
   RhinoMCP script loaded. Server started automatically.
   To stop the server, run: stop_server()
   ```

### Running the MCP Server

The MCP server will be started automatically by Claude Desktop using the configuration in `claude_desktop_config.json`. You don't need to start it manually.

### Starting the Connection

1. First, start the Rhino script:

   - Open Rhino 7
   - Open the Python Editor
   - Open and run `rhino_script.py`
   - Verify you see the startup messages in the Python Editor

2. Then start Claude Desktop:
   - It will automatically start the MCP server when needed
   - The connection between Claude and Rhino will be established automatically

### Managing the Connection

- To stop the Rhino script server:
  - In the Python Editor, type `stop_server()` and press Enter
  - You should see "RhinoMCP server stopped" in the outputt

### Claude Integration

To integrate with Claude Desktop:

1. Go to Claude Desktop > Settings > Developer > Edit Config
2. Open the `claude_desktop_config.json` file and add the following configuration:

```json
{
  "mcpServers": {
    "rhino": {
      "command": "/Users/Joo/miniconda3/envs/rhino_mcp/bin/python",
      "args": ["-m", "rhino_mcp.server"]
    }
  }
}
```

Make sure to:

- Replace the Python path with the path to Python in your conda environment
- Save the file and restart Claude Desktop

> **Important Note:** If you're using a conda environment, you must specify the full path to the Python interpreter as shown above. Using the `uvx` command might not work properly with conda environments.

### Grasshopper Integration(wip)

## Usage

### Using with Claude

Once connected, Calude or another LLM can use the following MCP tools:

- `get_scene_info()`: Get simplified scene information focusing on layers and example objects
- `get_layers()`: Get information about all layers in the Rhino scene
- `execute_code(code)`: Execute arbitrary Python code in Rhino
- `get_objects_with_metadata(filters, metadata_fields)`: Get detailed information about objects in the scene with their metadata, with optional filtering
- `capture_viewport(layer, show_annotations, max_size)`: Capture the viewport with optional annotations and layer filtering

### MCP Inspector

1. Runing following command in cmd

- `npx @modelcontextprotocol/inspector`

2. Select Transport Type such as SSE or Stdio
3. For SSE mcp server, you should start the server manually then connect the port accordingly in the mcp inspector -
   - Sample URL of SSE Server http://localhost:8080/sse
   - Sample URL of Stdio Server http://localhost:8080

### Example Commands

Here are some examples of what you can ask Claude to do:

- "Get information about the current Rhino scene"
- "Create a cube at the origin"
- "Get all layers in the Rhino document"
- "Execute this Python code in Rhino: ..."

## Extending

To add new functionality, you need to:

1. Add new command handlers and functions in `rhino_script.py` and the `RhinoMCPServer` class.
2. Add corresponding MCP tools in `server.py` that include tool and arg descriptions

## Relevant Documentation and Resources

- MCP offical Documentation :
  - Client Developer: https://modelcontextprotocol.io/quickstart/client
  - Server Developer: https://modelcontextprotocol.io/quickstart/server
- Open Source MCP Documentation: https://github.com/cyanheads/model-context-protocol-resources
  - Client Developer: https://github.com/cyanheads/model-context-protocol-resources/blob/main/guides/mcp-client-development-guide.md
  - Server Developer: https://github.com/cyanheads/model-context-protocol-resources/blob/main/guides/mcp-server-development-guide.md
- Open web UI for building AI agent interface:https://github.com/open-webui/open-webui
- Switch between Stdio Server and SSE server:https://github.com/supercorp-ai/supergateway
