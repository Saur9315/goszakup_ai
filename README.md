# GosZakup AI

AI-агент для анализа государственных закупок Республики Казахстан по данным OWS v3 (goszakup.gov.kz): 27 организаций-заказчиков, 2024–2026 годы. Отвечает на вопросы на русском и казахском языках: поиск и сравнение закупок, аналитика эффективности, аномалии цен и объёмов, справедливость цены лота (Fair Price). Каждый ответ содержит вывод, использованные данные, метод, уверенность с ограничениями и Top-K закупок со ссылками на портал.

LLM не считает цифры: расчёты выполняют детерминированные инструменты на SQL и Python, а каждое число в тексте ответа сверяется с их результатами.

| Метрика (33 сценария, 99 фактов) | gpt-5.4-mini | gpt-4o | qwen3-8 (on-prem) |
|---|---|---|---|
| Точность фактов в ответе (ТЗ ≥ 85%) | 100% | 100% | 99,0% |
| Определение типа вопроса | 100% | 100% | 97,0% |
| Задержка p50 | 3,6 с | 3,0 с | 21 с |

Полные отчёты — в [evals/reports](evals/reports).

## Архитектура

```
OWS v3 (GraphQL + REST)
   │  загрузка и инкрементальная синхронизация (worker / CronJob)
   ▼
PostgreSQL + pgvector
   raw    ответы API как есть (JSONB)
   core   нормализованная модель: план, лоты, объявления, договоры, участники, справочники
   mart   витрины: наблюдения цен, эталонные цены, Fair Price, аномалии, эффективность
   meta   синхронизация, проверки качества, журнал ответов агента
   agent  память диалогов (LangGraph checkpointer)
   ▲  роль только на чтение витрин
API (FastAPI) ── агент (LangGraph) ── LLM: OpenAI / своя модель (vLLM, Qwen)
```

Граф агента: разбор вопроса → поиск сущностей (БИН, лоты, коды ЕНС ТРУ, регион) → уточнение при нехватке данных → инструменты → формулировка ответа → проверка цифр → память диалога.

## Быстрый старт (Docker)

Нужны Docker с Compose, токен OWS v3 и ключ LLM (OpenAI или своя модель с OpenAI-совместимым API).

```bash
cp .env.example .env      # заполнить OWS_TOKEN, пароли, OPENAI_API_KEY
docker compose up -d --build
docker compose logs -f worker
```

При пустой базе worker сам выполняет первичную загрузку: справочники, ИПЦ, данные 27 организаций (около 10 минут), витрины и выборку цен по всему порталу (около часа). Затем синхронизирует данные каждые 6 часов.

Вопрос агенту:

```bash
curl -s localhost:8000/api/ask -H 'Content-Type: application/json' \
  -d '{"question": "Оцени адекватность цены лота №85092773-ОК3 относительно аналогичных контрактов других ведомств"}'

docker compose exec api goszakup ask "Найди закупки с отклонением цены > 30% от средневзвешенной по ЕНСТРУ за 2025 год"
```

Swagger: http://localhost:8000/docs. Чтобы продолжить диалог, передайте `thread_id` из предыдущего ответа.

## Своя LLM (on-prem)

Любой сервер с OpenAI-совместимым API подключается без изменения кода:

```bash
OPENAI_BASE_URL=http://my-llm:8000/v1
OPENAI_MODEL=my-model
OPENAI_API_KEY=any
```

Локальный vLLM поднимается профилем compose (нужен NVIDIA Container Toolkit):

```bash
docker compose --profile local-llm up -d vllm
# в .env: OPENAI_BASE_URL=http://vllm:8000/v1, OPENAI_MODEL=local-llm
```

Резервный провайдер на случай недоступности основного: `LLM_FALLBACK_PROVIDER=qwen`.

## Kubernetes

```bash
docker build -t registry.local/goszakup-backend:0.1.0 backend && docker push registry.local/goszakup-backend:0.1.0
kubectl create namespace goszakup
kubectl -n goszakup create secret generic goszakup-secrets --from-env-file=.env
kubectl apply -k deploy/k8s/base               # или deploy/k8s/overlays/local-llm (vLLM на GPU)
```

Состав: Postgres (StatefulSet), Job миграций, API (Deployment, 2 реплики), CronJob синхронизации каждые 6 часов, выборки цен раз в неделю и ИПЦ раз в месяц, NetworkPolicy для доступа к базе. Секреты разделены: API работает под ролью только на чтение и не получает токен OWS.

## Разработка

```bash
cd backend
uv sync
docker compose up -d postgres
uv run alembic upgrade head
uv run goszakup bootstrap
uv run pytest                     # тесты не требуют токенов
uv run goszakup chat              # диалог в терминале
```

| Команда | Назначение |
|---|---|
| `goszakup bootstrap` | первичная загрузка всего |
| `goszakup sync` | инкрементальная синхронизация, обновление витрин, проверки качества |
| `goszakup ingest refs \| scope \| benchmark \| cpi \| replay` | отдельные этапы загрузки |
| `goszakup marts build \| refresh` | витрины |
| `goszakup dq run` | проверки качества данных |
| `goszakup analyze fair-price \| price-anomalies \| volume-anomalies` | аналитика без LLM |
| `goszakup ask`, `goszakup chat` | вопрос агенту, диалог |
| `goszakup eval run [--provider] [--model]` | прогон эталонного набора |
| `goszakup serve` | HTTP API |

## API

| Метод | Назначение |
|---|---|
| `POST /api/ask` | вопрос агенту (`question`, необязательный `thread_id`) |
| `GET /api/threads/{id}` | история диалога |
| `GET /api/runs/{id}` | сохранённый ответ: параметры, вызовы инструментов, проверка цифр |
| `GET /api/fair-price/{lot}` | Fair Price лота без LLM |
| `GET /api/anomalies/price`, `/api/anomalies/volume` | аномалии цен и объёмов |
| `GET /api/efficiency`, `/api/orgs`, `/api/status` | эффективность, организации, свежесть данных и проверки качества |

## Структура

```
backend/src/goszakup_ai/
  ows/         клиент OWS v3: GraphQL и REST, пагинация, повторы, лимиты, защита токена
  ingestion/   загрузка, инкремент по indexDate, догрузка связей, выборка цен по порталу
  transform/   очистка названий
  db/          модели SQLAlchemy; миграции — backend/migrations
  marts/       витрины (материализованные представления)
  quality/     проверки качества данных
  analytics/   Fair Price, аномалии, ИПЦ, статистика
  agent/       граф LangGraph, инструменты, подсказки, проверка цифр, память
  evals/       эталонный набор и метрики
  api/         FastAPI
deploy/k8s/    манифесты Kubernetes (kustomize)
evals/reports/ отчёты оценки качества
```
