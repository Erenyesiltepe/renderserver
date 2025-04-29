import asyncio
import websockets
import json
import uuid
import datetime
import random
import logging
import os
import imagelist
from aiohttp import web

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Use 0.0.0.0 to bind to all interfaces, essential for Render
WEBSOCKET_HOST = "0.0.0.0"

# Get the main port from environment variable PORT for the WebSocket server
WEBSOCKET_PORT = int(os.environ.get("PORT", 8765)) # Render expects the main service here

# Define a *different* port for the HTTP health check
# Choose a port unlikely to conflict, e.g., 8080 or make it configurable
HTTP_HEALTH_PORT = int(os.environ.get("HTTP_PORT", 8080))

# --- HTTP Health Check Handler ---
async def handle_health(request):
    """A simple HTTP handler that returns 200 OK for health checks."""
    logging.info("Health check request received.")
    return web.Response(text="OK", status=200)

# --- WebSocket Server Class ---
class WebSocketServer:
    # Modify __init__ to accept both ports
    def __init__(self, host, ws_port, http_port):
        self.host = host
        self.ws_port = ws_port
        self.http_port = http_port # Store the http port
        self.connected_clients = set()
        logging.info(f"WebSocketServer initialized. WS on {self.host}:{self.ws_port}, HTTP on {self.host}:{self.http_port}")

    # ... (register_client, unregister_client, onDataReceived, sendData, periodic_sender remain the same) ...
    async def register_client(self, websocket):
        self.connected_clients.add(websocket)
        logging.info(f"Client connected: {websocket.remote_address}. Total clients: {len(self.connected_clients)}")

    async def unregister_client(self, websocket):
        self.connected_clients.discard(websocket)
        logging.info(f"Client disconnected: {websocket.remote_address}. Total clients: {len(self.connected_clients)}")

    async def onDataReceived(self, websocket, message):
        logging.info(f"Received data from {websocket.remote_address}: {message}")
        try:
            data = json.loads(message)
            logging.info(f"Parsed JSON data: {data}")
            # Add your custom logic here
        except json.JSONDecodeError:
            logging.warning(f"Received non-JSON message: {message}")
        except Exception as e:
            logging.error(f"Error processing message: {e}")

    async def sendData(self, message, target_websocket=None):
        if isinstance(message, dict):
            message_str = json.dumps(message)
        else:
            message_str = str(message)

        if target_websocket:
            if target_websocket in self.connected_clients:
                try:
                    await target_websocket.send(message_str)
                    logging.debug(f"Sent message to {target_websocket.remote_address}: {message_str}")
                except websockets.exceptions.ConnectionClosed:
                    logging.warning(f"Attempted to send to already closed connection {target_websocket.remote_address}")
                    await self.unregister_client(target_websocket)
                except Exception as e:
                    logging.error(f"Error sending message to {target_websocket.remote_address}: {e}")
                    await self.unregister_client(target_websocket) # Remove on other errors too
            else:
                 logging.warning(f"Target websocket {target_websocket.remote_address} not found in connected clients.")
        else:
            # Broadcast to all clients - More robust error handling
            if self.connected_clients:
                logging.debug(f"Broadcasting message to {len(self.connected_clients)} clients: {message_str}")
                # Use list comprehension for slightly cleaner broadcast attempt
                results = await asyncio.gather(
                    *[client.send(message_str) for client in self.connected_clients],
                    return_exceptions=True # Catch errors without stopping others
                )
                # Handle disconnections after broadcast attempt
                disconnected_clients = set()
                for i, result in enumerate(results):
                    client = list(self.connected_clients)[i] # Get corresponding client
                    if isinstance(result, Exception):
                        logging.warning(f"Client {client.remote_address} disconnected during broadcast: {result}")
                        disconnected_clients.add(client)

                for client in disconnected_clients:
                    await self.unregister_client(client)


    async def periodic_sender(self, interval_seconds=10): # Keep your interval
        while True:
            await asyncio.sleep(interval_seconds)
            if self.connected_clients:
                current_datetime = datetime.datetime.now()
                message = {
                    "id": str(uuid.uuid4()),
                    "type": "server_update",
                    "timestamp": current_datetime.isoformat(),
                    "data": random.randint(1, 50000),
                    "server_time": f"Server time: {current_datetime.strftime('%H:%M:%S')}",
                    "image": random.choice(imagelist.imageList)
                }
                await self.sendData(message)

    async def connection_handler(self, websocket):
        await self.register_client(websocket)
        try:
            async for message in websocket:
                await self.onDataReceived(websocket, message)
        except websockets.exceptions.ConnectionClosedError as e:
            logging.info(f"Connection closed with error: {e}")
        except websockets.exceptions.ConnectionClosedOK:
            logging.info("Connection closed gracefully.")
        except Exception as e:
            logging.error(f"An unexpected error occurred with {websocket.remote_address}: {e}")
        finally:
            await self.unregister_client(websocket)

    # --- Split start into separate server starters ---
    async def start_http_server(self):
        """Starts the HTTP health check server."""
        http_app = web.Application()
        http_app.router.add_get('/health', handle_health)
        runner = web.AppRunner(http_app)
        await runner.setup()
        # Use the dedicated HTTP port
        site = web.TCPSite(runner, self.host, self.http_port)
        try:
            await site.start()
            logging.info(f"HTTP health check server running on http://{self.host}:{self.http_port}/health")
            # Keep the HTTP server running in the background
            await asyncio.Event().wait() # Keep running until cancelled
        except asyncio.CancelledError:
             logging.info("HTTP server task cancelled.")
        finally:
            await runner.cleanup() # Clean up aiohttp resources

    async def start_websocket_server(self):
        """Starts the WebSocket server."""
        # Use serve context manager for clean shutdown
        async with websockets.serve(self.connection_handler, self.host, self.ws_port) as server:
            logging.info(f"WebSocket server running on ws://{self.host}:{self.ws_port}")
            await asyncio.Future() # Keep this coroutine running until interrupted/cancelled

    async def start(self):
        """Starts both the WebSocket and HTTP servers concurrently."""
        logging.info(f"Attempting to start servers...")

        # Start the periodic sender task
        sender_task = asyncio.create_task(self.periodic_sender())
        sender_task.set_name("PeriodicSender")

        # Start the HTTP server task
        http_task = asyncio.create_task(self.start_http_server())
        http_task.set_name("HttpServer")

        # Start the WebSocket server task (this one will run indefinitely in foreground of this task)
        websocket_task = asyncio.create_task(self.start_websocket_server())
        websocket_task.set_name("WebSocketServer")

        # Wait for any of the main server tasks to complete (which they shouldn't unless there's an error)
        # Or until an external signal (like KeyboardInterrupt) stops asyncio.run
        done, pending = await asyncio.wait(
            [sender_task, http_task, websocket_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Log if any task finishes unexpectedly and handle potential exceptions
        for task in done:
            try:
                result = task.result() # This will raise exception if task failed
                logging.warning(f"Task {task.get_name()} finished unexpectedly with result: {result}")
            except asyncio.CancelledError:
                 logging.info(f"Task {task.get_name()} was cancelled.")
            except Exception as e:
                logging.error(f"Task {task.get_name()} failed: {e}", exc_info=True)

        # Cancel pending tasks on exit
        logging.info("Shutting down pending tasks...")
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True) # Wait for cancellations
        logging.info("Server shutdown complete.")


# --- Main execution ---
if __name__ == "__main__":
    # Pass both ports to the constructor
    server = WebSocketServer(WEBSOCKET_HOST, WEBSOCKET_PORT, HTTP_HEALTH_PORT)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logging.info("Server stopped manually.")
    except Exception as e:
        logging.error(f"Server failed to start or crashed: {e}", exc_info=True)
