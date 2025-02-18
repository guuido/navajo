from asyncio import Transport
from socket import socket
from unittest.mock import Mock
from navajo.utils import get_client_addr, get_server_addr, is_ssl
import pytest

@pytest.fixture
def mock_transport():
    return Mock(spec=Transport)

@pytest.fixture
def mock_socket():
    return Mock(spec=socket)

def test_get_server_addr_with_socket(mock_transport, mock_socket):
    test_value = ('127.0.0.1', 25000)
    mock_socket.getsockname.return_value = test_value
    mock_transport.get_extra_info.side_effect = lambda key: mock_socket if key == 'socket' else None

    assert get_server_addr(mock_transport) == test_value

def test_get_server_addr_with_sockname(mock_transport):
    test_value = ('127.0.0.1', 25000)
    mock_transport.get_extra_info.side_effect = lambda key: test_value if key == 'sockname' else None

    assert get_server_addr(mock_transport) == test_value

def test_get_server_addr_with_socket_error(mock_transport, mock_socket):
    mock_socket.getsockname.side_effect = OSError()
    mock_transport.get_extra_info.side_effect = lambda key: mock_socket if key == 'socket' else None

    result = get_server_addr(mock_transport)
    assert result is None

def test_get_server_addr_with_invalid_format(mock_transport):
    mock_transport.get_extra_info.side_effect = lambda key: {
        'socket': None,
        'sockname': 'invalid'
    }[key]
    
    result = get_server_addr(mock_transport)
    assert result is None

def test_get_client_addr_with_socket(mock_transport, mock_socket):
    test_value = ('127.0.0.1', 25000)
    mock_socket.getpeername.return_value = test_value
    mock_transport.get_extra_info.side_effect = lambda key: mock_socket if key == 'socket' else None

    assert get_client_addr(mock_transport) == test_value

def test_get_client_addr_with_peername(mock_transport):
    test_value = ('127.0.0.1', 25000)
    mock_transport.get_extra_info.side_effect = lambda key: test_value if key == 'peername' else None

    assert get_client_addr(mock_transport) == test_value

def test_get_client_addr_with_socket_error(mock_transport, mock_socket):
    mock_socket.getpeername.side_effect = OSError()
    mock_transport.get_extra_info.side_effect = lambda key: mock_socket if key == 'socket' else None

    result = get_client_addr(mock_transport)
    assert result is None

def test_get_client_addr_with_invalid_format(mock_transport):
    mock_transport.get_extra_info.side_effect = lambda key: {
        'socket': None,
        'peername': 'invalid'
    }[key]
    
    result = get_client_addr(mock_transport)
    assert result is None

def test_is_ssl_true(mock_transport):
    mock_transport.get_extra_info.side_effect = lambda key: Mock() if key == 'sslcontext' else None

    assert is_ssl(mock_transport) == True

def test_is_ssl_false(mock_transport):
    mock_transport.get_extra_info.return_value = None

    assert is_ssl(mock_transport) == False

@pytest.mark.parametrize("addr,expected", [
    (('192.168.1.1', 8000), ('192.168.1.1', 8000)),  # IPv4
    (('::1', 8000), ('::1', 8000)),                  # IPv6
    (('localhost', 8000), ('localhost', 8000)),      # Hostname
])
def test_address_formats(mock_transport, mock_socket, addr, expected):
    # Test different address formats for both server and client
    mock_socket.getsockname.return_value = addr
    mock_socket.getpeername.return_value = addr
    mock_transport.get_extra_info.return_value = mock_socket
    
    assert get_server_addr(mock_transport) == expected
    assert get_client_addr(mock_transport) == expected