#! python3
"""
Rhino MCP - Rhino-side Script
Handles communication with external MCP server and executes Rhino commands.
"""

import socket
import threading
import json
import time
import System
import Rhino
import scriptcontext as sc
import rhinoscriptsyntax as rs
import os
import platform
import traceback
import sys
import base64
from System.Drawing import Bitmap
from System.Drawing.Imaging import ImageFormat
from System.IO import MemoryStream
from datetime import datetime

# Grasshopper imports (will be available when Grasshopper is loaded)
try:
    from Grasshopper import Instances
    from Grasshopper.Kernel import GH_ComponentServer
    from System import Guid
    from System.Drawing import PointF
    # Import common Grasshopper component libraries
    import Grasshopper.Kernel.Parameters as Params
    import Grasshopper.Kernel.Special as Special
except ImportError:
    # Grasshopper not available, will be handled in functions
    Instances = None
    GH_ComponentServer = None
    Guid = None
    PointF = None
    Params = None
    Special = None

# Configuration
HOST = 'localhost'
PORT = 9876

# Add constant for annotation layer
ANNOTATION_LAYER = "MCP_Annotations"

VALID_METADATA_FIELDS = {
    'required': ['id', 'name', 'type', 'layer'],
    'optional': [
        'short_id',      # Short identifier (DDHHMMSS format)
        'created_at',    # Timestamp of creation
        'bbox',          # Bounding box coordinates
        'description',   # Object description
        'user_text'      # All user text key-value pairs
    ]
}

# Note: Component creation now uses dynamic lookup through Grasshopper's component server
# instead of hardcoded mappings. This is more robust and handles component name variations.

def get_log_dir():
    """Get the appropriate log directory based on the platform"""
    home_dir = os.path.expanduser("~")
    
    # Platform-specific log directory
    if platform.system() == "Darwin":  # macOS
        log_dir = os.path.join(home_dir, "Library", "Application Support", "RhinoMCP", "logs")
    elif platform.system() == "Windows":
        log_dir = os.path.join(home_dir, "AppData", "Local", "RhinoMCP", "logs")
    else:  # Linux and others
        log_dir = os.path.join(home_dir, ".rhino_mcp", "logs")
    
    return log_dir

def log_message(message):
    """Log a message to both Rhino's command line and log file"""
    # Print to Rhino's command line
    Rhino.RhinoApp.WriteLine(message)
    
    # Log to file
    try:
        log_dir = get_log_dir()
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        log_file = os.path.join(log_dir, "rhino_mcp.log")
        
        # Log platform info on first run
        if not os.path.exists(log_file):
            with open(log_file, "w") as f:
                f.write("=== RhinoMCP Log ===\n")
                f.write("Platform: {0}\n".format(platform.system()))
                f.write("Python Version: {0}\n".format(sys.version))
                f.write("Rhino Version: {0}\n".format(Rhino.RhinoApp.Version))
                f.write("==================\n\n")
        
        with open(log_file, "a") as f:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            f.write("[{0}] {1}\n".format(timestamp, message))
    except Exception as e:
        Rhino.RhinoApp.WriteLine("Failed to write to log file: {0}".format(str(e)))

class RhinoMCPServer:
    def __init__(self, host='localhost', port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None
    
    def start(self):
        if self.running:
            log_message("Server is already running on {0}:{1}".format(self.host, self.port))
            return
            
        self.running = True
        
        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            
            # Start server thread
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            log_message("RhinoMCP server started on {0}:{1}".format(self.host, self.port))
        except Exception as e:
            log_message("Failed to start server: {0}".format(str(e)))
            self.stop()
            
    def stop(self):
        self.running = False
        
        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        # Wait for thread to finish
        if self.server_thread:
            try:
                if self.server_thread.is_alive():
                    self.server_thread.join(timeout=1.0)
            except:
                pass
            self.server_thread = None
        
        log_message("RhinoMCP server stopped")
    
    def _server_loop(self):
        """Main server loop that accepts connections"""
        while self.running:
            try:
                client, addr = self.socket.accept()
                log_message("Client connected from {0}:{1}".format(addr[0], addr[1]))
                
                # Handle client in a new thread
                client_thread = threading.Thread(target=self._handle_client, args=(client,))
                client_thread.daemon = True
                client_thread.start()
                
            except Exception as e:
                if self.running:
                    log_message("Error accepting connection: {0}".format(str(e)))
                    time.sleep(0.5)
    
    def _handle_client(self, client):
        """Handle a client connection"""
        try:
            # Set socket buffer size
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 14485760)  # 10MB
            client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 14485760)  # 10MB
            
            while self.running:
                # Receive command with larger buffer
                data = client.recv(14485760)  # 10MB buffer
                if not data:
                    log_message("Client disconnected")
                    break
                    
                try:
                    command = json.loads(data.decode('utf-8'))
                    log_message("Received command: {0}".format(command))
                    
                    # Create a closure to capture the client connection
                    def execute_wrapper():
                        try:
                            response = self.execute_command(command)
                            response_json = json.dumps(response)
                            # Split large responses into chunks if needed
                            chunk_size = 14485760  # 10MB chunks
                            response_bytes = response_json.encode('utf-8')
                            for i in range(0, len(response_bytes), chunk_size):
                                chunk = response_bytes[i:i + chunk_size]
                                client.sendall(chunk)
                            log_message("Response sent successfully")
                        except Exception as e:
                            log_message("Error executing command: {0}".format(str(e)))
                            traceback.print_exc()
                            error_response = {
                                "status": "error",
                                "message": str(e)
                            }
                            try:
                                client.sendall(json.dumps(error_response).encode('utf-8'))
                            except Exception as e:
                                log_message("Failed to send error response: {0}".format(str(e)))
                                return False  # Signal connection should be closed
                        return True  # Signal connection should stay open
                    
                    # Use RhinoApp.Idle event for IronPython 2.7 compatibility
                    def idle_handler(sender, e):
                        if not execute_wrapper():
                            # If execute_wrapper returns False, close the connection
                            try:
                                client.close()
                            except:
                                pass
                        # Remove the handler after execution
                        Rhino.RhinoApp.Idle -= idle_handler
                    
                    Rhino.RhinoApp.Idle += idle_handler
                    
                except ValueError as e:
                    # Handle JSON decode error (IronPython 2.7)
                    log_message("Invalid JSON received: {0}".format(str(e)))
                    error_response = {
                        "status": "error",
                        "message": "Invalid JSON format"
                    }
                    try:
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except:
                        break  # Close connection on send error
                
        except Exception as e:
            log_message("Error handling client: {0}".format(str(e)))
            traceback.print_exc()
        finally:
            try:
                client.close()
            except:
                pass
    
    def execute_command(self, command):
        """Execute a command received from the client"""
        try:
            command_type = command.get("type")
            params = command.get("params", {})
            
            if command_type == "get_rhino_scene_info":
                return self._get_rhino_scene_info(params)
            elif command_type == "_rhino_create_cube":
                return self._create_cube(params)
            elif command_type == "get_rhino_layers":
                return self._get_rhino_layers()
            elif command_type == "execute_code":
                return self._execute_rhino_code(params)
            elif command_type == "get_rhino_objects_with_metadata":
                return self._get_rhino_objects_with_metadata(params)
            elif command_type == "capture_rhino_viewport":
                return self._capture_rhino_viewport(params)
            elif command_type == "add_rhino_object_metadata":
                return self._add_rhino_object_metadata(
                    params.get("object_id"), 
                    params.get("name"), 
                    params.get("description")
                )
            elif command_type == "get_rhino_selected_objects":
                return self._get_rhino_selected_objects(params)
            elif command_type == "grasshopper_add_components":
                return self._grasshopper_add_components(params)
            elif command_type == "grasshopper_get_definition_info":
                return self._grasshopper_get_definition_info()
            elif command_type == "grasshopper_run_solver":
                return self._grasshopper_run_solver(params)
            elif command_type == "grasshopper_clear_canvas":
                return self._grasshopper_clear_canvas()
            elif command_type == "grasshopper_list_available_components":
                return self._grasshopper_list_available_components()
            else:
                return {"status": "error", "message": "Unknown command type"}
                
        except Exception as e:
            log_message("Error executing command: {0}".format(str(e)))
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def _get_rhino_scene_info(self, params=None):
        """Get simplified scene information focusing on layers and example objects"""
        try:
            doc = sc.doc
            if not doc:
                return {
                    "status": "error",
                    "message": "No active document"
                }
            
            log_message("Getting simplified scene info...")
            layers_info = []

            # Get unit system information
            unit_system_code = rs.UnitSystem()
            unit_system_names = {
                0: "No unit system",
                1: "Microns",
                2: "Millimeters", 
                3: "Centimeters",
                4: "Meters",
                5: "Kilometers",
                6: "Microinches",
                7: "Mils",
                8: "Inches",
                9: "Feet",
                10: "Miles",
                11: "Custom Unit System",
                12: "Angstroms",
                13: "Nanometers",
                14: "Decimeters",
                15: "Dekameters",
                16: "Hectometers",
                17: "Megameters",
                18: "Gigameters",
                19: "Yards",
                20: "Printer point",
                21: "Printer pica",
                22: "Nautical mile",
                23: "Astronomical",
                24: "Lightyears",
                25: "Parsecs"
            }
            
            unit_system_name = unit_system_names.get(unit_system_code, "Unknown")
            
            for layer in doc.Layers:
                layer_objects = [obj for obj in doc.Objects if obj.Attributes.LayerIndex == layer.Index]
                example_objects = []
                
                for obj in layer_objects[:5]:  # Limit to 5 example objects per layer
                    try:
                        # Convert NameValueCollection to dictionary
                        user_strings = {}
                        if obj.Attributes.GetUserStrings():
                            for key in obj.Attributes.GetUserStrings():
                                user_strings[key] = obj.Attributes.GetUserString(key)
                        
                        obj_info = {
                            "id": str(obj.Id),
                            "name": obj.Name or "Unnamed",
                            "type": obj.Geometry.GetType().Name if obj.Geometry else "Unknown",
                            "metadata": user_strings  # Now using the converted dictionary
                        }
                        example_objects.append(obj_info)
                    except Exception as e:
                        log_message("Error processing object: {0}".format(str(e)))
                        continue
                
                layer_info = {
                    "full_path": layer.FullPath,
                    "object_count": len(layer_objects),
                    "is_visible": layer.IsVisible,
                    "is_locked": layer.IsLocked,
                    "example_objects": example_objects
                }
                layers_info.append(layer_info)
            
            response = {
                "status": "success",
                "unit_system": {
                    "code": unit_system_code,
                    "name": unit_system_name
                },
                "layers": layers_info
            }
            
            log_message("Simplified scene info collected successfully: {0}".format(json.dumps(response)))
            return response
            
        except Exception as e:
            log_message("Error getting simplified scene info: {0}".format(str(e)))
            return {
                "status": "error",
                "message": str(e),
                "layers": []
            }
    
    def _create_cube(self, params):
        """Create a cube in the scene"""
        try:
            size = float(params.get("size", 1.0))
            location = params.get("location", [0, 0, 0])
            name = params.get("name", "Cube")
            
            # Create cube using RhinoCommon
            box = Rhino.Geometry.Box(
                Rhino.Geometry.Plane.WorldXY,
                Rhino.Geometry.Interval(0, size),
                Rhino.Geometry.Interval(0, size),
                Rhino.Geometry.Interval(0, size)
            )
            
            # Move to specified location
            transform = Rhino.Geometry.Transform.Translation(
                location[0] - box.Center.X,
                location[1] - box.Center.Y,
                location[2] - box.Center.Z
            )
            box.Transform(transform)
            
            # Add to document
            id = sc.doc.Objects.AddBox(box)
            if id != System.Guid.Empty:
                obj = sc.doc.Objects.Find(id)
                if obj:
                    obj.Name = name
                    sc.doc.Views.Redraw()
                    return {
                        "status": "success",
                        "message": "Created cube with size {0}".format(size),
                        "id": str(id)
                    }
            
            return {"status": "error", "message": "Failed to create cube"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _get_rhino_layers(self):
        """Get information about all layers"""
        try:
            doc = sc.doc
            layers = []
            
            for layer in doc.Layers:
                layers.append({
                    "id": layer.Index,
                    "name": layer.Name,
                    "object_count": layer.ObjectCount,
                    "is_visible": layer.IsVisible,
                    "is_locked": layer.IsLocked
                })
            
            return {
                "status": "success",
                "layers": layers
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _execute_rhino_code(self, params):
        """Execute arbitrary Python code"""
        try:
            code = params.get("code", "")
            if not code:
                return {"status": "error", "message": "No code provided"}
            
            log_message("Executing code: {0}".format(code))
            
            # Create a list to store printed output
            printed_output = []
            
            # Override print function to capture output
            def custom_print(*args, **kwargs):
                output = " ".join(str(arg) for arg in args)
                printed_output.append(output)
                # Also print to Rhino's command line
                Rhino.RhinoApp.WriteLine(output)
            
            # Create execution environment with custom print in both global and local scope
            exec_globals = globals().copy()
            exec_globals['print'] = custom_print
            exec_globals['printed_output'] = printed_output
            
            local_dict = {'print': custom_print, 'printed_output': printed_output}
            
            try:
                # Execute the code with custom print in both scopes
                # To Do: Find a way to add the script running to the history
                exec(code, exec_globals, local_dict)
                
                # Get result from local_dict or use a default message
                result = local_dict.get("result", "Code executed successfully")
                log_message("Code execution completed. Result: {0}".format(result))
                
                response = {
                    "status": "success",
                    "result": str(result),
                    "printed_output": printed_output,  # Include captured print output
                    #"variables": {k: str(v)  k, v in local_dict.items() if not k.startswith('__')}
                }
                
                log_message("Sending response: {0}".format(json.dumps(response)))
                return response
                
            except Exception as e:
                # hint = "Did you use f-string formatting? You have to use IronPython here that doesn't support this."
                error_response = {
                    "status": "error",
                    "message": str(e),
                    "printed_output": printed_output  # Include any output captured before the error
                }
                log_message("Error: {0}".format(error_response))
                return error_response
                
        except Exception as e:
            # hint = "Did you use f-string formatting? You have to use IronPython here that doesn't support this."
            error_response = {
                "status": "error",
                "message": str(e),
            }
            log_message("System error: {0}".format(error_response))
            return error_response

    def _add_rhino_object_metadata(self, obj_id, name=None, description=None):
        """Add standardized metadata to an object"""
        try:
            import json
            import time
            from datetime import datetime
            
            # Generate short ID
            short_id = datetime.now().strftime("%d%H%M%S")
            
            # Get bounding box
            bbox = rs.BoundingBox(obj_id)
            bbox_data = [[p.X, p.Y, p.Z] for p in bbox] if bbox else []
            
            # Get object type
            obj = sc.doc.Objects.Find(obj_id)
            obj_type = obj.Geometry.GetType().Name if obj else "Unknown"
            
            # Standard metadata
            metadata = {
                "short_id": short_id,
                "created_at": time.time(),
                "layer": rs.ObjectLayer(obj_id),
                "type": obj_type,
                "bbox": bbox_data
            }
            
            # User-provided metadata
            if name:
                rs.ObjectName(obj_id, name)
                metadata["name"] = name
            else:
                # Auto-generate name if none provided
                auto_name = "{0}_{1}".format(obj_type, short_id)
                rs.ObjectName(obj_id, auto_name)
                metadata["name"] = auto_name
                
            if description:
                metadata["description"] = description
                
            # Store metadata as user text (convert bbox to string for storage)
            user_text_data = metadata.copy()
            user_text_data["bbox"] = json.dumps(bbox_data)
            
            # Add all metadata as user text
            for key, value in user_text_data.items():
                rs.SetUserText(obj_id, key, str(value))
                
            return {"status": "success"}
        except Exception as e:
            log_message("Error adding metadata: " + str(e))
            return {"status": "error", "message": str(e)}

    def _get_rhino_objects_with_metadata(self, params):
        """Get objects with their metadata, with optional filtering"""
        try:
            import re
            import json
            
            filters = params.get("filters", {})
            metadata_fields = params.get("metadata_fields")
            layer_filter = filters.get("layer")
            name_filter = filters.get("name")
            id_filter = filters.get("short_id")
            
            # Validate metadata fields
            all_fields = VALID_METADATA_FIELDS['required'] + VALID_METADATA_FIELDS['optional']
            if metadata_fields:
                invalid_fields = [f for f in metadata_fields if f not in all_fields]
                if invalid_fields:
                    return {
                        "status": "error",
                        "message": "Invalid metadata fields: " + ", ".join(invalid_fields),
                        "available_fields": all_fields
                    }
            
            objects = []
            
            for obj in sc.doc.Objects:
                obj_id = obj.Id
                
                # Apply filters
                if layer_filter:
                    layer = rs.ObjectLayer(obj_id)
                    pattern = "^" + layer_filter.replace("*", ".*") + "$"
                    if not re.match(pattern, layer, re.IGNORECASE):
                        continue
                    
                if name_filter:
                    name = obj.Name or ""
                    pattern = "^" + name_filter.replace("*", ".*") + "$"
                    if not re.match(pattern, name, re.IGNORECASE):
                        continue
                    
                if id_filter:
                    short_id = rs.GetUserText(obj_id, "short_id") or ""
                    if short_id != id_filter:
                        continue
                    
                # Build base object data with required fields
                obj_data = {
                    "id": str(obj_id),
                    "name": obj.Name or "Unnamed",
                    "type": obj.Geometry.GetType().Name,
                    "layer": rs.ObjectLayer(obj_id)
                }
                
                # Get user text data and parse stored values
                stored_data = {}
                for key in rs.GetUserText(obj_id):
                    value = rs.GetUserText(obj_id, key)
                    if key == "bbox":
                        try:
                            value = json.loads(value)
                        except:
                            value = []
                    elif key == "created_at":
                        try:
                            value = float(value)
                        except:
                            value = 0
                    stored_data[key] = value
                
                # Build metadata based on requested fields
                if metadata_fields:
                    metadata = {k: stored_data[k] for k in metadata_fields if k in stored_data}
                else:
                    metadata = {k: v for k, v in stored_data.items() 
                              if k not in VALID_METADATA_FIELDS['required']}
                
                # Only include user_text if specifically requested
                if not metadata_fields or 'user_text' in metadata_fields:
                    user_text = {k: v for k, v in stored_data.items() 
                               if k not in metadata}
                    if user_text:
                        obj_data["user_text"] = user_text
                
                # Add metadata if we have any
                if metadata:
                    obj_data["metadata"] = metadata
                    
                objects.append(obj_data)
            
            return {
                "status": "success",
                "count": len(objects),
                "objects": objects,
                "available_fields": all_fields
            }
            
        except Exception as e:
            log_message("Error filtering objects: " + str(e))
            return {
                "status": "error",
                "message": str(e),
                "available_fields": all_fields
            }

    def _capture_rhino_viewport(self, params):
        """Capture viewport with optional annotations and layer filtering"""
        try:
            layer_name = params.get("layer")
            show_annotations = params.get("show_annotations", True)
            max_size = params.get("max_size", 800)  # Default max dimension
            original_layer = rs.CurrentLayer()
            temp_dots = []

            if show_annotations:
                # Ensure annotation layer exists and is current
                if not rs.IsLayer(ANNOTATION_LAYER):
                    rs.AddLayer(ANNOTATION_LAYER, color=(255, 0, 0))
                rs.CurrentLayer(ANNOTATION_LAYER)
                
                # Create temporary text dots for each object
                for obj in sc.doc.Objects:
                    if layer_name and rs.ObjectLayer(obj.Id) != layer_name:
                        continue
                        
                    bbox = rs.BoundingBox(obj.Id)
                    if bbox:
                        pt = bbox[1]  # Use top corner of bounding box
                        short_id = rs.GetUserText(obj.Id, "short_id")
                        if not short_id:
                            short_id = datetime.now().strftime("%d%H%M%S")
                            rs.SetUserText(obj.Id, "short_id", short_id)
                        
                        name = rs.ObjectName(obj.Id) or "Unnamed"
                        text = "{0}\n{1}".format(name, short_id)
                        
                        dot_id = rs.AddTextDot(text, pt)
                        rs.TextDotHeight(dot_id, 8)
                        temp_dots.append(dot_id)
            
            try:
                view = sc.doc.Views.ActiveView
                memory_stream = MemoryStream()
                
                # Capture to bitmap
                bitmap = view.CaptureToBitmap()
                
                # Calculate new dimensions while maintaining aspect ratio
                width, height = bitmap.Width, bitmap.Height
                if width > height:
                    new_width = max_size
                    new_height = int(height * (max_size / width))
                else:
                    new_height = max_size
                    new_width = int(width * (max_size / height))
                
                # Create resized bitmap
                resized_bitmap = Bitmap(bitmap, new_width, new_height)
                
                # Save as JPEG (IronPython doesn't support quality parameter)
                resized_bitmap.Save(memory_stream, ImageFormat.Jpeg)
                
                bytes_array = memory_stream.ToArray()
                image_data = base64.b64encode(bytes(bytearray(bytes_array))).decode('utf-8')
                
                # Clean up
                bitmap.Dispose()
                resized_bitmap.Dispose()
                memory_stream.Dispose()
                
            finally:
                if temp_dots:
                    rs.DeleteObjects(temp_dots)
                rs.CurrentLayer(original_layer)
            
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_data
                }
            }
            
        except Exception as e:
            log_message("Error capturing viewport: " + str(e))
            if 'original_layer' in locals():
                rs.CurrentLayer(original_layer)
            return {
                "type": "text",
                "text": "Error capturing viewport: " + str(e)
            }

    def _get_rhino_selected_objects(self, params):
        """Get objects that are currently selected in Rhino, including subobjects"""
        try:            
            include_lights = params.get("include_lights", False)
            include_grips = params.get("include_grips", False)
            include_subobjects = params.get("include_subobjects", True)

            selected_objects = []
            
            # Handle subobject selections if enabled
            if include_subobjects:
                object_count = sc.doc.Objects.Count

                log_message("Checking {0} objects for both sub-objects and full-objects selection...".format(object_count))

                # Create GetObject for interactive selection
                go = Rhino.Input.Custom.GetObject()
                go.SetCommandPrompt("Select objects or subobjects (Enter when done)")
                go.SubObjectSelect = True  # Enable subobject selection
                go.DeselectAllBeforePostSelect = False
                go.EnableBottomObjectPreference = True  # Prefer edges over surfaces
                
                # Allow multiple selection
                result = go.GetMultiple(0, 0)  # min=0, max=0 means any number
                
                if result == Rhino.Input.GetResult.Object:
                    object_count = go.ObjectCount
                    if not object_count:
                        log_message("No objects selected")
                        return {
                            "status": "error",
                            "message": "No objects selected"
                        }
                    for i in range(object_count):
                        objref = go.Object(i)
                        obj = objref.Object()
                        
                        # Check if this is a subobject selection
                        component_index = objref.GeometryComponentIndex
                        
                        if component_index.ComponentIndexType != Rhino.Geometry.ComponentIndexType.InvalidType:
                            # This is a subobject selection
                            obj_id = obj.Id
                            
                            # Check if we already have this object in our list
                            existing_obj = None
                            for existing in selected_objects:
                                if existing["id"] == str(obj_id) and existing["selection_type"] == "subobject":
                                    existing_obj = existing
                                    break
                            
                            if existing_obj:
                                # Add to existing subobject list
                                existing_obj["subobjects"].append({
                                    "index": component_index.Index,
                                    "type": str(component_index.ComponentIndexType)
                                })
                            else:
                                # Create new entry
                                obj_data = {
                                    "id": str(obj_id),
                                    "name": obj.Name or "Unnamed",
                                    "type": obj.Geometry.GetType().Name if obj.Geometry else "Unknown",
                                    "layer": rs.ObjectLayer(obj_id),
                                    "selection_type": "subobject",
                                    "subobjects": [{
                                        "index": component_index.Index,
                                        "type": str(component_index.ComponentIndexType)
                                    }]
                                }
                                
                                # Get metadata
                                user_strings = {}
                                for key in rs.GetUserText(obj_id):
                                    user_strings[key] = rs.GetUserText(obj_id, key)
                                
                                if user_strings:
                                    obj_data["metadata"] = user_strings
                                    
                                selected_objects.append(obj_data)
                        else:
                            # This is a full object selection
                            obj_data = {
                                "id": str(obj.Id),
                                "name": obj.Name or "Unnamed",
                                "type": obj.Geometry.GetType().Name if obj.Geometry else "Unknown",
                                "layer": rs.ObjectLayer(obj.Id),
                                "selection_type": "full"
                            }
                            
                            # Get metadata
                            user_strings = {}
                            for key in rs.GetUserText(obj.Id):
                                user_strings[key] = rs.GetUserText(obj.Id, key)
                            
                            if user_strings:
                                obj_data["metadata"] = user_strings
                                
                            selected_objects.append(obj_data)
                
                go.Dispose()
            
            return {
                "status": "success",
                "count": len(selected_objects),
                "objects": selected_objects,
            }
            
        except Exception as e:
            log_message("Error getting selected objects: " + str(e))
            return {"status": "error", "message": str(e)}

    def _grasshopper_add_components(self, params):
        """Add components to the current Grasshopper definition"""
        try:
            components = params.get("components", [])
            if not components:
                return {"status": "error", "message": "No components specified"}
            
            # Get Grasshopper plugin
            gh = rs.GetPlugInObject('Grasshopper')
            if not gh:
                return {"status": "error", "message": "Grasshopper plugin not available"}
            
            if not gh.IsEditorLoaded():
                return {"status": "error", "message": "Grasshopper editor is not loaded"}
            
            if not Instances:
                return {"status": "error", "message": "Grasshopper Instances not available"}
            
            doc = Instances.ActiveCanvas.Document
            if not doc:
                return {"status": "error", "message": "No active Grasshopper document"}
            
            created_components = []
            component_objects = []
            
            # Create components using direct instantiation
            for i, comp_def in enumerate(components):
                comp_type = comp_def.get("type")
                position = comp_def.get("position", [100 + i * 100, 100])
                name = comp_def.get("name")
                
                try:
                    component = None
                    
                    # Create components based on type - using direct instantiation
                    if comp_type == "Number Slider" and Special:
                        component = Special.GH_NumberSlider()
                    elif comp_type == "Number" and Params:
                        component = Params.Param_Number()
                    elif comp_type == "Integer" and Params:
                        component = Params.Param_Integer()
                    elif comp_type == "Boolean" and Params:
                        component = Params.Param_Boolean()
                    elif comp_type == "Point" and Params:
                        component = Params.Param_Point()
                    elif comp_type == "Vector" and Params:
                        component = Params.Param_Vector()
                    elif comp_type == "Text" and Params:
                        component = Params.Param_String()
                    else:
                        # Try to create using Grasshopper plugin's component creation
                        gh = rs.GetPlugInObject('Grasshopper')
                        if gh and hasattr(gh, 'CreateComponent'):
                            try:
                                component = gh.CreateComponent(comp_type)
                            except:
                                pass
                    
                    if not component:
                        log_message("Unknown component type: {0}".format(comp_type))
                        continue
                    
                    # Set position
                    component.CreateAttributes()
                    if component.Attributes:
                        component.Attributes.Pivot = PointF(float(position[0]), float(position[1]))
                    
                    # Set custom name if provided
                    if name:
                        component.NickName = name
                    
                    # Add to document
                    doc.AddObject(component, False)
                    
                    created_components.append({
                        "index": i,
                        "type": comp_type,
                        "position": position,
                        "name": name or comp_type,
                        "id": str(component.InstanceGuid)
                    })
                    
                    component_objects.append(component)
                    
                except Exception as e:
                    log_message("Error creating component {0}: {1}".format(comp_type, str(e)))
                    continue
            
            # Handle connections
            for i, comp_def in enumerate(components):
                connections = comp_def.get("connections", [])
                if not connections or i >= len(component_objects):
                    continue
                    
                target_component = component_objects[i]
                
                for conn in connections:
                    try:
                        from_idx = conn.get("from_component", 0)
                        from_output = conn.get("from_output", 0)
                        to_input = conn.get("to_input", 0)
                        
                        if from_idx < len(component_objects):
                            source_component = component_objects[from_idx]
                            
                            # Connect components
                            if (hasattr(target_component, 'Params') and hasattr(source_component, 'Params') and
                                to_input < len(target_component.Params.Input) and 
                                from_output < len(source_component.Params.Output)):
                                target_component.Params.Input[to_input].AddSource(
                                    source_component.Params.Output[from_output]
                                )
                    except Exception as e:
                        log_message("Error connecting components: {0}".format(str(e)))
                        continue
            
            # Refresh canvas and run solver
            try:
                Instances.ActiveCanvas.Refresh()
                gh.RunSolver(True)
            except Exception as e:
                log_message("Error refreshing canvas or running solver: {0}".format(str(e)))
            
            return {
                "status": "success",
                "message": "Added {0} components to Grasshopper".format(len(created_components)),
                "components": created_components
            }
            
        except Exception as e:
            log_message("Error adding Grasshopper components: " + str(e))
            return {"status": "error", "message": str(e)}

    def _grasshopper_get_definition_info(self):
        """Get information about the current Grasshopper definition"""
        try:
            # Get Grasshopper plugin
            gh = rs.GetPlugInObject('Grasshopper')
            if not gh:
                return {"status": "error", "message": "Grasshopper plugin not available"}
            
            info = {
                "editor_loaded": gh.IsEditorLoaded(),
                "components": [],
                "component_count": 0
            }
            
            if gh.IsEditorLoaded() and Instances:
                
                doc = Instances.ActiveCanvas.Document
                if doc:
                    components_info = []
                    
                    for obj in doc.Objects:
                        if hasattr(obj, 'ComponentGuid'):
                            comp_info = {
                                "id": str(obj.InstanceGuid),
                                "type": obj.Name,
                                "nickname": obj.NickName,
                                "position": [obj.Attributes.Pivot.X, obj.Attributes.Pivot.Y] if obj.Attributes else [0, 0],
                                "input_count": len(obj.Params.Input) if hasattr(obj, 'Params') else 0,
                                "output_count": len(obj.Params.Output) if hasattr(obj, 'Params') else 0
                            }
                            components_info.append(comp_info)
                    
                    info["components"] = components_info
                    info["component_count"] = len(components_info)
            
            return {
                "status": "success",
                "info": info
            }
            
        except Exception as e:
            log_message("Error getting Grasshopper definition info: " + str(e))
            return {"status": "error", "message": str(e)}

    def _grasshopper_run_solver(self, params):
        """Run the Grasshopper solver"""
        try:
            force_update = params.get("force_update", True)
            
            # Get Grasshopper plugin
            gh = rs.GetPlugInObject('Grasshopper')
            if not gh:
                return {"status": "error", "message": "Grasshopper plugin not available"}
            
            if not gh.IsEditorLoaded():
                return {"status": "error", "message": "Grasshopper editor is not loaded"}
            
            # Run solver
            gh.RunSolver(force_update)
            
            return {
                "status": "success",
                "message": "Grasshopper solver executed successfully"
            }
            
        except Exception as e:
            log_message("Error running Grasshopper solver: " + str(e))
            return {"status": "error", "message": str(e)}

    def _grasshopper_clear_canvas(self):
        """Clear all components from the Grasshopper canvas"""
        try:
            # Get Grasshopper plugin
            gh = rs.GetPlugInObject('Grasshopper')
            if not gh:
                return {"status": "error", "message": "Grasshopper plugin not available"}
            
            if not gh.IsEditorLoaded():
                return {"status": "error", "message": "Grasshopper editor is not loaded"}
            
            if not Instances:
                return {"status": "error", "message": "Grasshopper Instances not available"}
            
            doc = Instances.ActiveCanvas.Document
            if doc:
                # Clear all objects
                doc.Objects.Clear()
                
                # Refresh canvas
                Instances.ActiveCanvas.Refresh()
                
                return {
                    "status": "success",
                    "message": "Grasshopper canvas cleared successfully"
                }
            else:
                return {"status": "error", "message": "No active Grasshopper document"}
            
        except Exception as e:
            log_message("Error clearing Grasshopper canvas: " + str(e))
            return {"status": "error", "message": str(e)}
    
    def _grasshopper_list_available_components(self):
        """List all available Grasshopper components for debugging"""
        try:
            # Get Grasshopper plugin
            gh = rs.GetPlugInObject('Grasshopper')
            if not gh:
                return {"status": "error", "message": "Grasshopper plugin not available"}
            
            if not gh.IsEditorLoaded():
                return {"status": "error", "message": "Grasshopper editor is not loaded"}
            
            # Return list of supported component types
            supported_components = [
                {"name": "Number Slider", "category": "Params", "subcategory": "Input"},
                {"name": "Number", "category": "Params", "subcategory": "Input"},
                {"name": "Integer", "category": "Params", "subcategory": "Input"},
                {"name": "Boolean", "category": "Params", "subcategory": "Input"},
                {"name": "Point", "category": "Params", "subcategory": "Input"},
                {"name": "Vector", "category": "Params", "subcategory": "Input"},
                {"name": "Text", "category": "Params", "subcategory": "Input"},
                {"name": "Series", "category": "Sets", "subcategory": "Sequence"},
                {"name": "Range", "category": "Sets", "subcategory": "Sequence"},
                {"name": "Cross Reference", "category": "Sets", "subcategory": "Tree"},
                {"name": "Addition", "category": "Maths", "subcategory": "Operators"},
                {"name": "Subtraction", "category": "Maths", "subcategory": "Operators"},
                {"name": "Multiplication", "category": "Maths", "subcategory": "Operators"},
                {"name": "Division", "category": "Maths", "subcategory": "Operators"},
                {"name": "Line", "category": "Curve", "subcategory": "Primitive"},
                {"name": "Circle", "category": "Curve", "subcategory": "Primitive"},
                {"name": "Rectangle", "category": "Curve", "subcategory": "Primitive"},
                {"name": "Polygon", "category": "Curve", "subcategory": "Primitive"},
                {"name": "Extrude", "category": "Surface", "subcategory": "Freeform"},
                {"name": "Move", "category": "Transform", "subcategory": "Euclidean"},
                {"name": "Rotate", "category": "Transform", "subcategory": "Euclidean"},
                {"name": "Scale", "category": "Transform", "subcategory": "Euclidean"},
                {"name": "Construct Point", "category": "Vector", "subcategory": "Point"},
            ]
            
            return {
                "status": "success",
                "components": supported_components,
                "count": len(supported_components),
                "note": "This is a list of currently supported component types. More components may be available but not yet implemented."
            }
            
        except Exception as e:
            log_message("Error listing Grasshopper components: " + str(e))
            return {"status": "error", "message": str(e)}

# Create and start server
server = RhinoMCPServer(HOST, PORT)
server.start()

# Add commands to Rhino
def start_server():
    """Start the RhinoMCP server"""
    server.start()

def stop_server():
    """Stop the RhinoMCP server"""
    server.stop()

# Automatically start the server when this script is loaded
start_server()
log_message("RhinoMCP script loaded. Server started automatically.")
log_message("To stop the server, run: stop_server()") 