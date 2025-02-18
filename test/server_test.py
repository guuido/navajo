import asyncio
import pytest
import pytest_asyncio
import signal
from contextlib import asynccontextmanager

# Mock ASGI application implementations
async def mock_app_success(scope, receive, send):
    """Mock ASGI app that successfully handles lifespan events"""
    assert scope["type"] == "lifespan"
    while True:
        message = await receive()
        if message is not None:
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

async def mock_app_startup_failure(scope, receive, send):
    """Mock ASGI app that fails during startup"""
    message = await receive()
    if message["type"] == "lifespan.startup":
        await send({"type": "lifespan.startup.failed", "message": "Startup failed"})

async def mock_app_shutdown_failure(scope, receive, send):
    """Mock ASGI app that fails during shutdown"""
    while True:
        message = await receive()
        
        if message is not None and message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message is not None and message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.failed", "message": "Shutdown failed"})
            return

@pytest_asyncio.fixture
async def server():
    """Fixture to create and cleanup server instance"""
    from navajo.server import Server 
    
    @asynccontextmanager
    async def create_server(app):
        server_instance = Server(app)
        yield server_instance
        # Cleanup
        if hasattr(server_instance, 'servers'):
            for server in server_instance.servers:
                server.close()
                await server.wait_closed()
    
    return create_server

@pytest.mark.asyncio
async def test_successful_startup_shutdown(server):
    """Test normal startup and shutdown flow"""
    async with server(mock_app_success) as server_instance:
        # Start the server
        asyncio.create_task(server_instance.start())
        await asyncio.sleep(0.2)  # Give time for startup
        
        assert server_instance._lifespan_state["startup"] == True
        assert not server_instance._lifespan_state["shutdown"]
        assert len(server_instance.servers) == 1
        
        # Trigger shutdown
        await server_instance.handle_shutdown_signal(signal.SIGTERM)
        await asyncio.sleep(0.1)  # Give time for shutdown
        
        assert server_instance._lifespan_state["shutdown"] == True

@pytest.mark.asyncio
async def test_startup_failure(server):
    """Test server behavior when startup fails"""
    async with server(mock_app_startup_failure) as server_instance:
        with pytest.raises(RuntimeError, match="Application startup failed"):
            await server_instance.start()
        
        assert server_instance._shutdown_event.is_set()

@pytest.mark.asyncio
async def test_shutdown_failure(server):
    """Test server behavior when shutdown fails"""
    async with server(mock_app_shutdown_failure) as server_instance:
        await server_instance.start()
        await asyncio.sleep(0.1)
        
        # Trigger shutdown
        await server_instance.handle_shutdown_signal(signal.SIGTERM)
        await server_instance.shutdown()
        
        # Even with shutdown failure, server should complete shutdown process
        assert server_instance._lifespan_state["shutdown"] == True

@pytest.mark.asyncio
async def test_signal_handling(server):
    """Test proper handling of shutdown signals"""
    async with server(mock_app_success) as server_instance:
        await server_instance.start()
        
        # Test SIGTERM
        await server_instance.handle_shutdown_signal(signal.SIGTERM)
        assert server_instance._shutdown_event.is_set()
        
        # Reset for SIGINT test
        server_instance._shutdown_event.clear()
        
        # Test SIGINT
        await server_instance.handle_shutdown_signal(signal.SIGINT)
        assert server_instance._shutdown_event.is_set()

@pytest.mark.asyncio
async def test_server_loop(server):
    """Test server loop behavior"""
    async with server(mock_app_success) as server_instance:
        await server_instance.start()
        
        # Create task for server loop
        loop_task = asyncio.create_task(server_instance.server_loop())
        
        # Verify server keeps running
        await asyncio.sleep(0.1)
        assert not loop_task.done()
        
        # Trigger shutdown
        server_instance._shutdown_event.set()
        await asyncio.sleep(0.1)
        assert loop_task.done()

