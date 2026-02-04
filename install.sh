#!/bin/bash
# UNITARES Governance MCP - Installation Script
# One-command setup for self-hosted deployment

set -e  # Exit on error

echo "=========================================="
echo "UNITARES Governance MCP - Installation"
echo "=========================================="
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed."
    echo "   Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed."
    echo "   Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose found"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cat > .env << EOF
# PostgreSQL Password (change this!)
POSTGRES_PASSWORD=$(openssl rand -hex 16)

# Optional: API Keys for model inference
# HF_TOKEN=your_huggingface_token
# GOOGLE_AI_API_KEY=your_google_ai_key
# NGROK_API_KEY=your_ngrok_key
EOF
    echo "✅ Created .env file with random PostgreSQL password"
    echo "   ⚠️  Please review .env and update POSTGRES_PASSWORD if needed"
    echo ""
else
    echo "✅ .env file already exists"
    echo ""
fi

# Create data and logs directories
echo "📁 Creating data directories..."
mkdir -p data logs
chmod 755 data logs
echo "✅ Directories created"
echo ""

# Build and start services
echo "🐳 Building Docker images..."
docker-compose build

echo ""
echo "🚀 Starting services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check health
echo ""
echo "🏥 Checking service health..."
if curl -f http://localhost:8767/health > /dev/null 2>&1; then
    echo "✅ Server is healthy!"
else
    echo "⚠️  Server may still be starting. Check logs with: docker-compose logs server"
fi

echo ""
echo "=========================================="
echo "✅ Installation Complete!"
echo "=========================================="
echo ""
echo "📊 Dashboard: http://localhost:8767/dashboard"
echo "🔌 MCP Endpoint: http://localhost:8767/mcp/"
echo "💚 Health Check: http://localhost:8767/health"
echo ""
echo "   Note: /sse endpoint still available for legacy clients"
echo ""
echo "📝 Useful commands:"
echo "   docker-compose logs -f server    # View server logs"
echo "   docker-compose restart server     # Restart server"
echo "   docker-compose down               # Stop all services"
echo "   docker-compose up -d              # Start all services"
echo ""
echo "📚 Documentation: docs/guides/DEPLOYMENT.md"
echo ""

