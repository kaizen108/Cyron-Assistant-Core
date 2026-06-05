# AI Ticket Assistant - Discord Bot SaaS

A multi-tenant SaaS Discord bot that provides AI-powered support automation in private ticket channels.

## Phase 1: Foundation & Core Connectivity

This phase implements the minimal skeleton proving the relay mechanism works between Discord bot and FastAPI backend.

### Features

- **Discord Bot**:
  - `/setup` command (admin only) - Sets up Tickets category and Support role
  - `/create-ticket` command - Creates private ticket channels
  - Message relay - Forwards messages from ticket channels to backend
  - Receives AI responses and posts them back to Discord

- **Backend API**:
  - `POST /relay` - Receives message payloads from bot
  - `GET /health` - Health check endpoint
  - Phase 1 returns placeholder responses

### Architecture

```
Discord Bot (discord.py) → HTTP POST → FastAPI Backend → Response → Discord Bot → Channel
```

- **Bot**: Lightweight, stateless, only relays messages
- **Backend**: Single source of truth (future: limits, AI, knowledge base)
- **No business logic in bot** - All logic lives in backend

## Prerequisites

- Python 3.11+
- Docker and Docker Compose (for containerized setup)
- Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))
- **Privileged Intents Enabled** (see setup instructions below)

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone <repository-url>
cd AI-ticket-assistant

# Create .env file from example
cp .env.example .env

# Edit .env and add your Discord bot token
# DISCORD_TOKEN=your_bot_token_here
```

### 2. Local Development (Without Docker)

#### Backend

```bash
# Install backend dependencies
pip install -r requirements-backend.txt

# Run backend (use root-level script)
python run_backend.py

# OR run with uvicorn directly
uvicorn backend.main:app --reload

# OR run as module
python -m uvicorn backend.main:app --reload
```

Backend will be available at `http://localhost:8000`

#### Bot

```bash
# Install bot dependencies
pip install -r requirements-bot.txt

# Run bot (use root-level script)
python run_bot.py

# OR run as module from project root
python -m bot.main

# OR run directly (should also work now)
python bot/main.py
```

### 3. Enable Privileged Intents (REQUIRED)

**⚠️ CRITICAL: Enable privileged intents before running the bot!**

The bot requires the **MESSAGE CONTENT INTENT** to read messages in ticket channels.

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your application → **Bot** section
3. Scroll to **Privileged Gateway Intents**
4. Enable **MESSAGE CONTENT INTENT**
5. Click **Save Changes**
6. Wait 1-2 minutes for changes to propagate

Without this, the bot will fail to start with: `PrivilegedIntentsRequired` error.

### 4. Docker Development (Recommended)

```bash
# Build and start all services
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build

# View logs
docker-compose logs -f bot
docker-compose logs -f api

# Stop services
docker-compose down
```

## Testing Phase 1

1. **Enable privileged intents** (see step 3 above)
2. **Invite bot to your Discord server**:
   - Go to Discord Developer Portal
   - OAuth2 → URL Generator
   - Select scopes: `bot`, `applications.commands`
   - Select permissions: `Manage Channels`, `Send Messages`, `Read Message History`, `View Channels`
   - Copy URL and open in browser

2. **Run setup**:
   - In Discord server, type `/setup` (requires admin permissions)
   - Bot will create "Tickets" category and "Support" role

3. **Create a ticket**:
   - Type `/create-ticket`
   - Bot creates private channel `ticket-{your_user_id}`

4. **Test message relay**:
   - Send a message in the ticket channel
   - Bot should relay to backend and respond with: "AI is thinking... (Phase 1 placeholder)"

5. **Test health endpoint**:
   ```bash
   curl http://localhost:8000/health
   ```

## Project Structure

```
AI-ticket-assistant/
├── bot/                    # Discord bot code
│   ├── cogs/              # Bot command modules
│   │   ├── setup.py       # /setup command
│   │   └── tickets.py     # /create-ticket + message relay
│   ├── utils/             # Utility modules
│   │   └── http_client.py # Backend HTTP client
│   ├── config.py          # Bot configuration
│   └── main.py            # Bot entry point
├── backend/               # FastAPI backend
│   ├── api/               # API endpoints
│   │   ├── health.py      # Health check
│   │   └── relay.py       # Message relay endpoint
│   ├── models/            # Pydantic models
│   │   └── relay.py       # Request/response models
│   ├── config.py          # Backend configuration
│   └── main.py            # FastAPI app
├── shared/                # Shared code (future)
├── docker-compose.yml     # Docker services
├── Dockerfile.bot         # Bot container
├── Dockerfile.backend     # Backend container
├── requirements.txt       # Common dependencies
├── requirements-bot.txt   # Bot dependencies
├── requirements-backend.txt # Backend dependencies
└── .env.example           # Environment variables template
```

## Environment Variables

Create a `.env` file in the root directory:

```env
# Discord Bot Configuration
DISCORD_TOKEN=your_discord_bot_token_here

# Backend API Configuration
BACKEND_URL=http://localhost:8000  # Use http://api:8000 in Docker
HOST=0.0.0.0
PORT=8000

# Logging
LOG_LEVEL=INFO
```

## API Endpoints

### `GET /health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "ai-ticket-assistant-backend"
}
```

### `POST /relay`
Relay message from Discord bot to backend.

**Request:**
```json
{
  "guild_id": "123456789012345678",
  "channel_id": "987654321098765432",
  "user_id": "111222333444555666",
  "content": "Hello, I need help!",
  "message_id": "999888777666555444"
}
```

**Response:**
```json
{
  "reply": "AI is thinking... (Phase 1 placeholder)"
}
```

## Development Notes

### Phase 1 Scope
- ✅ Bot joins server and responds to commands
- ✅ Ticket channel creation
- ✅ Message relay (bot → backend → bot)
- ✅ Health check endpoint
- ✅ Docker setup
- ❌ No database (Phase 2)
- ❌ No AI processing (Phase 3)
- ❌ No limits/plans (Phase 2)
- ❌ No dashboard (Phase 4)

### Code Standards
- **Type hints**: All functions have type hints
- **Async-first**: All I/O operations are async
- **Error handling**: Try/except with logging
- **Separation of concerns**: Bot has no business logic
- **Logging**: Structured logging throughout

## Troubleshooting

### Bot doesn't respond to commands
- Check bot has proper permissions in server
- Verify `DISCORD_TOKEN` is correct in `.env`
- Check bot logs for errors
- **Verify MESSAGE CONTENT INTENT is enabled** in Discord Developer Portal

### PrivilegedIntentsRequired Error
**Error:** `Shard ID None is requesting privileged intents that have not been explicitly enabled`

**Solution:**
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your application → **Bot** section
3. Scroll to **Privileged Gateway Intents**
4. Enable **MESSAGE CONTENT INTENT**
5. Click **Save Changes**
6. Wait 1-2 minutes for changes to propagate
7. Restart the bot

See [SETUP_INTENTS.md](SETUP_INTENTS.md) for detailed instructions.

### Backend connection fails
- Verify `BACKEND_URL` is correct
- In Docker: use `http://api:8000`
- Locally: use `http://localhost:8000`
- Check backend is running: `curl http://localhost:8000/health`

### Ticket channel not created
- Run `/setup` first to create Tickets category
- Check bot has `Manage Channels` permission
- Check bot logs for permission errors

## Next Steps (Future Phases)

- **Phase 2**: Database, knowledge base, subscription plans, usage limits
- **Phase 3**: AI engine integration, token tracking
- **Phase 4**: Admin dashboard
- **Phase 5**: Testing, hardening, deployment

## License

[Your License Here]

## Support

For issues or questions, please open an issue in the repository.

