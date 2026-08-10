# Dukkan Cloud - Production-Ready Cloud Provisioning Platform

## Overview

Dukkan Cloud is an enterprise-grade cloud provisioning platform similar to Hetzner Cloud, built with FastAPI and Next.js. It provides a complete infrastructure management solution with multi-tenancy, RBAC, and integrations with Proxmox VE and Apache Guacamole.

## Architecture

```
/workspace
├── app/                          # FastAPI Backend
│   ├── main.py                   # Application entry point
│   ├── config.py                 # Configuration settings
│   ├── database.py               # Database connection
│   ├── models.py                 # SQLAlchemy ORM models
│   ├── schemas.py                # Pydantic validation schemas
│   ├── dependencies.py           # Auth & RBAC dependencies
│   ├── routers/                  # API route handlers
│   │   ├── auth.py               # Authentication endpoints
│   │   ├── organizations.py      # Organization management
│   │   ├── vms.py                # VM/LXC provisioning
│   │   ├── networks.py           # VPC & firewall rules
│   │   ├── volumes.py            # Block storage
│   │   ├── billing.py            # Usage tracking & invoices
│   │   └── admin.py              # Admin endpoints
│   └── services/                 # Business logic
│       ├── proxmox_service.py    # Proxmox VE API integration
│       └── guacamole_service.py  # Apache Guacamole integration
├── frontend/                     # Next.js Frontend
│   ├── src/
│   │   ├── app/                  # App Router pages
│   │   ├── components/           # React components
│   │   └── lib/                  # Utilities & API client
│   └── package.json
├── requirements.txt              # Python dependencies
└── .env.example                  # Environment variables template
```

## Features

### Core Features
- **Multi-tenancy**: Organization-based resource isolation
- **RBAC**: Role-based access control (superadmin, org_admin, member, viewer)
- **VM Provisioning**: LXC containers and QEMU VMs via Proxmox
- **Cloud-Init**: Automatic SSH key injection and user configuration
- **Browser Console**: RDP/SSH/VNC access via Apache Guacamole
- **API Keys**: Programmatic access for Terraform/Ansible

### Advanced Features
- **VPC Networking**: Private networks with CIDR configuration
- **Firewall Rules**: Allow/deny rules with port ranges
- **Block Storage**: Provision and attach volumes to VMs
- **Usage Tracking**: Hourly resource consumption monitoring
- **Billing Engine**: Monthly invoice generation
- **Audit Logging**: Complete activity trail
- **Rate Limiting**: API protection against abuse
- **WebSocket Console**: Real-time terminal streaming

## Quick Start

### 1. Install Dependencies

```bash
# Backend
cd /workspace
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Initialize Database

```bash
python -c "from app.database import init_db; init_db()"
```

### 4. Run Backend

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Run Frontend

```bash
cd frontend
npm run dev
```

## API Documentation

Once running, access the interactive API docs at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Security Features

1. **JWT Authentication**: HttpOnly secure cookies for frontend, Bearer tokens for API
2. **Password Hashing**: bcrypt with configurable rounds
3. **API Key Hashing**: SHA-256 hashed keys stored in database
4. **CORS Protection**: Configurable allowed origins
5. **Rate Limiting**: Per-minute request limits
6. **Audit Logging**: All actions logged with IP and user agent
7. **Secure URLs**: Guacamole credentials never in URL query strings

## Database Schema

Key models include:
- `Organization`: Multi-tenant container
- `User`: RBAC-enabled users
- `VirtualMachine`: LXC/QEMU instances
- `Network`: VPC configurations
- `FirewallRule`: Network security rules
- `Volume`: Block storage
- `UsageLog`: Billing data
- `Invoice`: Monthly bills
- `APIKey`: Programmatic access
- `ActivityLog`: Audit trail

## Pricing Model

Default pricing (configurable):
- CPU: $0.01 per core/hour
- RAM: $0.005 per GB/hour
- Storage: $0.0001 per GB/hour

## Environment Variables

See `.env.example` for all configuration options including:
- Database connection
- Proxmox VE credentials
- Guacamole credentials
- JWT secret key
- CORS settings
- Rate limiting
- Billing rates

## License

Proprietary - Dukkan Cloud © 2024
