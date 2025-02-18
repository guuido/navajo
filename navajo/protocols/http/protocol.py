import asyncio
import logging
from navajo.protocols.http.handlers import ASGIResponseHandler, ErrorResponseHandler, TimeoutHandler, TimeoutType
from navajo.protocols.http.parser import ParserError, ParserState, RequestBuffer
from navajo.utils import BadRequestError, UnsupportedProtocolError, get_client_addr, get_server_addr, is_ssl

REQUEST_TIMEOUT = 60
KEEP_ALIVE_TIMEOUT = 5
MAX_KEEP_ALIVE_REQUESTS = 100

class HttpServerProtocol(asyncio.Protocol):
    def __init__(self, app):
        self.transport = None
        self.server = None
        self.client = None
        self.scheme = None
        self.buffer = None
        self.app = app
        self.logger = logging.getLogger("navajo")
        self.timeout_handler = None
        self.error_response_handler = None
        self.asgi_response_handler = None
        self.request_count = 0

    def connection_made(self, transport):
        self.transport = transport
        self.server = get_server_addr(transport)
        self.client = get_client_addr(transport)
        self.scheme = 'https' if is_ssl(transport) else 'http'
        self.request_count = 0
        self.buffer = RequestBuffer()
        self.timeout_handler = TimeoutHandler(self._timeout_expired,self._keepalive_timeout_expired)
        self.error_response_handler = ErrorResponseHandler(transport)
        self.asgi_response_handler = ASGIResponseHandler()
        self.logger.debug(f"Connection created with {self.client} on {self.scheme}")

    def connection_lost(self, exc):
        self.timeout_handler.cancel_timeout_handle(TimeoutType.ALL)
        try:
            if not self.transport.is_closing():
                self.transport.close()
        except Exception as e:
            self.logger.error("Error closing transport")
            
    def data_received(self, data):
        self.timeout_handler.reset_timeout(TimeoutType.REQUEST,REQUEST_TIMEOUT)
        self.timeout_handler.cancel_timeout_handle(TimeoutType.KEEP_ALIVE)

        self.buffer.feed_data(data)

        if self.buffer.state in (ParserState.RECEIVING_CHUNKS, ParserState.CHUNKS_COMPLETE, ParserState.COMPLETE):
            try:
                headers = self.buffer.get_request_headers()
                parsed_headers = self.buffer.parse_headers(headers)
            except RuntimeError:
                return
            except UnsupportedProtocolError as protocol_error:
                self.timeout_handler.cancel_timeout_handle(TimeoutType.ALL)
                return self.error_response_handler.send_protocol_error_response(str(protocol_error.value))
            except BadRequestError:
                self.timeout_handler.cancel_timeout_handle(TimeoutType.ALL)
                return self.error_response_handler.send_bad_request_response()
                             
            # Build ASGI scope
            scope = {
                'type': 'http',
                'asgi': {'version': '3.0', 'spec_version': '2.3'},
                'http_version': parsed_headers['http_version'],
                'method': parsed_headers['method'],
                'scheme': self.scheme,
                'path': parsed_headers['path'],
                'raw_path': parsed_headers['raw_path'],
                'query_string': parsed_headers['query_string'],
                'root_path': '',
                'headers': parsed_headers['headers'],
                'client': self.client,
                'server': self.server
            }

            asyncio.create_task(self.handle_request(scope))

            if self.buffer.state in (ParserState.CHUNKS_COMPLETE, ParserState.COMPLETE):
                self.request_count += 1
                self.buffer = RequestBuffer()
                self.timeout_handler.cancel_timeout_handle(TimeoutType.REQUEST)

        elif self.buffer.state == ParserState.ERROR:
            self.timeout_handler.cancel_timeout_handle(TimeoutType.ALL)
            if self.buffer.error == ParserError.LENGTH_REQUIRED:
                return self.error_response_handler.send_length_required_response()
            else:
                return self.error_response_handler.send_bad_request_response()

    def eof_received(self):
        self.logger.debug(f"EOF received from {self.client}")
        return False

    def _timeout_expired(self):
        self.logger.warning(f"Connection to {self.client} timed out")
        self.error_response_handler.send_timeout_response()

    def _keepalive_timeout_expired(self):
        self.logger.warning(f"Keep-Alive timeout for {self.client} timed out")
        self.transport.close()

    async def handle_request(self,scope):
        """Handle the ASGI application cycle."""
        self.asgi_response_handler.set_scope(scope)
        try:
            await self.app(
                scope,
                self._receive,
                self._send
            )
        except OSError:
            pass
        except Exception as exc:
            self.timeout_handler.cancel_timeout_handle(TimeoutType.ALL)
            self.error_response_handler.send_internal_server_error_response()

    async def _receive(self):
        """ASGI receive function"""
        if self.transport.is_closing():
            return {
            'type': 'http.disconnect',
        }

        if self.buffer.state in (ParserState.RECEIVING_CHUNKS, ParserState.CHUNKS_COMPLETE):
            body = self.buffer.get_last_chunks()
            if self.buffer.state == ParserState.CHUNKS_COMPLETE:
                more_body = False
            else:
                more_body = True
        elif self.buffer.state == ParserState.COMPLETE:
            body = self.buffer.get_request_body()
            more_body = False
        else:
            body = b''
            more_body = False

        return {
            'type': 'http.request',
            'body':body,
            'more_body': more_body
        }

    async def _send(self, message):
        """ASGI send function"""

        if self.transport.is_closing():
            raise OSError()

        message_type = message['type']

        if message_type == 'http.response.start':
            self.asgi_response_handler.set_started(True)
            self.asgi_response_handler.set_status(message['status'])
            self.asgi_response_handler.set_headers(message['headers'])

        elif message_type == 'http.response.body':
            if not self.asgi_response_handler.started():
                raise RuntimeError("Response body sent before response start!")
            
            # Construct response
            status_line = f"HTTP/1.1 {self.asgi_response_handler.status()}\r\n"
            header_lines = []
            for name, value in self.asgi_response_handler.headers():
                header_lines.append(f"{name.decode('latin1')}: {value.decode('latin1')}\r\n")

            response = (
                status_line.encode('latin1') +
                b''.join(line.encode('latin1') for line in header_lines) +
                b'\r\n' +
                message.get('body', b'')
            )

            self.transport.write(response)
            if not message.get('more_body', False):
                if not self.should_keep_alive():
                    self.timeout_handler.cancel_timeout_handle(TimeoutType.ALL)
                    self.transport.close()
                else:
                    self.timeout_handler.reset_timeout(TimeoutType.KEEP_ALIVE, KEEP_ALIVE_TIMEOUT)

    def should_keep_alive(self) -> bool:
        if self.request_count >= MAX_KEEP_ALIVE_REQUESTS:
            return False

        for name, value in self.asgi_response_handler.scope()['headers']:
            if name.lower() == b'connection':
                return value.lower() != b'close'
        return self.asgi_response_handler.scope()['http_version'] == '1.1'
    
    