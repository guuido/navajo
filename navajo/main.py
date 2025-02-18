
from navajo.server import Server
import logging

def run(app: callable):
    setup_logging()
    server = Server(app)
    server.run()

def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,  # Set the default logging level
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Customize log format
        handlers=[
            logging.StreamHandler()  # Default to stream output (console)
            # You can add FileHandler here if you want to log to a file as well
            # logging.FileHandler('my_log.log')
        ]
)