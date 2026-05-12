"""
config/logger.py — Настройка логирования через loguru
"""
import sys
import os
from loguru import logger
from config.settings import config


def setup_logger():
    os.makedirs(os.path.dirname(config.log_file), exist_ok=True)

    logger.remove()

    # Консоль
    logger.add(
        sys.stdout,
        level=config.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # Файл
    logger.add(
        config.log_file,
        level=config.log_level,
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
    )

    return logger


setup_logger()
