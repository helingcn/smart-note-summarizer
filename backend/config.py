import logging

logging.basicConfig(
    filename="smartdigest.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("smartdigest")