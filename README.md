# Rick and Morty API Integration

This project provides a robust, asynchronous client for the Rick and Morty API and a FastAPI service that wraps around it.

## Features

- **Asynchronous Operations**: All API operations are non-blocking, providing high throughput and responsiveness
- **Resilient Client**: Built-in retry logic, error handling, and timeouts
- **Rate Limiting**: Protection against API rate limits and abuse
- **Redis Caching**: Distributed caching with Redis to improve performance and reduce API calls
- **Comprehensive Error Handling**: Detailed error information and proper HTTP status codes

## Project Structure

```
rick_and_morty_app/
├── client.py              # Client module for the Rick and Morty API
├── api_service.py         # FastAPI service exposing the API
├── rate_limiter.py        # Query rate controller
├── requirements.txt       # Project dependencies
├── Dockerfile             # Docker configuration
└── docker-compose.yml     # Docker Compose configuration with Redis
```

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package installer)
- Redis (optional for local installation, provided via Docker for Docker installation)

### Option 1: Local Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Yanlebed/rick_and_morty_app.git
   cd rick_and_morty_app
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install and start Redis (if not already running):
   ```bash
   redis-server
   ```

5. Run the API service:
   ```bash
   uvicorn api_service:app --host 0.0.0.0 --port 8000 --reload
   ```

### Option 2: Docker Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Yanlebed/rick_and_morty_app.git
   cd rick_and_morty_app
   ```

2. Build and start the containers:
   ```bash
   docker-compose up -d
   ```

## Usage

### API Endpoints

Once the server is running, you can access the following endpoints:

- **GET /health**: Health check endpoint
- **GET /characters**: Get all characters with optional filtering
  - Query parameters: name, status, species, page
- **GET /characters/{id}**: Get a specific character by ID
- **GET /locations**: Get all locations with optional filtering
  - Query parameters: name, type, dimension, page
- **GET /locations/{id}**: Get a specific location by ID
- **GET /episodes**: Get all episodes with optional filtering
  - Query parameters: name, episode, page
- **GET /episodes/{id}**: Get a specific episode by ID
- **GET /download/all**: Download all characters, locations, and episodes to files
- **GET /cache/clear**: Clear cache entries

### Example Requests

#### Get all characters
```bash
curl -X GET "http://localhost:8000/characters"
```

#### Get character with ID 1
```bash
curl -X GET "http://localhost:8000/characters/1"
```

#### Filter characters
```bash
curl -X GET "http://localhost:8000/characters?name=rick&status=alive"
```

#### Download all data
```bash
curl -X GET "http://localhost:8000/download/all"
```

### API Documentation

When the service is running, you can access the automatic API documentation:
http://localhost:8000/docs

## Security Measures

The API service includes several security measures:

1. **Rate Limiting**: Prevents abuse by limiting requests per IP
2. **Input Validation**: Validates all input parameters to prevent injection
3. **Security Headers**: Adds security headers to all responses
4. **Error Handling**: Provides appropriate error responses without leaking implementation details

## Error Handling

The API handles the following error scenarios:

- **404 Not Found**: When a requested resource doesn't exist
- **400 Bad Request**: When invalid parameters are provided
- **429 Too Many Requests**: When rate limits are exceeded
- **500 Internal Server Error**: For unexpected server errors
- **503 Service Unavailable**: When the upstream Rick and Morty API is unavailable

## Performance Considerations

- **Caching**: Common queries are cached to improve performance
- **Asynchronous I/O**: All operations are non-blocking
- **Connection Pooling**: Reuses HTTP connections to reduce overhead
- **Retry Logic**: Automatically retries failed requests with exponential backoff
