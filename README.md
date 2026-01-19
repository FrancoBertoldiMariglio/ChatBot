# Sistema multicanal de atención al cliente con IA: arquitectura completa para MVP

Un sistema de atención al cliente con WhatsApp, RAG conversacional y handoff humano puede construirse dentro del presupuesto de **$300 USD/mes** usando servicios serverless de GCP, APIs con free tiers generosos y herramientas open-source. La arquitectura propuesta soporta multi-tenancy desde el inicio, abstracción de providers LLM, y escala naturalmente desde MVP hasta producción empresarial.

El stack recomendado combina **Twilio WhatsApp** (mejor DX, ~$50/mes), **Qdrant** para vectores (free tier 1GB), **LiteLLM** para abstracción multi-LLM (gratis, self-hosted), **Chatwoot** para centro de control (self-hosted ~$25/mes), y **GCP Cloud Run** como compute serverless. El costo total estimado para MVP es **$150-250/mes** con ~500 conversaciones mensuales.

---

## Integración WhatsApp: Twilio es la opción más rápida para MVP

Desde julio 2025, Meta cambió a pricing por mensaje (no por conversación). Los mensajes de servicio dentro de la ventana de 24 horas son **gratuitos**, lo que reduce significativamente costos para atención al cliente reactiva.

| Provider | Markup por mensaje | Fee mensual | SDK Python/.NET | Setup |
|----------|-------------------|-------------|-----------------|-------|
| **Twilio** | $0.005/msg | $0 | ✅ Oficial | Bajo |
| Meta Cloud API | $0 | $0 | Community | Alto |
| 360dialog | $0 | $49-99 | REST | Medio |
| Vonage | ~$0.00015/msg | Variable | Oficial | Medio |

**Twilio** ofrece SDKs oficiales para Python y .NET, webhooks robustos, y setup en horas en lugar de días. Para 500 conversaciones/mes (~2,000 mensajes), el costo estimado es **$20-50/mes** incluyendo fees de Meta. La API unificada de Twilio también facilita agregar SMS y Voice en el roadmap.

La alternativa más económica es **Meta Cloud API directo** (sin markup), pero requiere más desarrollo: configuración manual de webhooks, Business Verification, y SDKs community. Para equipos que priorizan velocidad de entrega sobre optimización de costos, Twilio es la mejor opción inicial.

**Implementación clave**: Usar webhooks de Twilio apuntando a Cloud Run, con validación de firma y manejo de sesiones basado en el `WaId` (WhatsApp ID) del usuario. La ventana de 24 horas debe trackearse en la base de datos para decidir entre mensajes de sesión (gratis) y templates (pagados).

---

## VoIP con IA conversacional: arquitectura preparada para el roadmap

Aunque VoIP no está en el MVP, la arquitectura debe contemplarlo desde el diseño. Existen dos caminos principales:

**Opción 1 - Plataformas especializadas (recomendado para MVP de voz)**:
- **Retell AI**: $0.07-0.14/min all-in, incluye STT/TTS/orquestación, 60 minutos gratis
- **Vapi.ai**: $0.05/min plataforma + servicios (~$0.15/min total), más flexible
- **Bland.ai**: $0.09/min, modelo propietario, enterprise-ready

**Opción 2 - Stack propio (mejor control, más esfuerzo)**:
```
Twilio Voice ($0.014/min) → Media Streams (WebSocket) → Tu servidor
    → Deepgram STT ($0.008/min) → LLM → ElevenLabs TTS ($0.08/min)
Total: ~$0.13/min
```

**Para el diseño actual**, la clave es usar abstracciones que soporten tanto texto como voz. LangChain/LiteLLM manejan el LLM de forma agnóstica al canal. El componente que cambia es el input/output processor:

```python
class ChannelAdapter(ABC):
    @abstractmethod
    async def receive(self) -> ConversationMessage: pass
    
    @abstractmethod  
    async def send(self, response: str) -> None: pass

class WhatsAppAdapter(ChannelAdapter): ...
class VoiceAdapter(ChannelAdapter):  # Futuro: WebSocket + STT/TTS
    ...
```

El costo de voice AI es **10-20x mayor que texto** (~$0.10-0.20/min vs ~$0.01/mensaje), por lo que es correcto priorizarlo para fase posterior cuando el modelo de negocio lo justifique.

---

## Arquitectura RAG con memoria conversacional multi-tenant

El sistema RAG debe manejar dos tipos de conocimiento: la **base de conocimiento del tenant** (FAQs, productos, políticas) y la **memoria conversacional** del usuario (historial, preferencias).

### Vector database: Qdrant es el mejor balance costo-flexibilidad

| Database | Free tier | Self-hosted | Multi-tenant | Recomendación |
|----------|-----------|-------------|--------------|---------------|
| **Qdrant** | 1GB cloud | ✅ Gratis | Excelente | ⭐ MVP + Scale |
| Pinecone | 2GB | ❌ | Bueno | Alternativa managed |
| pgvector | Con PostgreSQL | ✅ | Limitado | Simple, <5M vectors |
| Chroma | N/A | ✅ | Limitado | Solo prototipos |

**Qdrant** ofrece 1GB gratis en cloud (suficiente para ~1M vectores de 768d), self-hosting sin costo, y **pre-filtering** eficiente para multi-tenancy. El patrón de aislamiento recomendado es metadata filtering con `tenant_id` en cada vector:

```python
qdrant.search(
    collection_name="knowledge_base",
    query_vector=embedding,
    query_filter=Filter(must=[
        FieldCondition(key="tenant_id", match=MatchValue(value="acme-corp"))
    ])
)
```

### Embeddings: text-embedding-3-small de OpenAI

A **$0.02/millón de tokens**, text-embedding-3-small ofrece el mejor ROI. Para un MVP con 10,000 documentos de 500 tokens = 5M tokens = **$0.10** de embedding inicial. Re-embedding mensual para actualizaciones: ~$5-20/mes.

Alternativa open-source para escala: `all-MiniLM-L6-v2` (384 dims) self-hosted elimina costos de API pero requiere GPU (~$50/mes) o inferencia CPU más lenta.

### Estrategia de chunking para atención al cliente

- **FAQs**: 150-250 tokens, sin overlap, mantener Q&A juntos
- **Artículos/documentación**: 512 tokens, 50-100 overlap
- **Historial de chat**: 256 tokens, chunking semántico por turno

**Hybrid search** es crítico para customer service: búsqueda vectorial falla con términos exactos (códigos de error, nombres de producto). Implementar BM25 + vector search con Reciprocal Rank Fusion:

```python
# LangChain EnsembleRetriever
from langchain.retrievers import EnsembleRetriever
ensemble = EnsembleRetriever(
    retrievers=[bm25_retriever, vector_retriever],
    weights=[0.6, 0.4]  # Priorizar keyword para CS
)
```

### Memoria conversacional: short-term + long-term

**Short-term (sesión)**: Últimos 10 mensajes en Redis/Firestore con TTL de 30-60 minutos. Límite de tokens para evitar context overflow.

**Long-term (usuario)**: 
1. Resúmenes periódicos: cada 15-20 turnos, LLM genera summary comprimido
2. Preferencias extraídas: entidades, decisiones, metadata estructurada en PostgreSQL
3. Embeddings de summaries en Qdrant con filtro `user_id`

```python
# Retrieval pipeline
context = (
    get_session_messages(session_id)[:10] +  # Short-term
    retrieve_user_summaries(user_id, query, k=3) +  # Long-term  
    retrieve_knowledge_base(tenant_id, query, k=5)  # KB
)
```

---

## Abstracción multi-LLM: LiteLLM es la solución

**LiteLLM** (open-source) unifica 100+ LLM APIs en formato OpenAI, incluyendo fallbacks automáticos, cost tracking, y load balancing. Se despliega como proxy server o se usa como SDK.

```yaml
# litellm_config.yaml
model_list:
  - model_name: customer-service
    litellm_params:
      model: vertex_ai/gemini-1.5-flash  # Primary: más barato
  - model_name: customer-service
    litellm_params:
      model: openai/gpt-4o-mini  # Secondary
  - model_name: customer-service  
    litellm_params:
      model: anthropic/claude-3-haiku  # Tertiary

router_settings:
  routing_strategy: "cost-based-routing"
  fallbacks:
    - customer-service: [customer-service]
  num_retries: 2
```

### Comparativa de costos LLM para customer service

| Modelo | Input/1K tokens | Output/1K tokens | Calidad | Latencia |
|--------|----------------|------------------|---------|----------|
| **Gemini 1.5 Flash** | $0.000075 | $0.0003 | Buena | Rápida |
| **GPT-4o-mini** | $0.00015 | $0.0006 | Muy buena | Rápida |
| Claude 3 Haiku | $0.00025 | $0.00125 | Muy buena | Rápida |
| Claude 3.5 Sonnet | $0.003 | $0.015 | Excelente | Media |

Para 10,000 interacciones/mes (500 tokens in, 300 out cada una):
- **Gemini Flash**: $1.28/mes
- **GPT-4o-mini**: $2.55/mes
- **Claude Haiku**: $5.00/mes

**Recomendación**: Gemini 1.5 Flash como primary (más económico), GPT-4o-mini como fallback (balance calidad-costo), Claude Haiku como tertiary. Costo LLM estimado: **$3-10/mes** para MVP.

---

## Centro de control y human handoff: Chatwoot self-hosted

**Chatwoot** (MIT license, 18K+ GitHub stars) es la mejor opción para el presupuesto. Incluye:
- Inbox unificado (WhatsApp, web, email, Facebook)
- Dashboard de agentes con asignación y routing
- Webhooks para integración con bot
- Reportes y métricas básicas
- Apps móviles Android/iOS

**Costo self-hosted**: VPS 2 vCPU, 4GB RAM = **$25-40/mes** (DigitalOcean, AWS Lightsail)

### Arquitectura de handoff

```
[Cliente] → [Webhook API] → [Bot Engine]
                                 ↓
                        [Evaluador de triggers]
                         ├─ Sentiment < -0.5
                         ├─ Confidence < 60%
                         ├─ Keywords: "agente", "humano"
                         └─ Loop detection (>2 fallbacks)
                                 ↓ (trigger)
                        [Context Package]
                         ├─ Transcripción completa
                         ├─ Metadata del usuario
                         ├─ Sentiment score
                         └─ Intent detectado
                                 ↓
                    [Chatwoot Queue Manager]
                                 ↓
                        [Agent Dashboard]
```

**Integración Chatwoot-Bot**: Usar webhooks bidireccionales. El bot envía mensajes vía API de Chatwoot y recibe eventos de agente vía webhook. Cuando un agente toma control, el bot pausa respuestas automáticas.

### Sentiment analysis: AWS Comprehend

Para ~10,000 mensajes/mes de ~500 caracteres:
- **AWS Comprehend**: ~$5/mes (50 unidades = 5,000 chars, $0.0001/unidad)
- **Azure Text Analytics**: ~$10/mes
- **Open-source** (DistilBERT self-hosted): $0 pero requiere GPU inference

**Recomendación**: AWS Comprehend por mejor ROI. El score se calcula en cada mensaje del cliente y se almacena para trending y triggers de escalación.

---

## Infraestructura GCP: serverless para minimizar costos

### Stack recomendado para MVP

| Componente | Servicio GCP | Costo mensual |
|------------|--------------|---------------|
| API/Webhooks | Cloud Run | **$0** (free tier) |
| Session data | Firestore | **$0** (free tier) |
| Queue async | Pub/Sub | **$0** (free tier) |
| Tenant/user data | Cloud SQL (opcional) | $9-50 |
| Object storage | Cloud Storage | ~$1 |
| Monitoring | Cloud Monitoring | **$0** |

**Cloud Run free tier** cubre 180K vCPU-seconds + 2M requests/mes, suficiente para ~5,000-10,000 mensajes/mes. Cold starts de 1-5s se mitigan con containers pequeños (<200MB) y warmup opcional ($12/mes por instancia mínima).

**Firestore** es ideal para MVP: free tier de 50K reads + 20K writes diarios cubre el volumen inicial. Multi-tenancy via subcollections: `/tenants/{tenantId}/sessions/{sessionId}`.

### Patrón event-driven para escalabilidad

```
[Twilio Webhook] → [Cloud Run: Webhook Handler]
                            ↓
                   [Pub/Sub: message-queue]
                            ↓
               [Cloud Run: AI Processor]
                     ↓           ↓
            [Qdrant]    [LiteLLM Proxy]
                     ↓           ↓
               [Response Composer]
                            ↓
                   [Twilio Send API]
```

Pub/Sub desacopla ingestion de processing, permite retries automáticos, y protege contra spikes de tráfico.

---

## Arquitectura de componentes completa

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              CANALES DE ENTRADA                             │
├──────────────┬──────────────┬──────────────┬──────────────┬────────────────┤
│   WhatsApp   │   Web Chat   │    Email     │   Facebook   │  Voice (TBD)   │
│   (Twilio)   │  (Chatwoot)  │  (Chatwoot)  │  (Chatwoot)  │  (Retell AI)   │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴────────────────┘
       │              │              │              │
       └──────────────┴──────────────┴──────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         GATEWAY LAYER (Cloud Run)                           │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐           │
│  │ Webhook Handler │   │ Session Manager │   │  Rate Limiter   │           │
│  │ (validate, auth)│   │ (tenant routing)│   │   (per tenant)  │           │
│  └────────┬────────┘   └────────┬────────┘   └─────────────────┘           │
└───────────┼─────────────────────┼──────────────────────────────────────────┘
            │                     │
            ▼                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         MESSAGE QUEUE (Pub/Sub)                             │
└────────────────────────────────┬───────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                      AI PROCESSING LAYER (Cloud Run)                        │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                      CONVERSATION ENGINE                           │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │     │
│  │  │  Sentiment  │  │   Intent    │  │   Handoff   │                │     │
│  │  │  Analyzer   │  │  Classifier │  │   Evaluator │                │     │
│  │  │ (Comprehend)│  │  (LLM/NLU)  │  │  (triggers) │                │     │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                │     │
│  │         │                │                │                        │     │
│  │         └────────────────┴────────────────┘                        │     │
│  │                          │                                         │     │
│  │                          ▼                                         │     │
│  │  ┌─────────────────────────────────────────────────────────────┐  │     │
│  │  │                    RAG PIPELINE                              │  │     │
│  │  │  [Query] → [Hybrid Search] → [Rerank] → [Context Assembly]  │  │     │
│  │  │              ↓                                               │  │     │
│  │  │      ┌──────────────┐                                        │  │     │
│  │  │      │   Qdrant     │  ← Tenant KB + User Memory             │  │     │
│  │  │      │ (Vector DB)  │                                        │  │     │
│  │  │      └──────────────┘                                        │  │     │
│  │  └─────────────────────────────────────────────────────────────┘  │     │
│  │                          │                                         │     │
│  │                          ▼                                         │     │
│  │  ┌─────────────────────────────────────────────────────────────┐  │     │
│  │  │                   LiteLLM PROXY                              │  │     │
│  │  │  ┌──────────┐   ┌──────────┐   ┌──────────┐                 │  │     │
│  │  │  │  Gemini  │ → │ GPT-4o   │ → │  Claude  │  (fallback)     │  │     │
│  │  │  │  Flash   │   │  mini    │   │  Haiku   │                 │  │     │
│  │  │  └──────────┘   └──────────┘   └──────────┘                 │  │     │
│  │  │  • Cost tracking • Budget limits • Load balancing           │  │     │
│  │  └─────────────────────────────────────────────────────────────┘  │     │
│  └───────────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────────┘
            │                                               │
            ▼                                               ▼
┌──────────────────────────────┐            ┌──────────────────────────────┐
│      RESPONSE HANDLER        │            │       HUMAN HANDOFF          │
│  • Format for channel        │            │    (via Chatwoot API)        │
│  • Media handling            │            │  • Transfer conversation     │
│  • Send via Twilio/Chatwoot  │            │  • Include full context      │
└──────────────────────────────┘            │  • Alert agent               │
                                            └──────────────────────────────┘
                                                         │
                                                         ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                    CHATWOOT (Self-hosted) - CONTROL CENTER                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Agent Inbox  │  │    Queue     │  │   Reports    │  │    CSAT      │   │
│  │  (unified)   │  │  Management  │  │   & Metrics  │  │   Surveys    │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
└────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Firestore   │  │  Cloud SQL   │  │    Qdrant    │  │    Redis     │   │
│  │  (sessions)  │  │  (tenants)   │  │  (vectors)   │  │   (cache)    │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Desglose de costos detallado

### MVP: ~500 conversaciones/mes (~5,000 mensajes)

| Componente | Servicio | Costo mensual |
|------------|----------|---------------|
| **WhatsApp API** | Twilio (markup + Meta fees) | $30-50 |
| **Compute** | Cloud Run (free tier) | $0 |
| **Session storage** | Firestore (free tier) | $0 |
| **Vector DB** | Qdrant Cloud (1GB free) | $0 |
| **Embeddings** | OpenAI text-embedding-3-small | $5-10 |
| **LLM inference** | Gemini Flash + fallbacks | $5-15 |
| **LLM orchestration** | LiteLLM (self-hosted) | $0 |
| **Sentiment** | AWS Comprehend | $5-10 |
| **Control center** | Chatwoot VPS (4GB RAM) | $25-35 |
| **Object storage** | Cloud Storage | $1-2 |
| **Domain + SSL** | Cloudflare | $0 |
| **TOTAL MVP** | | **$71-122** |
| **Buffer (contingencias)** | +30% | **$92-159** |

**El MVP está significativamente bajo el presupuesto de $300/mes**, dejando margen para:
- Agregar Cloud SQL PostgreSQL (+$9-50) cuando se necesite
- Minimum instances en Cloud Run para reducir cold starts (+$12)
- Redis para caching (+$30)

### Proyección de costos al escalar

| Escala | Mensajes/mes | Costo estimado |
|--------|--------------|----------------|
| **MVP** | 5,000 | $100-160 |
| **Crecimiento** | 10,000 | $180-280 |
| **Producción** | 50,000 | $400-600 |
| **Enterprise** | 100,000+ | $800-1,500 |

Los componentes que más escalan en costo son:
1. **WhatsApp fees** (Twilio + Meta): lineal con volumen
2. **LLM inference**: puede optimizarse con caching y modelos más baratos
3. **Compute**: Cloud Run escala automáticamente pero pierde free tier
4. **Vector DB**: Qdrant paid tier ~$85/mes después de 1GB

---

## Roadmap MVP → Producción

### Fase 1: MVP (Semanas 1-4)
- Deploy Chatwoot en VPS
- Configurar WhatsApp via Twilio
- Implementar bot básico con LangChain + Qdrant
- Handoff manual a agentes
- **Entregable**: Sistema funcional para 1-2 tenants piloto

### Fase 2: Optimización (Semanas 5-8)
- Agregar LiteLLM proxy con fallbacks
- Implementar sentiment analysis + triggers automáticos
- Dashboard de métricas customizado (React)
- Memory management (short-term + summarization)
- **Entregable**: Sistema robusto con métricas

### Fase 3: Multi-tenancy (Semanas 9-12)
- Onboarding de tenants con upload de knowledge base
- Aislamiento de datos por tenant en Qdrant/Firestore
- Billing tracking por tenant via LiteLLM
- Backups automatizados
- **Entregable**: Plataforma SaaS lista para múltiples clientes

### Fase 4: Voice AI (Futuro)
- Integrar Retell AI o Twilio Voice + Deepgram
- Adapter pattern para canal de voz
- Shared conversation engine con WhatsApp
- **Entregable**: Soporte multicanal completo

---

## Stack tecnológico recomendado

| Capa | Tecnología | Justificación |
|------|------------|---------------|
| **Backend API** | Python FastAPI o .NET Core | Experiencia del dev, async nativo |
| **AI/RAG** | LangChain + LangGraph | Madurez, flexibilidad, memoria integrada |
| **Vector DB** | Qdrant | Free tier generoso, excelente multi-tenancy |
| **LLM Gateway** | LiteLLM (self-hosted) | Gratis, fallbacks, cost tracking |
| **Primary LLM** | Gemini 1.5 Flash | Más económico, buena calidad |
| **Embeddings** | OpenAI text-embedding-3-small | Mejor ROI, 1536 dims |
| **Message Queue** | GCP Pub/Sub | Free tier, integración nativa |
| **Session Store** | Firestore | Free tier, real-time, serverless |
| **Compute** | Cloud Run | Serverless, scale-to-zero, free tier |
| **WhatsApp** | Twilio | Mejor DX, SDKs oficiales |
| **Control Center** | Chatwoot (self-hosted) | Open-source, completo, económico |
| **Sentiment** | AWS Comprehend | Económico, preciso, fácil integración |
| **Frontend Dashboard** | React + Zustand + Socket.io | Stack moderno, real-time ready |

Esta arquitectura mantiene **vendor lock-in mínimo**: los componentes core (LangChain, Qdrant, LiteLLM) son open-source o tienen alternativas directas. El único componente con lock-in moderado es Twilio, pero la lógica de negocio está abstraída del provider de mensajería.

El sistema está diseñado para que cada tenant pueda cargar su información (documentos, FAQs, productos), que se procesa automáticamente en embeddings y se almacena en Qdrant con su `tenant_id`. El bot "aprende" de esta información via RAG, sin necesidad de fine-tuning costoso.
