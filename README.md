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

---

## Ручной запуск management-команд

### Импорт событий из KudaGo

```bash
python manage.py import_kudago
```

Команда загружает события из публичного API KudaGo и сохраняет их как активности с `source='kudago'`.

**Основные параметры:**

| Параметр | Описание | По умолчанию |
|---|---|---|
| `--location` | Код города (`msk`, `spb`, `nsk` и т.д.) | Все доступные города |
| `--categories` | Фильтр по категориям через запятую (`concert,theater`) | Все категории |
| `--days-ahead` | Горизонт импорта в днях | `30` |
| `--page-size` | Размер страницы (макс. 100) | `100` |
| `--max-pages` | Максимум страниц для загрузки | `10` |
| `--dry-run` | Режим проверки без сохранения | `False` |

Примеры:

```bash
# Импорт событий Москвы на 7 дней вперёд (проверка)
python manage.py import_kudago --location msk --days-ahead 7 --dry-run

# Импорт концертов и театров Санкт-Петербурга
python manage.py import_kudago --location spb --categories concert,theater

# Быстрый импорт — 1 страница по 15 событий
python manage.py import_kudago --days-ahead 1 --page-size 15 --max-pages 1
```

### Очистка устаревших KudaGo-событий

```bash
python manage.py cleanup_kudago
```

Команда удаляет события из KudaGo (`source='kudago'`, `organizer IS NULL`), у которых `end_at` уже наступил, вместе с привязанными фото.

**Параметры:**

| Параметр | Описание |
|---|---|
| `--dry-run` | Режим проверки: показать количество событий к удалению без фактического удаления |

Пример:

```bash
python manage.py cleanup_kudago --dry-run
```
