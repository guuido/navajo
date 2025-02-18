from asyncio import Transport

def get_server_addr(transport: Transport) -> tuple[str, int] | None:
    socket = transport.get_extra_info('socket')
    if socket is None:
        server_addr = transport.get_extra_info('sockname')
    else:
        try:
            server_addr = socket.getsockname() 
        except OSError: 
            return None
        
    return ((str(server_addr[0]),int(server_addr[1]))) if type(server_addr) == tuple else None

def get_client_addr(transport: Transport) -> tuple[str, int] | None:
    socket = transport.get_extra_info('socket')
    if socket is None:
        client_addr = transport.get_extra_info('peername')
    else:
        try:
            client_addr = socket.getpeername() 
        except OSError: 
            return None
        
    return ((str(client_addr[0]),int(client_addr[1]))) if type(client_addr) == tuple else None

def is_ssl(transport: Transport) -> bool:
    is_ssl = True if transport.get_extra_info("sslcontext") else False
    return is_ssl

class UnsupportedProtocolError(Exception):
    pass

class BadRequestError(Exception):
    pass