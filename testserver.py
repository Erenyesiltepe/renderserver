import asyncio
import websockets
import json
import uuid
import datetime
import random
import logging
import os
import imagelist
from aiohttp import web # Import aiohttp web server components

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Use 0.0.0.0 to bind to all interfaces, essential for Render
WEBSOCKET_HOST = "0.0.0.0"
# Get port from environment variable PORT, default to 10000 for Render compatibility
# Render often defaults to 10000, but reading from os.environ is the key.
WEBSOCKET_PORT = int(os.environ.get("PORT", 8765))

# --- HTTP Health Check Handler ---
async def handle_health(request):
    """A simple HTTP handler that returns 200 OK for health checks."""
    logging.info("Health check request received.")
    return web.Response(text="OK", status=200)

# --- WebSocket Server Class (mostly unchanged) ---
class WebSocketServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connected_clients = set()
        logging.info(f"WebSocketServer initialized. Ready to listen on {self.host}:{self.port}")

    async def register_client(self, websocket):
        self.connected_clients.add(websocket)
        logging.info(f"Client connected: {websocket.remote_address}. Total clients: {len(self.connected_clients)}")

    async def unregister_client(self, websocket):
        # Use discard instead of remove to avoid KeyError if already removed
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
                    # Ensure removal if connection closed during send
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
                disconnected_clients = set()
                for client in self.connected_clients:
                    try:
                        await client.send(message_str)
                    except websockets.exceptions.ConnectionClosed:
                        logging.warning(f"Client {client.remote_address} disconnected during broadcast.")
                        disconnected_clients.add(client)
                    except Exception as e:
                        logging.error(f"Error broadcasting to {client.remote_address}: {e}")
                        disconnected_clients.add(client)

                # Remove disconnected clients after iteration
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

    async def start(self):
        """Starts both the WebSocket and HTTP servers."""
        logging.info(f"Attempting to start servers on {self.host}:{self.port}...")

        # --- Start the periodic sender ---
        asyncio.create_task(self.periodic_sender())

        # --- Configure and start the aiohttp server for health checks ---
        http_app = web.Application()
        http_app.router.add_get('/health', handle_health) # Add the health check route
        runner = web.AppRunner(http_app)
        await runner.setup()
        # Use the same host and port for the HTTP site
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logging.info(f"HTTP health check server running on http://{self.host}:{self.port}/health")

        # --- Start the WebSocket server ---
        # websockets.serve will run in the foreground of this coroutine
        async with websockets.serve(self.connection_handler, self.host, self.port):
            logging.info(f"WebSocket server running on ws://{self.host}:{self.port}")
            await asyncio.Future()  # Keep running until interrupted

# --- Main execution ---
if __name__ == "__main__":
    server = WebSocketServer(WEBSOCKET_HOST, WEBSOCKET_PORT)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logging.info("Server stopped manually.")
    except Exception as e:
        logging.error(f"Server failed to start or crashed: {e}", exc_info=True) # Add exc_info for more details
