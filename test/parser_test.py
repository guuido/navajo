from navajo.protocols.http.parser import ParserError, ParserState, RequestBuffer
from navajo.utils import BadRequestError, UnsupportedProtocolError
import pytest

@pytest.fixture
def parser():
    return RequestBuffer()

def test_feed_data(parser):
    data = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
    parser.feed_data(data)

    assert data == parser.buffer.read()
    assert parser.buffer.tell() == len(data)

def test_try_parse_no_body_complete(parser):
    data = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
    parser.feed_data(data)

    assert parser.state == ParserState.COMPLETE

def test_try_parse_body_complete(parser):
    data = b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n\r\nHello, World"
    parser.feed_data(data)

    assert parser.state == ParserState.COMPLETE

def test_try_parse_body_incomplete(parser):
    data = b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n\r\nHello,"
    parser.feed_data(data)

    assert parser.state == ParserState.RECEIVING_BODY

def test_try_parse_receiving_headers(parser):
    data = b"GET / HTTP/1.1\r\nHost: "
    parsed = parser.feed_data(data)

    assert parsed == False
    assert parser.state == ParserState.RECEIVING_HEADERS

def test_try_parse_no_body_stream(parser):
    parts = [
        b"GET / HTTP/1.1\r\n",
        b"Host: example.com\r\n",
        b"\r\n",
    ]

    for i in range(len(parts)):
        parser.feed_data(parts[i])
        if i != 2:
            assert parser.state == ParserState.RECEIVING_HEADERS
        else:
            assert parser.state == ParserState.COMPLETE

def test_try_parse_body_stream(parser):
    parts = [
        b"POST /submit ",
        b"HTTP/1.1\r\n",
        b"Content-Length: 12\r\n\r\n",
        b"Hello, ",
        b"World"
    ]

    for i in range(len(parts)):
        parser.feed_data(parts[i])
        if i == 0 or i == 1:
            assert parser.state == ParserState.RECEIVING_HEADERS
        elif i == 2 or i == 3:
            assert parser.state == ParserState.RECEIVING_BODY
        else:
            assert parser.state == ParserState.COMPLETE

def test_try_parse_chunked(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\n",
        b"Host: example.com\r\n",
        b"Transfer-Encoding: chunked\r\n",
        b"Content-Type: application/octet-stream\r\n\r\n",
        b"5\r\nHello\r\n",
        b"6\r\nWorld!\r\n",
        b"0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    if i <= 3:
        assert parser.state == ParserState.RECEIVING_HEADERS
    elif i > 3 and i < 6:
        assert parser.state == ParserState.RECEIVING_CHUNKS
    else:
        assert parser.state == ParserState.CHUNKS_COMPLETE

def test_try_parse_multiple_chunks(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\n",
        b"Host: example.com\r\n",
        b"Transfer-Encoding: chunked\r\n",
        b"Content-Type: application/octet-stream\r\n\r\n",
        b"5\r\nHello\r\n6\r\nWorld!\r\n",
        b"0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    if i <= 3:
        assert parser.state == ParserState.RECEIVING_HEADERS
    elif i > 3 and i < 5:
        assert parser.state == ParserState.RECEIVING_CHUNKS
    else:
        assert parser.state == ParserState.CHUNKS_COMPLETE

def test_try_parse_mixed_chunks(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\n",
        b"Host: example.com\r\n",
        b"Transfer-Encoding: chunked\r\n",
        b"Content-Type: application/octet-stream\r\n\r\n",
        b"5\r\nHello\r\n6\r\nWor",
        b"ld!\r\n0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    if i <= 3:
        assert parser.state == ParserState.RECEIVING_HEADERS
    elif i > 3 and i < 5:
        assert parser.state == ParserState.RECEIVING_CHUNKS
    else:
        assert parser.state == ParserState.CHUNKS_COMPLETE

    assert parser.get_request_body() == b"HelloWorld!"

def test_try_parse_chunked_malformed_chunk_no_size_crlf(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"5Hello\r\n",
        b"6\r\nWorld!\r\n",
        b"0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    if i < 1:
        assert parser.state == ParserState.RECEIVING_HEADERS
    else:
        assert parser.state == ParserState.ERROR
        assert parser.error == ParserError.BAD_REQUEST

def test_try_parse_chunked_malformed_chunk_no_end_crlf(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"5\r\nHello\r\n",
        b"6\r\nWorld!",
        b"0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    if i < 2:
        assert parser.state == ParserState.RECEIVING_HEADERS
    else:
        assert parser.state == ParserState.ERROR
        assert parser.error == ParserError.BAD_REQUEST

def test_try_parse_chunked_malformed_chunk_no_crlf(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"5\r\nHello\r\n",
        b"6World!",
        b"0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    if i < 2:
        assert parser.state == ParserState.RECEIVING_HEADERS
    else:
        assert parser.state == ParserState.ERROR
        assert parser.error == ParserError.BAD_REQUEST

def test_try_parse_chunked_malformed_chunk_no_last_crlf(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"5\r\nHello\r\n",
        b"6\r\nWorld!\r\n",
        b"0\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    if i < 3:
        assert parser.state == ParserState.RECEIVING_HEADERS
    else:
        assert parser.state == ParserState.RECEIVING_CHUNKS

def test_get_last_chunks_single(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"5\r\nHello\r\n",
        b"6\r\nWorld!\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    
    last_chunk = parser.get_last_chunks()
    assert last_chunk == b'World!'

def test_get_last_chunks_single_closing(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"5\r\nHello\r\n",
        b"6\r\nWorld!\r\n",
        b"0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    
    last_chunk = parser.get_last_chunks()
    assert last_chunk == b''

def test_get_last_chunks_multiple(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"6\r\nHello \r\n6\r\nWorld!\r\n0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])
    
    last_chunk = parser.get_last_chunks()
    assert last_chunk == b'Hello World!'

def test_get_request_headers_success(parser):
    data = b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n\r\nHello, World"
    parser.feed_data(data)

    headers = parser.get_request_headers()

    assert type(headers) == bytes
    assert headers  == b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n\r\n"

def test_get_request_headers_failure(parser):
    data = b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n"
    parser.feed_data(data)

    with pytest.raises(RuntimeError):
        parser.get_request_headers()

def test_get_request_body_success(parser):
    data = b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n\r\nHello, World"
    parser.feed_data(data)

    body = parser.get_request_body()

    assert type(body) == bytes
    assert body  == b"Hello, World"

def test_get_request_body_failure(parser):
    data = b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n"
    parser.feed_data(data)

    with pytest.raises(RuntimeError):
        parser.get_request_body()

def test_get_request_body_chunked_success(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"6\r\nHello \r\n6\r\nWorld!\r\n0\r\n\r\n"
    ]

    for i in range(len(chunks)):
        parser.feed_data(chunks[i])

    body = parser.get_request_body()

    assert type(body) == bytes
    assert body  == b"Hello World!"

def test_get_request_body_chunked_failure(parser):
    chunks = [
        b"POST /upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding:chunked\r\nContent-Type: application/octet-stream\r\n\r\n",
        b"6\r\nHello \r\n6\r\nWorld!\r\n"
    ]
    
    for i in range(len(chunks)):
        parser.feed_data(chunks[i])

    with pytest.raises(RuntimeError):
        parser.get_request_body()

def test_get_request_data_success(parser):
    data = b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n\r\nHello, World"
    parser.feed_data(data)

    assert parser.state == ParserState.COMPLETE

    parsed_req = parser.get_request_data()

    assert type(parsed_req) == tuple
    assert parsed_req[0] == b"POST /submit HTTP/1.1\r\nContent-Length: 12\r\n\r\n"
    assert parsed_req[1] == b"Hello, World"

def test_get_request_data_failure(parser):
    with pytest.raises(RuntimeError):
        parser.get_request_data()

def test_parse_headers(parser):
    test_case_1 =  b"GET /index.html HTTP/1.1\r\nHost: example.com\r\nUser-Agent: curl/7.64.1\r\nAccept: */*\r\n\r\n" # Simple GET
    expected_1 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'',
        'headers': [
            (b'host',b'example.com'),
            (b'user-agent',b'curl/7.64.1'),
            (b'accept',b'*/*')
        ],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_1) == expected_1

    test_case_2 = b"GET /index.html HTTP/1.1\r\n\r\n" # Empty headers (at least host is required)
    with pytest.raises(BadRequestError):
        parser.parse_headers(test_case_2)

    test_case_3 = b"GET /index.html HTTP/1.1 Extra\r\nHost: example.com\r\n\r\n" # Malformed first line
    with pytest.raises(BadRequestError):
        parser.parse_headers(test_case_3)

    test_case_4 = b"GET /index.html HTTP/2.0\r\nHost: example.com\r\n\r\n" # Unsupported protocol
    with pytest.raises(UnsupportedProtocolError):
        parser.parse_headers(test_case_4)

    test_case_5 = b"GET /index.html?param1=value1&param2=value2 HTTP/1.1\r\nHost: example.com\r\n\r\n" # Query params
    expected_5 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'param1=value1&param2=value2',
        'headers': [(b'host', b'example.com')],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_5) == expected_5

    test_case_6 = b"GET /index.html? HTTP/1.1\r\nHost: example.com\r\n\r\n" # Empty query string
    expected_6 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'',
        'headers': [(b'host', b'example.com')],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_6) == expected_6

    test_case_7 = b"GET /index.html HTTP/1.1\r\nHost: example.com\r\nAccept: text/html\r\nAccept: application/json\r\n\r\n" # Headers with same name
    expected_7 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'',
        'headers': [
            (b'host', b'example.com'),
            (b'accept', b'text/html'),
            (b'accept', b'application/json')
        ],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_7) == expected_7

    test_case_8 = b"GET /index.html HTTP/1.1\r\nHost: example.com \r\n Accept: */*\r\n\r\n" # Headers with trailing/leading whitespaces
    expected_8 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'',
        'headers': [
            (b'host', b'example.com'),
            (b'accept', b'*/*')
        ],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_8) == expected_8

    test_case_9 = b"GET /index.html HTTP/1.1\r\nHost:example.com\r\nAccept:\r\n\r\n" # Headers with no value
    expected_9 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'',
        'headers': [
            (b'host', b'example.com'),
            (b'accept', b'')
        ],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_9) == expected_9

    test_case_10 = b"GET /index.html HTTP/1.1\r\nHost: example.com\r\nX-Custom-Header: value:with:colons\r\n\r\n" # Header with colons in value
    expected_10 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'',
        'headers': [
            (b'host', b'example.com'),
            (b'x-custom-header', b'value:with:colons')
        ],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_10) == expected_10

    test_case_11 = b"GET /index.html HTTP/1.1\r\nHost example.com\r\nAccept: */*\r\n\r\n" # Header without colons
    with pytest.raises(BadRequestError):
        parser.parse_headers(test_case_11)

    test_case_12 = b"" # Empty request
    with pytest.raises(BadRequestError):
        parser.parse_headers(test_case_12)

    test_case_13 = b"\r\n" # Request with only CRLF
    with pytest.raises(BadRequestError):
        parser.parse_headers(test_case_13)

    test_case_14 = b"GET /index.html HTTP/1.1\r\nHost: example.com\r\nX-Custom-Header: " + "café".encode('latin1') + b"\r\n\r\n" # Request with non-ASCII chars
    expected_14 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'',
        'headers': [
            (b'host', b'example.com'),
            (b'x-custom-header', b'caf\xe9')
        ],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_14) == expected_14

    test_case_15 = b"GET /index.html HTTP/1.1\r\n\r\nHost: example.com\r\n\r\nAccept: */*\r\n\r\n" # Request with multiple CRLFs
    expected_15 = {
        'method': 'GET',
        'path': '/index.html',
        'raw_path': b'/index.html',
        'query_string': b'',
        'headers': [
            (b'host', b'example.com'),
            (b'accept', b'*/*')
        ],
        'http_version': '1.1'
    }

    assert parser.parse_headers(test_case_15) == expected_15 # Shouldn't happen because first line would be treated as headers by the protocol

    test_case_16 = b"INVALID /index.html HTTP/1.1\r\nHost: example.com\r\n\r\n" # Invalid method
    with pytest.raises(BadRequestError):
        parser.parse_headers(test_case_16)

    test_case_17 = b"GET /index.html HTTP/1.1 \r\nHost: example.com\r\nAccept: */*\r\n\r\n" # First line trailing whitespace
    with pytest.raises(BadRequestError):
        parser.parse_headers(test_case_17)