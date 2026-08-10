"""
Dukkan Cloud - Main Application Entry Point
FastAPI application with all routers, middleware, and configuration.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

from app.config import settings
from app.database import init_db, engine, Base
from app.routers import (
    auth,
    organizations,
    vms,
    networks,
    volumes,
    billing,
    admin,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Initialize rate limiter
rate_limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("=" * 60)
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info("=" * 60)
    
    # Initialize database tables
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized successfully")
    
    # Log configuration (without sensitive data)
    logger.info(f"Proxmox URL: {settings.PROXMOX_URL}")
    logger.info(f"Guacamole URL: {settings.GUACAMOLE_URL}")
    logger.info(f"Database: PostgreSQL configured")
    logger.info(f"CORS Origins: {settings.CORS_ORIGINS}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application...")
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="""
## Dukkan Cloud API

Enterprise-grade cloud provisioning platform similar to Hetzner Cloud.

### Features

- **Virtual Machines**: Create and manage LXC containers and QEMU VMs
- **Networking**: VPC, private networks, and firewall rules
- **Block Storage**: Provision and attach volumes to VMs
- **Console Access**: Browser-based RDP/SSH/VNC via Apache Guacamole
- **Billing**: Usage tracking and invoice generation
- **Multi-tenancy**: Organization-based access control
- **RBAC**: Role-based permissions (superadmin, org_admin, member, viewer)
- **API Keys**: Programmatic access for Terraform/Ansible

### Authentication

Use `/api/v1/auth/login` to obtain a JWT token. The token will be set as an HttpOnly cookie
for browser clients, or can be used as a Bearer token for API clients.

For programmatic access (Terraform/Ansible), generate API keys via `/api/v1/auth/api-keys`
and use the `X-API-Key` header.
    """,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Add rate limiter
app.state.limiter = rate_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)


# Custom exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions gracefully."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred",
            "error_code": "INTERNAL_ERROR",
        },
    )


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for load balancers and monitoring.
    """
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
    }


# Include routers
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(organizations.router, prefix=settings.API_PREFIX)
app.include_router(vms.router, prefix=settings.API_PREFIX)
app.include_router(networks.router, prefix=settings.API_PREFIX)
app.include_router(volumes.router, prefix=settings.API_PREFIX)
app.include_router(billing.router, prefix=settings.API_PREFIX)
app.include_router(admin.router, prefix=settings.API_PREFIX)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
