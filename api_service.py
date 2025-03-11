"""
Rick and Morty API Service
==========================
A FastAPI service that provides endpoints to access Rick and Morty data.
"""
import asyncio
import logging
from typing import Optional, Any
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
import os
from datetime import datetime
import redis.asyncio as redis

from client import RickAndMortyClient, NotFoundError, RateLimitError, ServerError, APIError
from rate_limiter import SimpleRateLimiter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Rick and Morty API Service",
    description="A service that provides access to Rick and Morty data",
    version="1.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create a rate limiter instance
rate_limiter = SimpleRateLimiter(requests_per_minute=30)

# Redis connection for caching
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
CACHE_TTL = int(os.environ.get("CACHE_TTL", 3600))

redis_client = None

# Middleware for rate limiting
@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    client_ip = request.client.host

    # You can exempt certain paths from rate limiting
    if request.url.path == "/health":
        return await call_next(request)

    if rate_limiter.is_rate_limited(client_ip):
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."},
            headers={"Retry-After": "60"}
        )

    response = await call_next(request)
    return response

# Add security headers middleware
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# Global exception handler for client errors
@app.exception_handler(NotFoundError)
async def not_found_exception_handler(request: Request, exc: NotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": exc.message}
    )

@app.exception_handler(RateLimitError)
async def rate_limit_exception_handler(request: Request, exc: RateLimitError):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": exc.message},
        headers={"Retry-After": str(exc.retry_after)}
    )

@app.exception_handler(ServerError)
async def server_error_exception_handler(request: Request, exc: ServerError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The Rick and Morty API is currently unavailable. Please try again later."}
    )

@app.exception_handler(APIError)
async def api_error_exception_handler(request: Request, exc: APIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message}
    )

# Dependencies
async def get_rick_and_morty_client():
    """Dependency to get the Rick and Morty API client."""
    async with RickAndMortyClient() as client:
        yield client

# Redis connection events
@app.on_event("startup")
async def startup_event():
    global redis_client
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")

@app.on_event("shutdown")
async def shutdown_event():
    if redis_client:
        await redis_client.close()
        logger.info("Disconnected from Redis")

# Redis cache functions
async def get_cache(key: str) -> Optional[Any]:
    """Get data from Redis cache if it exists."""
    if redis_client:
        try:
            cached_data = await redis_client.get(key)
            if cached_data:
                return json.loads(cached_data)
        except redis.RedisError as e:
            logger.error(f"Redis error when getting {key}: {e}")
    return None

async def set_cache(key: str, data: Any) -> None:
    """Set data in Redis cache with expiration time."""
    if redis_client:
        try:
            await redis_client.set(key, json.dumps(data), ex=CACHE_TTL)
        except redis.RedisError as e:
            logger.error(f"Redis error when setting {key}: {e}")

async def invalidate_cache(pattern: str) -> None:
    """Invalidate cache entries matching a pattern."""
    if redis_client:
        try:
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis_client.delete(*keys)
                if cursor == 0:
                    break
        except redis.RedisError as e:
            logger.error(f"Redis error when invalidating cache {pattern}: {e}")

# Validate character filters to prevent injection or abuse
def validate_character_filters(
    name: Optional[str] = None,
    status: Optional[str] = None,
    species: Optional[str] = None,
    page: int = Query(1, ge=1, le=100),  # Limit max page to prevent DoS
):
    errors = []

    # Validate fields
    if name and len(name) > 100:
        errors.append("Name is too long (max 100 characters)")

    if status and status.lower() not in ["alive", "dead", "unknown"]:
        errors.append("Status must be one of: alive, dead, unknown")

    if species and len(species) > 100:
        errors.append("Species is too long (max 100 characters)")

    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    # Return validated filters
    return {
        "name": name,
        "status": status.lower() if status else None,
        "species": species,
        "page": page
    }

# API Routes
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/characters")
async def get_characters(
    name: Optional[str] = None,
    status: Optional[str] = None,
    species: Optional[str] = None,
    page: int = Query(1, ge=1, le=100),
    client: RickAndMortyClient = Depends(get_rick_and_morty_client)
):
    """
    Get characters with optional filtering.

    - **name**: Filter by character name
    - **status**: Filter by character status (alive, dead, unknown)
    - **species**: Filter by character species
    - **page**: Page number for paginated results
    """
    # Validate filters
    validated_filters = validate_character_filters(name, status, species, page)

    # Build cache key
    cache_key = f"characters:{json.dumps(validated_filters)}"

    # Try to get from cache
    cached_data = await get_cache(cache_key)
    if cached_data:
        return cached_data

    # Fetch from API
    try:
        data = await client.get_characters(validated_filters)
        # Cache the result
        await set_cache(cache_key, data)
        return data
    except Exception as e:
        logger.error(f"Error fetching characters: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch characters")

@app.get("/characters/{character_id}")
async def get_character(
    character_id: int,
    client: RickAndMortyClient = Depends(get_rick_and_morty_client)
):
    """
    Get a specific character by ID.

    - **character_id**: The ID of the character to fetch
    """
    # Validate ID
    if character_id <= 0:
        raise HTTPException(status_code=400, detail="Character ID must be positive")

    cache_key = f"character:{character_id}"

    # Try to get from cache
    cached_data = await get_cache(cache_key)
    if cached_data:
        return cached_data

    # Fetch from API - errors will be handled by exception handlers
    data = await client.get_character(character_id)
    # Cache the result
    await set_cache(cache_key, data)
    return data

@app.get("/locations")
async def get_locations(
    name: Optional[str] = None,
    type: Optional[str] = None,
    dimension: Optional[str] = None,
    page: int = Query(1, ge=1, le=100),
    client: RickAndMortyClient = Depends(get_rick_and_morty_client)
):
    """
    Get locations with optional filtering.

    - **name**: Filter by location name
    - **type**: Filter by location type
    - **dimension**: Filter by location dimension
    - **page**: Page number for paginated results
    """
    # Validate filters (simplified version)
    filters = {"name": name, "type": type, "dimension": dimension, "page": page}
    filters = {k: v for k, v in filters.items() if v is not None}

    cache_key = f"locations:{json.dumps(filters)}"

    # Try to get from cache
    cached_data = await get_cache(cache_key)
    if cached_data:
        return cached_data

    # Fetch from API
    try:
        data = await client.get_locations(filters)
        # Cache the result
        await set_cache(cache_key, data)
        return data
    except Exception as e:
        logger.error(f"Error fetching locations: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch locations")

@app.get("/locations/{location_id}")
async def get_location(
    location_id: int,
    client: RickAndMortyClient = Depends(get_rick_and_morty_client)
):
    """
    Get a specific location by ID.

    - **location_id**: The ID of the location to fetch
    """
    # Validate ID
    if location_id <= 0:
        raise HTTPException(status_code=400, detail="Location ID must be positive")

    cache_key = f"location:{location_id}"

    # Try to get from cache
    cached_data = await get_cache(cache_key)
    if cached_data:
        return cached_data

    # Fetch from API - errors will be handled by exception handlers
    data = await client.get_location(location_id)
    # Cache the result
    await set_cache(cache_key, data)
    return data

@app.get("/episodes")
async def get_episodes(
    name: Optional[str] = None,
    episode: Optional[str] = None,
    page: int = Query(1, ge=1, le=100),
    client: RickAndMortyClient = Depends(get_rick_and_morty_client)
):
    """
    Get episodes with optional filtering.

    - **name**: Filter by episode name
    - **episode**: Filter by episode code (e.g. S01E01)
    - **page**: Page number for paginated results
    """
    # Validate filters (simplified version)
    filters = {"name": name, "episode": episode, "page": page}
    filters = {k: v for k, v in filters.items() if v is not None}

    cache_key = f"episodes:{json.dumps(filters)}"

    # Try to get from cache
    cached_data = await get_cache(cache_key)
    if cached_data:
        return cached_data

    # Fetch from API
    try:
        data = await client.get_episodes(filters)
        # Cache the result
        await set_cache(cache_key, data)
        return data
    except Exception as e:
        logger.error(f"Error fetching episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch episodes")

@app.get("/episodes/{episode_id}")
async def get_episode(
    episode_id: int,
    client: RickAndMortyClient = Depends(get_rick_and_morty_client)
):
    """
    Get a specific episode by ID.

    - **episode_id**: The ID of the episode to fetch
    """
    # Validate ID
    if episode_id <= 0:
        raise HTTPException(status_code=400, detail="Episode ID must be positive")

    cache_key = f"episode:{episode_id}"

    # Try to get from cache
    cached_data = await get_cache(cache_key)
    if cached_data:
        return cached_data

    # Fetch from API - errors will be handled by exception handlers
    data = await client.get_episode(episode_id)
    # Cache the result
    await set_cache(cache_key, data)
    return data

@app.get("/cache/clear")
async def clear_cache(pattern: str = "*"):
    """
    Clear cache entries matching a pattern.

    - **pattern**: Redis key pattern to match (default: "*" which clears all cache)
    """
    try:
        await invalidate_cache(pattern)
        return {"status": "success", "message": f"Cache cleared for pattern: {pattern}"}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear cache")

@app.get("/download/all")
async def download_all_data(background_tasks: BackgroundTasks):
    """
    Start a background task to download all data.
    This will save all characters, locations, and episodes to the 'rickmorty_data' directory.
    The download happens in the background to prevent blocking the request.
    """
    background_tasks.add_task(download_data_task)
    return {"status": "Download started in background", "message": "Data will be saved to the rickmorty_data directory"}

async def download_data_task():
    """Background task to download all data."""
    logger.info("Starting background download of all Rick and Morty data")
    try:
        async with RickAndMortyClient() as client:
            # Fetch all data types concurrently
            characters_task = asyncio.create_task(client.get_characters())
            locations_task = asyncio.create_task(client.get_locations())
            episodes_task = asyncio.create_task(client.get_episodes())

            # Wait for all tasks to complete
            characters = await characters_task
            locations = await locations_task
            episodes = await episodes_task

            # Save data to files
            os.makedirs("rickmorty_data", exist_ok=True)

            with open("rickmorty_data/characters.json", "w") as f:
                json.dump(characters, f, indent=2)

            with open("rickmorty_data/locations.json", "w") as f:
                json.dump(locations, f, indent=2)

            with open("rickmorty_data/episodes.json", "w") as f:
                json.dump(episodes, f, indent=2)

            logger.info(f"Saved {len(characters)} characters, {len(locations)} locations, and {len(episodes)} episodes")
    except Exception as e:
        logger.error(f"Error downloading all data: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)