# WeDo Postman Collection

В папке лежат файлы для ручного тестирования API через Postman:

- `WeDo Backend.postman_collection.json` — коллекция запросов.
- `WeDo Local.postman_environment.json` — локальное окружение с переменными.

## Импорт

1. Открыть Postman.
2. Нажать `Import`.
3. Импортировать оба файла из этой папки.
4. В правом верхнем углу Postman выбрать окружение `WeDo Local`.

## Запуск backend

Перед тестированием API должен быть запущен локально.

Через Django:

```powershell
python manage.py runserver
```

Через Docker:

```powershell
docker compose up --build
```

Проверка доступности:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/openapi.json -UseBasicParsing
```

Если сервер работает, вернется статус `200`.

## Переменные окружения

Основные переменные:

- `baseUrl` — адрес backend, по умолчанию `http://127.0.0.1:8000`.
- `accessToken` — JWT access token.
- `refreshToken` — JWT refresh token.
- `userId` — текущий пользователь.
- `otherUserId` — второй пользователь.
- `targetUserId` — пользователь для запросов подписок и профиля.
- `activityId` — активность для связанных запросов.
- `fileId` — загруженный файл.
- `notificationId` — уведомление.
- `qrToken` — QR-токен пользователя.

Важно: переменная называется именно `baseUrl`. Postman учитывает регистр, поэтому `{{baseurl}}` не подставится.

## Базовый порядок проверки

1. Выполнить `Auth / Register Current User`.
   После ответа автоматически сохранятся `accessToken`, `refreshToken`, `userId`.

2. Если пользователь уже создан, выполнить `Auth / Login`.
   Этот запрос также сохраняет токены.

3. Выполнить `Users / Get Me`, чтобы проверить авторизацию.

4. Выполнить `Activities / List Activities`.

5. Если в базе уже есть активности, вручную указать `activityId` в окружении или взять ID из ответа списка активностей.

6. Выполнить связанные запросы:

```text
Activities / Get Activity
Activities / Save Activity
Participation / Join Activity
Notifications / List Notifications
Ratings / List Activity Ratings
```

7. Для проверки второго пользователя выполнить `Auth / Register Other User`.
   Этот запрос сохраняет `otherUserId` и `targetUserId`.

После регистрации второго пользователя активным станет токен второго пользователя. Чтобы снова работать от имени первого пользователя, нужно выполнить `Auth / Login`.

## Файлы

Для проверки загрузки:

1. Открыть `Files / Upload Image`.
2. В `Body -> form-data` выбрать файл в поле `file`.
3. Отправить запрос.
4. После успешного ответа сохранится `fileId`.
5. Выполнить `Files / List Files By IDs` или `Files / Download File`.

## Документация

Публичные запросы без авторизации:

```text
Docs / OpenAPI JSON
Docs / Swagger UI
```

## Негативные сценарии

В коллекции есть отдельные запросы для проверки ошибок:

- `Auth / Invalid Login`
- `Auth / Refresh Missing Token`
- `Activities / Save Activity Duplicate`
- `Ratings / Create Rating Without Attendance`
- `Files / Upload Missing File`
- `Subscriptions / Create Subscription Duplicate`

Ожидаемые коды для таких сценариев: `400`, `401`, `403` или `404`.

## Частые проблемы

Если Postman показывает `Host: {{baseurl}}`, значит переменная написана неправильно. Нужно использовать:

```text
{{baseUrl}}
```

Если защищенные запросы возвращают `401`, нужно заново выполнить `Auth / Login` или `Auth / Register Current User`.

Если запросы к Docker-стенду не проходят, проверить, что контейнеры запущены:

```powershell
docker compose ps
```
