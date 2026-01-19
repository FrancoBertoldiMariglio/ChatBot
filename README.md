# AI Customer Support MVP

Sistema multicanal de atención al cliente con IA, RAG conversacional y handoff humano.

## Inicio Rápido

### Prerrequisitos

- Python 3.11+
- Docker y Docker Compose
- Cuenta de Twilio con WhatsApp habilitado
- API keys de OpenAI o Google AI

### Instalación

1. **Clonar y configurar**:
```bash
cd ChatBot
cp .env.example .env
# Editar .env con tus credenciales
```

2. **Iniciar servicios con Docker**:
```bash
docker-compose up -d
```

3. **O ejecutar localmente**:
```bash
pip install -r requirements.txt
python -m uvicorn src.api.main:app --reload
```

4. **Configurar Qdrant**:
```bash
python scripts/setup_qdrant.py
```

### Verificar instalación

```bash
curl http://localhost:8000/health
```

## Estructura del Proyecto

```
ChatBot/
├── src/
│   ├── api/                    # FastAPI application
│   │   ├── main.py            # App factory
│   │   ├── dependencies.py    # Dependency injection
│   │   └── routes/
│   │       ├── webhooks.py    # Twilio/WhatsApp webhooks
│   │       ├── admin.py       # Tenant management
│   │       └── health.py      # Health checks
│   ├── core/
│   │   ├── config.py          # Settings management
│   │   └── exceptions.py      # Custom exceptions
│   ├── models/
│   │   ├── tenant.py          # Multi-tenant models
│   │   ├── conversation.py    # Conversation state
│   │   └── message.py         # Message models
│   ├── services/
│   │   ├── conversation/
│   │   │   ├── engine.py      # Main orchestrator
│   │   │   ├── memory.py      # Memory management
│   │   │   └── handoff.py     # Human handoff logic
│   │   ├── channels/
│   │   │   ├── base.py        # Channel adapter interface
│   │   │   └── whatsapp.py    # Twilio/WhatsApp adapter
│   │   ├── rag/
│   │   │   ├── embeddings.py  # Embedding service
│   │   │   ├── vectorstore.py # Qdrant integration
│   │   │   └── retriever.py   # RAG retriever
│   │   ├── llm/
│   │   │   └── provider.py    # LiteLLM abstraction
│   │   └── sentiment/
│   │       └── analyzer.py    # Sentiment analysis
│   └── storage/
│       ├── base.py            # Storage interface
│       ├── memory.py          # In-memory (dev)
│       └── firestore.py       # Firestore (prod)
├── tests/
├── config/
│   └── litellm_config.yaml    # LLM routing config
├── scripts/
│   ├── setup_qdrant.py        # Initialize Qdrant
│   └── ingest_knowledge.py    # Ingest documents
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Configuración

### Variables de Entorno

```bash
# Application
APP_ENV=development
APP_DEBUG=true

# Twilio (WhatsApp)
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# LLM Providers
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# AWS Comprehend (sentiment)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

### Configurar Webhook de Twilio

1. En la consola de Twilio, ir a **WhatsApp Sandbox**
2. Configurar webhook URL: `https://tu-dominio.com/webhooks/whatsapp/{tenant_id}`
3. Para desarrollo local, usar ngrok:
```bash
docker-compose --profile dev up ngrok
# URL disponible en http://localhost:4040
```

## API Endpoints

### Health
- `GET /health` - Health check básico
- `GET /health/ready` - Readiness check con dependencias
- `GET /health/live` - Liveness probe

### Webhooks
- `POST /webhooks/whatsapp/{tenant_id}` - Webhook de Twilio WhatsApp

### Admin
- `POST /admin/tenants` - Crear tenant
- `GET /admin/tenants` - Listar tenants
- `GET /admin/tenants/{id}` - Obtener tenant
- `PATCH /admin/tenants/{id}` - Actualizar tenant
- `DELETE /admin/tenants/{id}` - Eliminar tenant
- `POST /admin/tenants/{id}/knowledge` - Ingestar documentos
- `POST /admin/tenants/{id}/knowledge/search` - Buscar en KB
- `GET /admin/tenants/{id}/conversations` - Listar conversaciones

## Uso

### Crear un Tenant

```bash
curl -X POST http://localhost:8000/admin/tenants \
  -H "Content-Type: application/json" \
  -d '{
    "id": "acme",
    "name": "Acme Corp",
    "company_name": "Acme Corporation",
    "welcome_message": "Hola! Soy el asistente de Acme. ¿En qué puedo ayudarte?"
  }'
```

### Cargar Knowledge Base

```bash
# Desde archivo
python scripts/ingest_knowledge.py acme ./docs/

# Via API
curl -X POST http://localhost:8000/admin/tenants/acme/knowledge \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      "Nuestra política de devoluciones permite devoluciones dentro de 30 días...",
      "Los horarios de atención son de 9am a 6pm de lunes a viernes..."
    ]
  }'
```

### Probar Conversación (desarrollo)

En modo desarrollo, se crea automáticamente un tenant "demo". Puedes enviar mensajes desde el WhatsApp Sandbox de Twilio al número configurado.

## Arquitectura

### Flujo de Mensaje

```
WhatsApp → Twilio → Webhook → Engine
                                ↓
                        Sentiment Analysis
                                ↓
                        Handoff Check
                                ↓
                        RAG Retrieval
                                ↓
                        LLM Completion
                                ↓
                        Send Response
```

### Multi-tenancy

El sistema soporta múltiples clientes (tenants) desde el diseño:
- Cada tenant tiene su propia configuración y knowledge base
- Aislamiento de datos mediante `tenant_id` en todas las colecciones
- Webhook URL incluye tenant_id: `/webhooks/whatsapp/{tenant_id}`

### Memory Management

- **Short-term**: Últimos 10 mensajes en sesión
- **Long-term**: Resúmenes automáticos almacenados como embeddings
- **User preferences**: Extraídas y almacenadas para personalización

### Human Handoff Triggers

1. **Sentiment negativo**: Score < -0.5
2. **Solicitud explícita**: Palabras clave como "agente", "humano"
3. **Fallbacks repetidos**: > 2 respuestas sin solución
4. **Loop detectado**: Preguntas similares repetidas

## Tests

```bash
# Ejecutar tests
pytest

# Con coverage
pytest --cov=src

# Tests específicos
pytest tests/test_health.py -v
```

## Deployment

### Docker

```bash
# Build
docker build -t ai-customer-support .

# Run
docker run -p 8000:8000 --env-file .env ai-customer-support
```

### GCP Cloud Run

```bash
# Build y push
gcloud builds submit --tag gcr.io/PROJECT/ai-customer-support

# Deploy
gcloud run deploy ai-customer-support \
  --image gcr.io/PROJECT/ai-customer-support \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "APP_ENV=production"
```

## Costos Estimados

| Componente | Servicio | Costo/mes |
|------------|----------|-----------|
| WhatsApp | Twilio | $30-50 |
| Compute | Cloud Run (free tier) | $0 |
| Vector DB | Qdrant Cloud (1GB free) | $0 |
| Embeddings | OpenAI | $5-10 |
| LLM | Gemini Flash + fallbacks | $5-15 |
| Sentiment | AWS Comprehend | $5-10 |
| **Total MVP** | | **$45-85** |

## Roadmap

- [x] Core conversation engine
- [x] WhatsApp integration (Twilio)
- [x] RAG with Qdrant
- [x] Multi-LLM support (LiteLLM)
- [x] Sentiment analysis
- [x] Human handoff triggers
- [x] Multi-tenancy
- [ ] Chatwoot integration
- [ ] Web chat widget
- [ ] Voice AI channel
- [ ] Admin dashboard (React)

## Licencia

MIT
