import asyncio
import logging
import signal
from socket import AF_INET
from navajo.protocols.http import HttpServerProtocol

logger = logging.getLogger("navajo")

class Server:
    def __init__(self,app):
        self.servers = []
        self._shutdown_event = None
        self.app = app
        self._lifespan_state = {"startup": False, "shutdown": False}
    
    def run(self):
        asyncio.run(self._run_())

    async def _run_(self):
        await self.start()
        try:
            await self.server_loop()
        finally:
            await self.shutdown()

    async def start(self):
        self._shutdown_event = asyncio.Event()

        # Start lifespan handling
        lifespan_task = asyncio.create_task(self.handle_lifespan())

        loop = asyncio.get_running_loop()
        signals = (signal.SIGTERM, signal.SIGINT)
        for sig in signals:
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(self.handle_shutdown_signal(s))
            )
        
        # Wait for startup to complete or fail
        while not self._lifespan_state["startup"]:
            if self._shutdown_event.is_set():
                raise RuntimeError("Application startup failed")
            await asyncio.sleep(0.1)

        server = await loop.create_server(
            protocol_factory=lambda: HttpServerProtocol(app=self.app),
            family=AF_INET,
            host="0.0.0.0",
            port=3000,
            ssl=None,
            backlog=100)
        logger.info("Server started on 0.0.0.0:3000")
        self.servers.append(server)

    async def handle_shutdown_signal(self, sig):
        logger.info(f"Received exit signal {sig.name}")
        self._shutdown_event.set()
    
    async def server_loop(self):
        await self._shutdown_event.wait()
    
    async def shutdown(self):
        logger.info("Gracefully shutting down...")
        for server in self.servers:
            server.close()
            await server.wait_closed()

        # Wait for lifespan shutdown to complete
        while not self._lifespan_state["shutdown"]:
            await asyncio.sleep(0.1)
        
        # Cancel all running tasks except the current one
        tasks = [t for t in asyncio.all_tasks() 
                if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        
        logger.info(f"Cancelling {len(tasks)} outstanding tasks")
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Shutdown complete")

    async def handle_lifespan(self):
        """Handle ASGI lifespan protocol events."""
        scope = {
            "type": "lifespan",
            "asgi": {
                "version": "3.0",
                "spec_version": "2.3"
            }
        }

        async def receive():
            if not self._lifespan_state["startup"]:
                return {"type": "lifespan.startup"}
            elif not self._lifespan_state["shutdown"] and self._shutdown_event.is_set():
                return {"type": "lifespan.shutdown"}
            await asyncio.sleep(0.1)  # Prevent busy waiting
            return None

        async def send(message):
            if message["type"] == "lifespan.startup.complete":
                logger.info("Application startup complete")
                self._lifespan_state["startup"] = True
            elif message["type"] == "lifespan.startup.failed":
                logger.error(f"Application startup failed: {message.get('message', 'No message provided')}")
                self._shutdown_event.set()
                await asyncio.sleep(0.1)
                self._lifespan_state["startup"] = True
            elif message["type"] == "lifespan.shutdown.complete":
                logger.info("Application shutdown complete")
                self._lifespan_state["shutdown"] = True
            elif message["type"] == "lifespan.shutdown.failed":
                logger.error(f"Application shutdown failed: {message.get('message', 'No message provided')}")
                self._lifespan_state["shutdown"] = True

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            logger.error(f"Error in lifespan protocol: {exc}")
            self._shutdown_event.set()

