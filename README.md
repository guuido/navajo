# Navajo - A Lightweight ASGI Server

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

ASGI server implementation with no dependencies, currently in development. This server is designed to handle ASGI applications and provides basic HTTP/1.1 support.

**Note:** This project is still under active development and is not yet production-ready. Contributions and feedback are welcome!

## Features

- **ASGI Compliance**: Compliant with the ASGI specification for asynchronous web servers.
- **HTTP/1.1 Support**: Currently supports HTTP/1.1 protocol.
- **Lifespan Events**: Handles ASGI lifespan events (`startup` and `shutdown`) for proper application initialization and cleanup.
- **Signal Handling**: Gracefully handles shutdown signals (`SIGTERM` and `SIGINT`).
- **No Dependencies**: The core server has **zero external dependencies**, making it lightweight and easy to integrate. (Note: optional dependencies are required only for running tests.)

## Installation
You can try Navajo by cloning the repository and installing it locally.

### Clone the Repository
```bash
git clone https://github.com/guuido/navajo.git
cd navajo
```
### Install the Package
You can install Navajo in editable mode using `pip`:
```bash
pip install -e .
```
To run tests or contribute to the project, install the optional development dependencies:
```bash
pip install -e ".[dev]"
```

## Usage
To run the server with your ASGI application, use the `run` function provided in the `navajo` package:
```python
from navajo import run

async def app(scope, receive, send):
    assert scope["type"] == "http"
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"text/plain"],
        ],
    })
    await send({
        "type": "http.response.body",
        "body": b"Hello, World!",
    })

run(app)
```

## Running tests
To run the tests, ensure you have installed the optional development dependencies (`pytest` and `pytest-asyncio`). Then, use the following command:
```bash
pytest
```

## Contributing
Contributions are welcome! If you'd like to contribute, please follow these steps:
1. Fork the repository.
2. Create a new branch for your feature or bugfix.
3. Submit a pull request with a detailed description of your changes.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
