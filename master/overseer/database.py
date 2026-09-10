"""MongoDB and Beanie Database initialization."""

import logging
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from overseer.config import get_settings
from overseer.models import ALL_DOCUMENT_MODELS

logger = logging.getLogger("overseer.database")

client: AsyncIOMotorClient = None


async def init_db(client_override: AsyncIOMotorClient = None, db_name_override: str = None) -> None:
    """Initialize Beanie ODM with MongoDB client."""
    global client
    settings = get_settings()

    if client_override:
        client = client_override
        db_name = db_name_override or settings.MONGODB_DATABASE
    else:
        client = AsyncIOMotorClient(settings.MONGODB_URL)
        db_name = settings.MONGODB_DATABASE

    db = client[db_name]
    await init_beanie(database=db, document_models=ALL_DOCUMENT_MODELS)
    logger.info(f"Connected to MongoDB database: {db_name}")


async def close_db() -> None:
    """Close MongoDB connections."""
    global client
    if client:
        client.close()
        logger.info("MongoDB client connection closed")
