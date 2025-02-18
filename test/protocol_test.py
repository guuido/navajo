from navajo.protocols.http.handlers import ASGIResponseHandler, ErrorResponseHandler, TimeoutHandler, TimeoutType
from navajo.protocols.http.protocol import KEEP_ALIVE_TIMEOUT, REQUEST_TIMEOUT, HttpServerProtocol
import pytest
import asyncio
from unittest.mock import Mock, call, create_autospec, patch
from navajo.protocols.http.parser import ParserState, RequestBuffer

@pytest.fixture
def transport():
    # Create a mock that specifies the asyncio.Transport interface
    transport = create_autospec(asyncio.Transport, instance=True)
    
    # Store written data for verification
    transport.written_data = []
    transport.write.side_effect = lambda data: transport.written_data.append(data)

    transport._closing = False

    def mock_is_closing():
        return transport._closing
    
    def mock_close():
        transport._closed = True
        transport._closing = True

    transport.close.side_effect = mock_close
    transport.is_closing.side_effect = mock_is_closing
    
    # Set up connection info
    transport.get_extra_info.side_effect = lambda name, default=None: {
        'socket': Mock(
            family='AF_INET',
            getsockname=lambda: ('127.0.0.1', 8000),
            getpeername=lambda: ('127.0.0.1',  12345)
        )
    }.get(name, default)
    
    return transport

@pytest.fixture
def protocol():
    # Mock ASGI app
    async def mock_app(scope, receive, send):
        assert scope['type'] == 'http'  # Verify scope
        
        # Verify request body
        request_body = await receive()
        assert request_body['type'] == 'http.request'
        
        # Send response
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'text/plain')]
        })
        await send({
            'type': 'http.response.body',
            'body': b'Hello, World!'
        })
    
    return HttpServerProtocol(mock_app)

@pytest.mark.asyncio
async def test_connection_lifecycle(protocol, transport):
    # Test connection establishment
    protocol.connection_made(transport)
    
    assert protocol.transport == transport
    assert protocol.server == ('127.0.0.1', 8000)
    assert protocol.client == ('127.0.0.1', 12345)
    assert protocol.scheme == 'http'
    assert isinstance(protocol.buffer,RequestBuffer)
    assert isinstance(protocol.timeout_handler,TimeoutHandler)
    assert isinstance(protocol.error_response_handler,ErrorResponseHandler)
    assert isinstance(protocol.asgi_response_handler,ASGIResponseHandler)
    
    transport.is_closing.return_value = False
    
    # Test connection termination
    protocol.connection_lost(None)

    transport.close.assert_called_once()

@pytest.mark.asyncio
async def test_basic_request_response(protocol, transport):
    protocol.connection_made(transport)
    
    # Send request
    request = (
        b'GET / HTTP/1.1\r\n'
        b'Host: localhost\r\n'
        b'Connection: close\r\n'
        b'\r\n'
    )
    protocol.data_received(request)
    
    # Allow event loop to process
    await asyncio.sleep(0)
    
    # Verify response using transport.write calls
    assert len(transport.write.call_args_list) > 0
    response = b''.join(call.args[0] for call in transport.write.call_args_list)
    assert b'HTTP/1.1 200' in response
    assert b'Hello, World!' in response
    
    # Verify connection closure due to "Connection: close"
    transport.close.assert_called_once()

@pytest.mark.asyncio
async def test_timeout_reset(protocol, transport):
    protocol.connection_made(transport)
    
    # Mock the timeout handler
    protocol.timeout_handler = Mock()
     
    # Send keep-alive request
    request = (
        b'GET / HTTP/1.1\r\n'
        b'Host: localhost\r\n'
        b'Connection: keep-alive\r\n'
        b'\r\n'
    )
    protocol.data_received(request)
    
    await asyncio.sleep(0)
    
    # Verify timeout was reset
    protocol.timeout_handler.reset_timeout.assert_has_calls([
        call(TimeoutType.REQUEST, REQUEST_TIMEOUT),
        call(TimeoutType.KEEP_ALIVE, KEEP_ALIVE_TIMEOUT)
    ])

@patch('navajo.protocols.http.protocol.REQUEST_TIMEOUT', 0.1)  
@pytest.mark.asyncio
async def test_request_timeout(protocol, transport):
    protocol.connection_made(transport)
    
    # Create a partial request that would trigger timeout
    protocol.data_received(b'GET / HTTP/1.1\r\n')
    
    # Simulate timeout
    await asyncio.sleep(0.2)
    
    # Verify timeout response and connection closure
    response = b''.join(call.args[0] for call in transport.write.call_args_list)
    assert b'408 Request Timeout' in response
    transport.close.assert_called_once()

@patch('navajo.protocols.http.protocol.KEEP_ALIVE_TIMEOUT', 0.1)  
@pytest.mark.asyncio
async def test_keepalive_timeout(protocol, transport):
    protocol.connection_made(transport)

    request = (
        b'GET / HTTP/1.1\r\n'
        b'Host: localhost\r\n'
        b'Connection: keep-alive\r\n'
        b'\r\n'
    )
    
    # Send complete request
    protocol.data_received(request)

    transport.close.assert_not_called()
    
    # Simulate timeout
    await asyncio.sleep(0.2)
    
    # Verify connection closure
    transport.close.assert_called_once()

@patch('navajo.protocols.http.protocol.MAX_KEEP_ALIVE_REQUESTS', 2)  
@pytest.mark.asyncio
async def test_max_keepalive_requests(protocol, transport):
    protocol.connection_made(transport)

    request = (
        b'GET / HTTP/1.1\r\n'
        b'Host: localhost\r\n'
        b'Connection: keep-alive\r\n'
        b'\r\n'
    )

    for i in range(2):
        protocol.data_received(request)
        transport.close.assert_not_called()
        assert protocol.request_count == i+1
        await asyncio.sleep(0)
    
    protocol.data_received(request)
    print(protocol.request_count)
    
    # Verify connection closure
    transport.close.assert_called_once()

@pytest.mark.asyncio
async def test_malformed_request(protocol, transport):
    protocol.connection_made(transport)
    
    # Send invalid request
    protocol.data_received(b'INVALID\r\n\r\n')
    
    await asyncio.sleep(0)
    
    # Verify error response
    response = b''.join(call.args[0] for call in transport.write.call_args_list)
    assert b'400 Bad Request' in response
    transport.close.assert_called_once()

@pytest.mark.asyncio
async def test_server_error(protocol, transport):
    # Mock app that raises an error
    async def error_app(scope, receive, send):
        raise RuntimeError("Server Error")
    
    protocol.app = error_app
    protocol.connection_made(transport)
    
    # Send valid request
    request = b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n'
    protocol.data_received(request)
    
    await asyncio.sleep(0)
    
    # Verify error response
    response = b''.join(call.args[0] for call in transport.write.call_args_list)
    assert b'500 Internal Server Error' in response
    transport.close.assert_called_once()

@pytest.mark.asyncio
async def test_buffer_reset_after_request(protocol, transport):
    protocol.connection_made(transport)
    
    # Send request
    request = b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n'
    protocol.data_received(request)
    
    await asyncio.sleep(0)
    
    # Verify buffer was reset
    assert isinstance(protocol.buffer, RequestBuffer)
    assert protocol.buffer.state == ParserState.RECEIVING_HEADERS

@pytest.mark.asyncio
async def test_buffer_reset_after_chunked_request(protocol, transport):
    protocol.connection_made(transport)

    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"6\r\nHello \r\n6\r\nWorld!\r\n0\r\n\r\n"
    ]

    # Send chunks
    for c in chunks:
        protocol.data_received(c)
    
    await asyncio.sleep(0)
    
    # Verify buffer was reset
    assert isinstance(protocol.buffer, RequestBuffer)
    assert protocol.buffer.state == ParserState.RECEIVING_HEADERS

# Test different HTTP methods
@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET","DELETE","OPTIONS"])
async def test_http_methods(method, protocol, transport):
    protocol.connection_made(transport)
    
    request = f"{method} / HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
    protocol.data_received(request)
    
    await asyncio.sleep(0)
    
    # Verify the method was correctly processed
    response = b''.join(call.args[0] for call in transport.write.call_args_list)
    assert b'200' in response

@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST","PUT","PATCH"])
async def test_http_methods_with_body(method, protocol, transport):
    protocol.connection_made(transport)
    
    request = f"{method} / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 12\r\n\r\nHello, World".encode()
    protocol.data_received(request)
    
    await asyncio.sleep(0)
    
    # Verify the method was correctly processed
    response = b''.join(call.args[0] for call in transport.write.call_args_list)
    assert b'200' in response




