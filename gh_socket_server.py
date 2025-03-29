import scriptcontext as sc
import clr, socket, threading, Rhino, json
clr.AddReference("System")
clr.AddReference("System.Drawing")
clr.AddReference("Grasshopper")
from System import Action
from System.Drawing import RectangleF
import Grasshopper
import Rhino.Geometry as rg

class GHEncoder(json.JSONEncoder):
    """Custom JSON encoder for Grasshopper/Rhino types"""
    def default(self, obj):
        if isinstance(obj, rg.Point3d):
            return {
                "x": float(obj.X),
                "y": float(obj.Y),
                "z": float(obj.Z)
            }
        elif isinstance(obj, RectangleF):
            return {
                "x": float(obj.X),
                "y": float(obj.Y),
                "width": float(obj.Width),
                "height": float(obj.Height)
            }
        return json.JSONEncoder.default(self, obj)

# Use scriptcontext.sticky as a persistent dictionary.
if "command" not in sc.sticky:
    sc.sticky["command"] = None
if "server_running" not in sc.sticky:
    sc.sticky["server_running"] = False
if "last_result" not in sc.sticky:
    sc.sticky["last_result"] = None
if "server_thread" not in sc.sticky:
    sc.sticky["server_thread"] = None

def get_param_info(param, parent_component=None):
    """Get information about a Grasshopper parameter."""
    try:
        bounds_rect = RectangleF(
            param.Attributes.Bounds.X, 
            (param.Attributes.Bounds.Y * -1) - param.Attributes.Bounds.Height, 
            param.Attributes.Bounds.Width, 
            param.Attributes.Bounds.Height
        )
        pivot_pt = rg.Point3d(param.Attributes.Pivot.X, param.Attributes.Pivot.Y * -1, 0)
        
        param_info = {
            "instanceGuid": str(param.InstanceGuid),
            "componentGuid": str(parent_component) if parent_component else None,
            "bounds": bounds_rect,
            "pivot": pivot_pt,
            "dataMapping": str(param.DataMapping) if hasattr(param, 'DataMapping') else None,
            "dataType": str(param.TypeName) if hasattr(param, 'TypeName') else None,
            "simplify": str(param.Simplify) if hasattr(param, 'Simplify') else None,
            "computiationTime": float(param.ProcessorTime.Milliseconds),
            "name": param.Name,
            "nickName": param.NickName,
            "category": param.Category,
            "subCategory": param.SubCategory,
            "description": param.Description,
            "kind": str(param.Kind) if hasattr(param, 'Kind') else None,
            "dataCount": param.VolatileData.DataCount if hasattr(param, 'VolatileData') else None,
            "pathCount": param.VolatileData.PathCount if hasattr(param, 'VolatileData') else None,
            "sources": [],
            "targets": []
        }

        # Get sources (inputs)
        for src in param.Sources:
            try:
                param_info["sources"].append(str(src.InstanceGuid))
            except:
                pass

        # Get targets (outputs)
        for tgt in param.Recipients:
            try:
                param_info["targets"].append(str(tgt.InstanceGuid))
            except:
                pass

        return param_info
    except Exception as e:
        print("Error getting param info: " + str(e))
        return None

def get_grasshopper_context():
    """Get information about the current Grasshopper document and its components."""
    try:
        # Get the current Grasshopper document
        doc = ghenv.Component.OnPingDocument()
        if not doc:
            return {"error": "No active Grasshopper document"}

        # Initialize graph dictionary
        IO_graph = {}

        # Get all objects in the document
        for obj in doc.Objects:
            if isinstance(obj, Grasshopper.Kernel.IGH_Component):
                comp_instanceGuid = str(obj.InstanceGuid)
                comp_out = obj.Params.Output
                comp_in = obj.Params.Input
                
                # Get component kind with fallback
                try:
                    kind = str(obj.Kind) if hasattr(obj, 'Kind') else str(obj.__class__.__name__)
                except:
                    kind = str(obj.__class__.__name__)
                
                # Basic info for all components
                comp_info = {
                    "instanceGuid": comp_instanceGuid,
                    "name": obj.Name,
                    "nickName": obj.NickName,
                    "description": obj.Description,
                    "category": obj.Category,
                    "subCategory": obj.SubCategory,
                    "kind": kind,
                    "sources": [],
                    "targets": []
                }
                
                # Add additional info for non-standard components
                if kind != "component":
                    comp_info.update({
                        "componentGuid": None,
                        "bounds": RectangleF(
                            obj.Attributes.Bounds.X, 
                            (obj.Attributes.Bounds.Y * -1) - obj.Attributes.Bounds.Height, 
                            obj.Attributes.Bounds.Width, 
                            obj.Attributes.Bounds.Height
                        ),
                        "pivot": rg.Point3d(obj.Attributes.Pivot.X, obj.Attributes.Pivot.Y * -1, 0),
                        "dataMapping": None,
                        "dataType": None,
                        "simplify": None,
                        "computiationTime": float(obj.ProcessorTime.Milliseconds),
                        "dataCount": None,
                        "pathCount": None
                    })
                
                IO_graph[comp_instanceGuid] = comp_info

                # Process outputs
                for o in comp_out:
                    param_info = get_param_info(o, comp_instanceGuid)
                    if param_info:
                        IO_graph[param_info["instanceGuid"]] = param_info

                # Process inputs
                for o in comp_in:
                    param_info = get_param_info(o, comp_instanceGuid)
                    if param_info:
                        if comp_instanceGuid not in param_info["targets"]:
                            param_info["targets"].append(comp_instanceGuid)
                        IO_graph[param_info["instanceGuid"]] = param_info

            elif isinstance(obj, Grasshopper.Kernel.IGH_Param):
                param_info = get_param_info(obj)
                if param_info:
                    IO_graph[param_info["instanceGuid"]] = param_info

        # Fill in sources based on targets
        for node_id, node in IO_graph.items():
            for target_id in node["targets"]:
                if target_id in IO_graph and node_id not in IO_graph[target_id]["sources"]:
                    IO_graph[target_id]["sources"].append(node_id)

        return {
            "status": "success",
            "graph": IO_graph
        }
    except Exception as e:
        print("Error in get_grasshopper_context: " + str(e))
        return {"error": str(e)}

def receive_full_request(conn):
    """Receive the complete HTTP request."""
    data = b''
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
        if b'\r\n\r\n' in data:  # Found end of headers
            break
    return data.decode('utf-8')

def respond(conn, response_dict):
    """Send an HTTP response with JSON content and close the connection."""
    json_response = json.dumps(response_dict, cls=GHEncoder)
    http_response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: {}\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Connection: close\r\n"
        "\r\n"
        "{}"
    ).format(len(json_response), json_response)
    try:
        conn.sendall(http_response.encode('utf-8'))
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except:
            pass

def parse_command(data):
    """Parse the incoming command data into a structured format."""
    try:
        command_data = json.loads(data)
        if isinstance(command_data, dict):
            return command_data
        return {"type": "raw", "data": data}
    except json.JSONDecodeError:
        return {"type": "raw", "data": data}

def execute_code(code_str):
    """Execute Python code string and return the result."""
    try:
        # Create a new dictionary for local variables
        local_vars = {}
        
        # Execute the code with access to the current context
        exec(code_str, globals(), local_vars)
        
        # If there's a result variable defined, return it
        if 'result' in local_vars:
            return {"status": "success", "result": local_vars['result']}
        return {"status": "success", "result": "Code executed successfully"}
    except Exception as e:
        print("Code execution error: " + str(e))
        return {"status": "error", "result": str(e)}

def process_command(command_data):
    """Process a command and return the result."""
    command_type = command_data.get("type", "raw")
    if command_type == "raw":
        # Handle legacy raw text commands
        raw_data = command_data["data"]
        if raw_data == "fetch_new_data":
            return {"result": "Fetched new data!", "status": "success"}
        else:
            return {"result": "Unknown command: " + raw_data, "status": "error"}
    elif command_type == "test_command":
        # Handle test command with dummy response
        params = command_data.get("params", {})
        return {
            "status": "success",
            "result": {
                "message": "Test command executed successfully",
                "received_params": params,
                "dummy_data": {"value": 42, "text": "Hello from Grasshopper!"}
            }
        }
    elif command_type == "get_context":
        # Get Grasshopper context
        context = get_grasshopper_context()
        if "error" in context:
            return {"status": "error", "result": context}
        return {
            "status": "success",
            "result": context
        }
    elif command_type == "execute_code":
        # Execute Python code
        code = command_data.get("code", "")
        if not code:
            return {"status": "error", "result": "No code provided"}
        return execute_code(code)
    else:
        return {"result": "Unknown command type: " + command_type, "status": "error"}

def socket_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    host = "127.0.0.1"  # Bind to localhost
    port = 9999         # Use port 9999
    s.bind((host, port))
    s.listen(5)         # Allow up to 5 pending connections
    print("Socket server listening on {}:{}".format(host, port))
    
    while True:
        try:
            s.settimeout(1.0)  # Check for new connections every second.
            try:
                conn, addr = s.accept()
                conn.settimeout(5.0)  # Set timeout for receiving data
            except socket.timeout:
                continue
            
            try:
                full_data = receive_full_request(conn)
                if not full_data:
                    continue
                
                # Extract the payload from the HTTP request (ignoring headers)
                parts = full_data.split("\r\n\r\n")
                if len(parts) > 1:
                    command = parts[1].strip()
                else:
                    command = full_data.strip()
                
                # Parse the command into a structured format
                command_data = parse_command(command)
                print("Received command: " + str(command_data))

                # Handle stop command
                if command_data.get("type") == "stop":
                    print("Received stop command. Closing server.")
                    respond(conn, {"status": "stopping", "message": "Server is shutting down."})
                    conn.close()
                    break

                # Process command immediately and store result
                result = process_command(command_data)
                sc.sticky["last_result"] = result
                
                # Send response with result
                response = {
                    "status": result["status"],
                    "result": result["result"],
                    "command_type": command_data.get("type", "raw")
                }
                respond(conn, response)
            except Exception as e:
                print("Error handling request: " + str(e))
                error_response = {
                    "status": "error",
                    "result": str(e),
                    "command_type": "error"
                }
                respond(conn, error_response)
            finally:
                try:
                    conn.close()
                except:
                    pass
        except Exception as e:
            print("Socket server error: " + str(e))
            break
    s.close()
    sc.sticky["server_running"] = False
    print("Socket server closed.")

# Start the socket server if it isn't already running.
if not sc.sticky["server_running"]:
    sc.sticky["server_running"] = True
    thread = threading.Thread(target=socket_server)
    thread.daemon = True
    thread.start()

# Main SolveInstance processing:
if sc.sticky["last_result"]:
    result = sc.sticky["last_result"]
    sc.sticky["last_result"] = None  # Clear the result after processing
    A = "Last command result: " + json.dumps(result, cls=GHEncoder)  # Use custom encoder here too
else:
    A = "Waiting for command..."
 