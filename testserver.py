import asyncio
import websockets
import json
import uuid
import datetime
import random
import logging
import imagelist
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

WEBSOCKET_HOST = "0.0.0.0"  # Listen on all available network interfaces
WEBSOCKET_PORT = int(os.environ.get("PORT", 8765))      # Port for the WebSocket server

class WebSocketServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        # Use a set to store connected client websockets
        self.connected_clients = set()
        logging.info(f"WebSocketServer initialized. Ready to listen on {self.host}:{self.port}")

    async def register_client(self, websocket):
        """Registers a new client connection."""
        self.connected_clients.add(websocket)
        logging.info(f"Client connected: {websocket.remote_address}. Total clients: {len(self.connected_clients)}")

    async def unregister_client(self, websocket):
        """Unregisters a client connection."""
        self.connected_clients.remove(websocket)
        logging.info(f"Client disconnected: {websocket.remote_address}. Total clients: {len(self.connected_clients)}")

    async def onDataReceived(self, websocket, message):
        """Handles incoming data from a client."""
        logging.info(f"Received data from {websocket.remote_address}: {message}")
        # Example: Echo the message back to the sender
        # await self.sendData(f"Server received: {message}", websocket)
        # Example: Process the data (if it's JSON, etc.)
        try:
            data = json.loads(message)
            logging.info(f"Parsed JSON data: {data}")
            # Add your custom logic here based on the received data
        except json.JSONDecodeError:
            logging.warning(f"Received non-JSON message: {message}")
        except Exception as e:
            logging.error(f"Error processing message: {e}")

    async def sendData(self, message, target_websocket=None):
        """
        Sends data to a specific client or broadcasts to all clients.

        Args:
            message (str or dict): The message to send. If dict, it will be JSON encoded.
            target_websocket (websocket, optional): If specified, send only to this client.
                                                    If None, broadcast to all connected clients.
        """
        if isinstance(message, dict):
            message_str = json.dumps(message)
        else:
            message_str = str(message) # Ensure it's a string

        if target_websocket:
            # Send to a specific client
            if target_websocket in self.connected_clients:
                try:
                    await target_websocket.send(message_str)
                    logging.debug(f"Sent message to {target_websocket.remote_address}: {message_str}")
                except websockets.exceptions.ConnectionClosed:
                    logging.warning(f"Attempted to send to already closed connection {target_websocket.remote_address}")
                except Exception as e:
                    logging.error(f"Error sending message to {target_websocket.remote_address}: {e}")
            else:
                 logging.warning(f"Target websocket {target_websocket.remote_address} not found in connected clients.")
        else:
            # Broadcast to all clients
            if self.connected_clients:
                logging.debug(f"Broadcasting message to {len(self.connected_clients)} clients: {message_str}")
                # Use asyncio.gather for concurrent sending
                # Create a list of tasks, handling potential disconnections during broadcast
                tasks = [client.send(message_str) for client in self.connected_clients]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Log any errors that occurred during broadcast
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                         # Find the client corresponding to the failed task (this is a bit indirect)
                         client_list = list(self.connected_clients)
                         if i < len(client_list):
                             failed_client = client_list[i]
                             logging.error(f"Error broadcasting to {failed_client.remote_address}: {result}")
                         else:
                             logging.error(f"Error broadcasting to an unknown client: {result}")

    async def periodic_sender(self, interval_seconds=2):
        """Example function to periodically send data to all clients."""
        while True:
            await asyncio.sleep(interval_seconds)
            if self.connected_clients: # Only send if there are clients
                current_datetime = datetime.datetime.now()
                message = {
                    "id": str(uuid.uuid4()),
                    "type": "server_update",
                    "timestamp": current_datetime.isoformat(),
                    "data": random.randint(1, 50000),
                    "server_time": f"Server time: {current_datetime.strftime('%H:%M:%S')}",
                    "image": random.choice(imagelist.imageList)
                }
                await self.sendData(message) # Broadcast the message

    async def connection_handler(self, websocket):
        """Handles a single client connection lifecycle."""
        await self.register_client(websocket)
        try:
            # Keep the connection open and listen for messages
            async for message in websocket:
                await self.onDataReceived(websocket, message)
        except websockets.exceptions.ConnectionClosedError as e:
            logging.info(f"Connection closed with error: {e}")
        except websockets.exceptions.ConnectionClosedOK:
            logging.info("Connection closed gracefully.")
        except Exception as e:
            logging.error(f"An unexpected error occurred with {websocket.remote_address}: {e}")
        finally:
            # Ensure client is unregistered on disconnection
            await self.unregister_client(websocket)

    async def start(self):
        """Starts the WebSocket server."""
        logging.info(f"Starting WebSocket server on {self.host}:{self.port}...")
        # Start the periodic sender as a background task
        asyncio.create_task(self.periodic_sender(interval_seconds=10))

        # Start the main server loop
        async with websockets.serve(self.connection_handler, self.host, self.port):
            logging.info("WebSocket server is running.")
            await asyncio.Future()  # Run forever until interrupted

# --- Main execution ---
if __name__ == "__main__":
    server = WebSocketServer(WEBSOCKET_HOST, WEBSOCKET_PORT)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logging.info("Server stopped manually.")
    except Exception as e:
        logging.error(f"Server failed to start or crashed: {e}")

