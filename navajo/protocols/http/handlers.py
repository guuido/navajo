import asyncio
from enum import Enum
import logging

class TimeoutType(Enum):
    REQUEST = 1
    KEEP_ALIVE = 2
    ALL = 3

class TimeoutHandler():
    def __init__(self, request_timeout_callback, keepalive_timeout_callback):
        self.request_timeout_handle = None
        self.keepalive_timeout_handle = None
        self.request_timeout_callback = request_timeout_callback
        self.keepalive_timeout_callback = keepalive_timeout_callback
        self.logger = logging.getLogger("navajo")

    def cancel_timeout_handle(self, type: TimeoutType):
        if type in (TimeoutType.REQUEST,TimeoutType.ALL):
            if self.request_timeout_handle:
                self.request_timeout_handle.cancel()

        if type in (TimeoutType.KEEP_ALIVE,TimeoutType.ALL):
            if self.keepalive_timeout_handle:
                self.keepalive_timeout_handle.cancel()
    
    def reset_timeout(self, type: TimeoutType, timeout):
        if type in (TimeoutType.REQUEST,TimeoutType.ALL):
            if self.request_timeout_handle:
                self.request_timeout_handle.cancel()
            self.request_timeout_handle = asyncio.get_event_loop().call_later(
                timeout, self.request_timeout_callback
            )

        if type in (TimeoutType.KEEP_ALIVE,TimeoutType.ALL):
            if self.keepalive_timeout_handle:
                self.keepalive_timeout_handle.cancel()
            self.keepalive_timeout_handle = asyncio.get_event_loop().call_later(
                timeout, self.keepalive_timeout_callback
            )

class ErrorResponseHandler():
    def __init__(self, transport):
        self.transport = transport
        self.logger = logging.getLogger("navajo")

    def send_timeout_response(self):
        response = (
            b"HTTP/1.1 408 Request Timeout\r\n"
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            b"Request timed out"
        )
        self.transport.write(response)
        self.transport.close()
    
    def send_protocol_error_response(self, error_msg):
        body = f"Unsupported protocol: {error_msg}"
        content_len_header = f"Content-Length: {len(bytes(body))}\r\n"
        response = (
            b"HTTP/1.1 505 HTTP Version Not Supported\r\n"
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n" +
            bytes(content_len_header) +
            b"\r\n" +
            bytes(body)
        )
        self.transport.write(response)
        self.transport.close()

    def send_bad_request_response(self):
        response = (
            b"HTTP/1.1 400 Bad Request\r\n"
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        self.transport.write(response)
        self.transport.close()

    def send_length_required_response(self):
        response = (
            b"HTTP/1.1 411 Length Required\r\n"
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        self.transport.write(response)
        self.transport.close()

    def send_internal_server_error_response(self):
        response = (
            b"HTTP/1.1 500 Internal Server Error\r\n"
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        self.transport.write(response)
        self.transport.close()

class ASGIResponseHandler():
    def __init__(self):
        self._started = False
        self._status = None
        self._headers = None
        self._scope = None
        self.logger = logging.getLogger("navajo")

    def set_started(self,started: bool):
        self._started = started

    def set_status(self,status: int):
        self._status = status
    
    def set_headers(self,headers):
        self._headers = headers

    def set_scope(self,scope):
        self._scope = scope

    def started(self):
        return self._started
    
    def status(self):
        return self._status
    
    def headers(self):
        return self._headers
    
    def scope(self):
        return self._scope

