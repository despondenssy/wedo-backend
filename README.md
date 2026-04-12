# WeDo Backend

Backend для мобильного приложения WeDo — поиск и организация событий по интересам.

## Стек

- Python 3.12
- Django + Django REST Framework
- PostgreSQL
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

### 5. Миграции и запуск

```bash
python manage.py migrate
python manage.py runserver
```

Сервер будет доступен по адресу: `http://127.0.0.1:8000`

---

## Запуск через Docker

### 1. Переменные окружения для Docker

```bash
cp .env.example .env.docker
```

Открыть `.env.docker` и заполнить. Обязательно указать `DB_HOST=db`.

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