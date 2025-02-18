from enum import Enum
from io import BytesIO
from typing import Optional

from navajo.utils import BadRequestError, UnsupportedProtocolError

class ParserError(Enum):
    BAD_REQUEST = 1
    LENGTH_REQUIRED = 2

class ParserState(Enum):
    RECEIVING_HEADERS = 1
    RECEIVING_BODY = 2
    COMPLETE = 3
    RECEIVING_CHUNKS = 4
    CHUNKS_COMPLETE = 5
    ERROR = 6

class RequestBuffer:
    def __init__(self):
        self.buffer = BytesIO()
        self.state = ParserState.RECEIVING_HEADERS
        self.content_length: Optional[int] = None
        self.is_chunked: bool = False
        self._headers_end: Optional[int] = None
        self.error: Optional[ParserError] = None

    def feed_data(self, data: bytes) -> bool:
        """
        Feed new data into the buffer.
        """
        self.buffer.seek(0, 2)  # Move to end
        current_position = self.buffer.tell()
        self.buffer.write(data)
        self.buffer.seek(current_position) 
        
        self._try_parse()
        return self.state in (ParserState.COMPLETE, ParserState.CHUNKS_COMPLETE)
    
    def _try_parse(self):
        """
        Try to parse the current buffer content.
        Returns True if a complete request is available.
        """
        if self.state == ParserState.RECEIVING_HEADERS:
            # Look for headers/body separator
            current_position = self.buffer.tell()
            self.buffer.seek(0)
            data = self.buffer.getvalue()
            self.buffer.seek(current_position) 
            separator_index = data.find(b'\r\n\r\n')
            
            if separator_index != -1:
                self._headers_end = separator_index + 4
                headers_data = data[:separator_index].decode('latin1')

                # Headers are complete, check if body is chunked
                self.is_chunked = self._get_is_chunked(headers_data)
                if self.is_chunked is True:
                    self.state = ParserState.RECEIVING_CHUNKS
                    # Check if there is already a chunk with size zero
                    current_body_size = self.buffer.getbuffer().nbytes - self._headers_end
                    if current_body_size > 0:
                        try:
                            final_chunk = self._has_final_chunk()
                            if final_chunk is True:
                                self.state = ParserState.CHUNKS_COMPLETE
                        except BadRequestError:
                            self.state = ParserState.ERROR
                            self.error = ParserError.BAD_REQUEST
                            return
                else:
                    # Body is not chunked, try to get content length
                    self.content_length = self._get_content_length(headers_data)
                    # Get HTTP method to check if content-length should be present
                    try:
                        method = self._get_http_method(headers_data)
                        body_required = True if method in ('PUT', 'POST', 'PATCH') else False
                    except BadRequestError:
                        self.state = ParserState.ERROR
                        self.error = ParserError.BAD_REQUEST
                        return

                    if self.content_length is None and body_required:
                        self.state = ParserState.ERROR
                        self.error = ParserError.BAD_REQUEST
                        return
                    if (self.content_length is None and not body_required) or self.content_length == 0: # No body
                        self.state = ParserState.COMPLETE
                        return
                    else:
                        self.state = ParserState.RECEIVING_BODY 
                        # Check if the body is already available in the buffer
                        current_body_size = self.buffer.getbuffer().nbytes - self._headers_end
                        if current_body_size >= self.content_length:
                            self.state = ParserState.COMPLETE
                            return
        
        elif self.state == ParserState.RECEIVING_BODY:
            current_body_size = self.buffer.getbuffer().nbytes - self._headers_end
            if self.content_length is None or current_body_size >= self.content_length:
                self.state = ParserState.COMPLETE
                return
        
        elif self.state == ParserState.RECEIVING_CHUNKS:
            try:
                final_chunk = self._has_final_chunk()
                if final_chunk is True:
                    self.state = ParserState.CHUNKS_COMPLETE
            except BadRequestError:
                self.state = ParserState.ERROR
                self.error = ParserError.BAD_REQUEST
                return

    def _has_final_chunk(self):
        current_position = self.buffer.tell()
        self.buffer.seek(0)
        data = self.buffer.getvalue()
        self.buffer.seek(current_position)
        chunks = data[self._headers_end:]

        while chunks:
            # Check for chunk size line
            chunk_size_end = chunks.find(b'\r\n')
            if chunk_size_end == -1:  # No CRLF found - might be incomplete
                return False   
            # Try to parse chunk size
            try:
                chunk_size_hex = chunks[:chunk_size_end].split(b';')[0]  # Handle chunk extensions
                chunk_size = int(chunk_size_hex, 16)
            except ValueError:  # Malformed chunk size
                raise BadRequestError()
            # Found a zero chunk - check if it's complete
            if chunk_size == 0:
                if len(chunks) < chunk_size_end + 4:  # Need to wait for \r\n\r\n
                    return False
                elif len(chunks) == chunk_size_end + 4:
                    if chunks[chunk_size_end:chunk_size_end + 4] != b'\r\n\r\n':
                        raise BadRequestError()
                    else:
                        return True
                else:
                    raise BadRequestError() # There is data after closing chunk
                
            # Calculate full chunk size including size line, data, and trailing CRLF
            full_chunk_size = chunk_size_end + 2 + chunk_size + 2
            
            # Check if we have the complete chunk
            if full_chunk_size > len(chunks):  # Incomplete chunk
                return False
                
            if chunks[chunk_size_end + 2 + chunk_size:chunk_size_end + 2 + chunk_size + 2] != b'\r\n':
                raise BadRequestError()  # Malformed chunk
                
            # Move to next chunk
            chunks = chunks[full_chunk_size:]
        
        return False     
    
    def _get_is_chunked(self, headers: str) -> bool:
        """Extract Transfer-Encoding:chunked from headers if present."""
        for line in headers.split('\r\n'):
            if line.lower().startswith('transfer-encoding:'):
                return line.split(':', 1)[1].strip() == 'chunked'
        return False
    
    def _get_content_length(self, headers: str) -> Optional[int]:
        """Extract Content-Length from headers if present."""
        for line in headers.split('\r\n'):
            if line.lower().startswith('content-length:'):
                return int(line.split(':', 1)[1].strip())
        return None
    
    def _get_http_method(self, headers: str) -> str:
        """Extract http method from headers"""
        lines = headers.split('\r\n')
        first_line = lines[0].split(' ')
        if  len(first_line) != 3:
            raise BadRequestError()
        return first_line[0]
    
    def get_last_chunks(self) -> bytes:
        """
        Return last chunks received.
        Should only be called when some chunks available.
        """
        if self.state not in (ParserState.RECEIVING_CHUNKS, ParserState.CHUNKS_COMPLETE):
            raise RuntimeError("Server is not receiving chunks")
            
        current_position = self.buffer.tell()
        data = self.buffer.getvalue()
        chunk = data[current_position:]
        chunked_body = b''

        while chunk:
            chunk_size_end = chunk.find(b'\r\n')
            if chunk_size_end == -1:
                raise BadRequestError()
            chunk_size_hex = chunk[:chunk_size_end].split(b';')[0]  # Handle chunk extensions
            chunk_size = int(chunk_size_hex, 16)
            full_chunk_size = chunk_size_end + 2 + chunk_size + 2
            if full_chunk_size > len(chunk):
                raise BadRequestError()
            chunk_value = chunk[chunk_size_end+2:chunk_size_end+2+chunk_size]
            chunked_body += chunk_value
            chunk = chunk[full_chunk_size:]
        
        return chunked_body
    
    def get_request_headers(self) -> bytes:
        """
        Return the headers as byte string.
        Should only be called when headers are available.
        """
        if self.state not in (ParserState.COMPLETE, ParserState.CHUNKS_COMPLETE, ParserState.RECEIVING_BODY, ParserState.RECEIVING_CHUNKS):
            raise RuntimeError("Headers are not available yet")
            
        data = self.buffer.getvalue()
        headers = data[:self._headers_end]
        
        return headers
    
    def get_request_body(self) -> bytes:
        """
        Return the body as byte string.
        Should only be called when body is available.
        """
        if self.state not in (ParserState.COMPLETE, ParserState.CHUNKS_COMPLETE):
            raise RuntimeError("Body is not available yet")
            
        data = self.buffer.getvalue()
        if self.state == ParserState.COMPLETE:
            body = data[self._headers_end:self._headers_end + self.content_length] if self.content_length else b''
        else:
            chunk = data[self._headers_end:]
            chunked_body = b''

            while chunk:
                chunk_size_end = chunk.find(b'\r\n')
                if chunk_size_end == -1:
                    raise BadRequestError()
                chunk_size_hex = chunk[:chunk_size_end].split(b';')[0]  # Handle chunk extensions
                chunk_size = int(chunk_size_hex, 16)
                full_chunk_size = chunk_size_end + 2 + chunk_size + 2
                if full_chunk_size > len(chunk):
                    raise BadRequestError()
                chunk_value = chunk[chunk_size_end+2:chunk_size_end+chunk_size+2]
                chunked_body += chunk_value
                chunk = chunk[full_chunk_size:]

            body = chunked_body
        
        return body
    
    def get_request_data(self) -> tuple[bytes, bytes]:
        """
        Return the headers and body as separate byte strings.
        Should only be called when a complete request is available.
        """
        headers = self.get_request_headers()
        body = self.get_request_body()
        
        return headers, body
    
    def parse_headers(self, headers: bytes) -> dict:
        """Parse raw headers to ASGI format."""
        header_lines = headers.decode('latin1').split('\r\n')
        
        # Parse first line
        first_line = header_lines[0].split(' ')
        if  len(first_line) != 3:
            raise BadRequestError()
        method = first_line[0]
        full_path = first_line[1]
        protocol = first_line[2]

        if method not in ('GET','POST','PUT','DELETE','HEAD','CONNECT','OPTIONS','TRACE','PATCH'):
            raise BadRequestError()

        # Check protocol version
        version = protocol.split('/')
        if  len(version) != 2:
            raise BadRequestError()
        elif version[1] not in ('1.0','1','1.1'):
            raise UnsupportedProtocolError(version)
        
        # Extract path string
        path = full_path.split('?')[0]

        # Extract raw path and query string
        raw_headers_bytes = headers
        first_line_bytes = raw_headers_bytes.split(b'\r\n')[0]  # First line in bytes
        raw_path_start = first_line_bytes.find(b' ') + 1  # Start of path
        raw_query_start = first_line_bytes.find(b'?', raw_path_start)  # Start of query string
        if raw_query_start == -1:
            # Extract raw path bytes (without query string)
            raw_path = first_line_bytes[raw_path_start:first_line_bytes.find(b' ',raw_path_start)]
            query = b''
        else:
            # Query string exists
            raw_path = first_line_bytes[raw_path_start:raw_query_start]
            query = first_line_bytes[raw_query_start + 1:first_line_bytes.find(b' ', raw_query_start)]
        
        # Parse headers into list of tuples
        parsed_headers = []
        has_host = False
        for line in header_lines[1:]:
            if not line or line.startswith(':'):
                continue
            try:
                name, value = line.split(':', 1)
            except ValueError:
                raise BadRequestError()
            if name.strip().lower() == 'host' and value != '':
                has_host = True
            parsed_headers.append(
                (name.strip().lower().encode('latin1'),
                 value.strip().encode('latin1'))
            )

        # Enforce host requirement for HTTP/1.1 
        if has_host is False:
            raise BadRequestError()
            
        return {
            'method': method,
            'path': path,
            'raw_path': raw_path,
            'query_string': query,
            'headers': parsed_headers,
            'http_version': protocol.split('/')[-1]
        }