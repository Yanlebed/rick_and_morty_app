import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Any, Union

class APIError(Exception):
    """Base exception for API errors"""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error {status_code}: {message}")

class NotFoundError(APIError):
    """Resource not found error"""
    def __init__(self, resource_type: str, resource_id: Optional[Union[int, str]] = None):
        message = f"{resource_type} not found"
        if resource_id is not None:
            message = f"{resource_type} with ID {resource_id} not found"
        super().__init__(404, message)

class RateLimitError(APIError):
    """Rate limit exceeded error"""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(429, f"Rate limit exceeded. Try again in {retry_after} seconds")

class ServerError(APIError):
    """Server-side error"""
    def __init__(self):
        super().__init__(500, "Internal server error")

class RickAndMortyClient:

    BASE_URL = "https://rickandmortyapi.com/api"

    def __init__(self,
                 session: Optional[aiohttp.ClientSession] = None,
                 max_retries: int = 3,
                 timeout: int = 10):
        """
        Initialize the Rick and Morty API client.

        Args:
            session: Optional aiohttp.ClientSession. If not provided, a new session will be created.
            max_retries: Maximum number of retries for failed requests.
            timeout: Timeout for each request in seconds.
        """
        self._session = session
        self._own_session = session is None
        self._max_retries = max_retries
        self._timeout = timeout
        self._logger = logging.getLogger(__name__)

    async def __aenter__(self):
        if self._own_session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._own_session and self._session:
            await self._session.close()

    async def _make_request(self, endpoint: str) -> Dict[str, Any]:
        """
        Make an HTTP request to the API with comprehensive error handling.

        Args:
            endpoint: API endpoint to request

        Returns:
            JSON response as dictionary

        Raises:
            NotFoundError: If the resource is not found (404)
            RateLimitError: If the rate limit is exceeded (429)
            ServerError: If the server returns a 5xx error
            APIError: For other API errors
            asyncio.TimeoutError: If the request times out
        """
        if not self._session:
            raise RuntimeError("Session not initialized. Use as async context manager.")

        url = f"{self.BASE_URL}/{endpoint}"

        # Extract resource type and ID for better error messages
        resource_parts = endpoint.split('/')
        resource_type = resource_parts[0]
        resource_id = int(resource_parts[1]) if len(resource_parts) > 1 and resource_parts[1].isdigit() else None

        # Retry logic with proper error handling
        for attempt in range(1, self._max_retries + 1):
            try:
                async with self._session.get(url, timeout=self._timeout) as response:
                    # Handle 429 Rate Limit
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        self._logger.warning(f"Rate limited, waiting {retry_after}s")

                        # On last attempt, raise the error
                        if attempt == self._max_retries:
                            raise RateLimitError(retry_after)

                        await asyncio.sleep(retry_after)
                        continue

                    # Handle 404 Not Found
                    if response.status == 404:
                        raise NotFoundError(resource_type, resource_id)

                    # Handle 5xx Server Errors
                    if 500 <= response.status < 600:
                        # On last attempt, raise the error
                        if attempt == self._max_retries:
                            raise ServerError()

                        wait_time = 2 ** attempt  # Exponential backoff
                        self._logger.warning(f"Server error {response.status}, retrying in {wait_time}s ({attempt}/{self._max_retries})")
                        await asyncio.sleep(wait_time)
                        continue

                    # Handle other errors
                    if response.status != 200:
                        error_data = await response.json()
                        error_message = error_data.get('error', 'Unknown error')
                        raise APIError(response.status, error_message)

                    # Success - return parsed JSON
                    return await response.json()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                wait_time = 2 ** attempt  # Exponential backoff

                if attempt < self._max_retries:
                    self._logger.warning(f"Request failed: {e}. Retrying in {wait_time}s ({attempt}/{self._max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    self._logger.error(f"Request failed after {self._max_retries} retries: {e}")
                    raise

    async def get_all_resources(self, resource_type: str) -> List[Dict[str, Any]]:
        """
        Fetch all resources of a specific type with proper error handling.

        Args:
            resource_type: Type of resource to fetch ("character", "location", or "episode")

        Returns:
            List of all resources
        """
        all_resources = []
        next_url = resource_type

        try:
            while next_url:
                data = await self._make_request(next_url)

                # Check for results key
                if "results" not in data:
                    self._logger.warning(f"Unexpected response format - no 'results' key in {resource_type} response")
                    break

                all_resources.extend(data.get("results", []))

                # Check if there are more pages
                info = data.get("info", {})
                next_page = info.get("next")
                if next_page:
                    # Extract only the endpoint part from the next URL
                    next_url = next_page.replace(self.BASE_URL + "/", "")
                else:
                    next_url = None
        except NotFoundError:
            # If resource type is not found, return empty list
            self._logger.warning(f"Resource type {resource_type} not found")
            return []

        return all_resources

    async def get_characters(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get characters with optional filtering.

        Args:
            filters: Optional dictionary of filter parameters
                - name: Filter by character name
                - status: Filter by character status (alive, dead, unknown)
                - species: Filter by character species
                - page: Page number for paginated results

        Returns:
            List of character resources
        """
        endpoint = "character"
        if filters:
            query_params = "&".join(f"{k}={v}" for k, v in filters.items() if v is not None)
            if query_params:
                endpoint = f"{endpoint}/?{query_params}"
        return await self.get_all_resources(endpoint)

    async def get_locations(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get locations with optional filtering.

        Args:
            filters: Optional dictionary of filter parameters
                - name: Filter by location name
                - type: Filter by location type
                - dimension: Filter by location dimension
                - page: Page number for paginated results

        Returns:
            List of location resources
        """
        endpoint = "location"
        if filters:
            query_params = "&".join(f"{k}={v}" for k, v in filters.items() if v is not None)
            if query_params:
                endpoint = f"{endpoint}/?{query_params}"
        return await self.get_all_resources(endpoint)

    async def get_episodes(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get episodes with optional filtering.

        Args:
            filters: Optional dictionary of filter parameters
                - name: Filter by episode name
                - episode: Filter by episode code (e.g. S01E01)
                - page: Page number for paginated results

        Returns:
            List of episode resources
        """
        endpoint = "episode"
        if filters:
            query_params = "&".join(f"{k}={v}" for k, v in filters.items() if v is not None)
            if query_params:
                endpoint = f"{endpoint}/?{query_params}"
        return await self.get_all_resources(endpoint)

    async def get_character(self, character_id: int) -> Dict[str, Any]:
        """
        Get a specific character by ID.

        Args:
            character_id: The ID of the character to fetch

        Returns:
            Character resource

        Raises:
            NotFoundError: If the character is not found
        """
        return await self._make_request(f"character/{character_id}")

    async def get_location(self, location_id: int) -> Dict[str, Any]:
        """
        Get a specific location by ID.

        Args:
            location_id: The ID of the location to fetch

        Returns:
            Location resource

        Raises:
            NotFoundError: If the location is not found
        """
        return await self._make_request(f"location/{location_id}")

    async def get_episode(self, episode_id: int) -> Dict[str, Any]:
        """
        Get a specific episode by ID.

        Args:
            episode_id: The ID of the episode to fetch

        Returns:
            Episode resource

        Raises:
            NotFoundError: If the episode is not found
        """
        return await self._make_request(f"episode/{episode_id}")