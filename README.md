# WeDo Backend

Backend для мобильного приложения WeDo — поиск и организация событий по интересам.

## Стек

- Python 3.12
- Django + Django REST Framework
- PostgreSQL
- Redis
- Celery + Celery beat
- Firebase Cloud Messaging
- JWT-аутентификация
- Docker

## Локальный запуск

### 1. Клонировать репозиторий

```bash
git clone https://github.com/despondenssy/wedo-backend.git
cd wedo-backend
```

### 2. Виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Переменные окружения

```bash
cp .env.example .env
```

Открыть `.env` и заполнить своими значениями по аналогии с `.env.example`.

Сгенерировать `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

### 4. База данных

Создать пользователя и базу в PostgreSQL, затем прописать credentials в `.env`.

### 5. Redis

Простейший способ — поднять контейнером:

```bash
docker run -d -p 6379:6379 --name wedo-redis redis:7-alpine
```

### 6. Миграции и запуск

```bash
python manage.py migrate
python manage.py runserver
```

Сервер будет доступен по адресу: `http://127.0.0.1:8000`

### 7. Celery worker (в отдельном терминале)

```bash
source venv/bin/activate
celery -A config worker -l info
```

### 8. Celery beat (опционально, в отдельном терминале)

Нужен, только если хочется, чтобы периодические задачи (напоминания, запросы оценки, перевод в `missed`) запускались автоматически:

```bash
source venv/bin/activate
celery -A config beat -l info
```

## Swagger / OpenAPI

Интерактивная документация (Swagger UI): https://despondenssy.github.io/wedo-backend/

Swagger UI также доступен локально по адресу: `http://127.0.0.1:8000/api/docs/swagger/`

Альтернативная документация с более наглядным просмотром схем RapiDoc: https://despondenssy.github.io/wedo-backend/rapidoc.html

RapiDoc также доступен локально по адресу: `http://127.0.0.1:8000/api/docs/rapidoc/`

OpenAPI-спецификация лежит в файле `openapi.json`.

Для GitHub Pages добавлена статическая документация в папке `docs/`.

---

## Запуск через Docker

В `docker-compose.yml` уже описаны все нужные сервисы: `db`, `redis`, `web`, `celery_worker`, `celery_beat`.

### 1. Переменные окружения для Docker

```bash
cp .env.example .env.docker
```

Открыть `.env.docker` и заполнить. Обязательно указать `DB_HOST=db` и `CELERY_BROKER_URL=redis://redis:6379/0`.

### 2. Собрать и запустить

```bash
docker compose build
docker compose up
```

Миграции применятся автоматически. Сервер будет доступен по адресу: `http://127.0.0.1:8000`

### 3. Остановить

```bash
docker compose down
```

---

## Rate-лимиты

| Endpoint | Лимит |
|---|---|
| `POST /auth/login` | 10/min |
| `POST /auth/register` | 5/hour |
| `POST /auth/refresh` | 20/min |
| `POST /me/qr-token` | 30/min |
| `POST /qr-tokens/resolve` | 30/min |
| `POST /activities/:id/attendance/scan` | 60/min |
| прочие anon-endpoint'ы | 60/min |
| прочие auth-endpoint'ы | 600/min |

При превышении возвращается `429 Too Many Requests` с заголовком `Retry-After`.

---

## Тесты

```bash
pytest                    # все тесты
pytest activities/ -v     # один app, с подробным выводом
```

Тестовая БД создаётся автоматически — пользователю Postgres нужно дать право `CREATEDB`:

```bash
sudo -u postgres psql -c "ALTER USER wedo_user CREATEDB;"
```

В тестах Celery работает в eager-режиме (синхронно в процессе теста), Redis и worker не нужны.
