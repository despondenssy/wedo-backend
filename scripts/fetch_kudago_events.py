#Это рандомный скрипт, который парсит события с кудаго, после внедрения кудаго удалить 

import argparse
import http.client
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE_URL = "https://kudago.com/public-api/v1.4/events/"
DEFAULT_FIELDS = ",".join(
    [
        "id",
        "title",
        "description",
        "dates",
        "place",
        "location",
        "categories",
        "price",
        "is_free",
        "images",
        "site_url",
    ]
)


def build_url(
    location: str,
    page_size: int,
    days_ahead: int,
    is_free: bool | None,
) -> str:
    now = datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "lang": "ru",
        "page": 1,
        "page_size": page_size,
        "fields": DEFAULT_FIELDS,
        "expand": "dates,place,location,images",
        "text_format": "plain",
        "location": location,
        "actual_since": int(now.timestamp()),
        "actual_until": int((now + timedelta(days=days_ahead)).timestamp()),
        "order_by": "dates",
    }

    if is_free is not None:
        params["is_free"] = str(is_free).lower()

    return f"{API_BASE_URL}?{urlencode(params)}"


def fetch_events(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "wedo-kudago-test-script/1.0",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )

    with urlopen(request, timeout=30) as response:
        try:
            body = response.read()
        except http.client.IncompleteRead as exc:
            body = exc.partial
    return json.loads(body.decode("utf-8"))


def first_date_range(event: dict[str, Any]) -> str:
    dates = event.get("dates") or []
    if not dates:
        return "dates: n/a"

    first = dates[0]
    start = first.get("start")
    end = first.get("end")

    def format_ts(value: Any) -> str:
        if not value:
            return "n/a"
        try:
            timestamp = float(value)
            if timestamp > 10**11:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return str(value)

    return f"{format_ts(start)} -> {format_ts(end)}"


def print_events(payload: dict[str, Any]) -> None:
    results = payload.get("results") or []
    count = payload.get("count", len(results))

    print(f"Найдено событий: {count}")
    print(f"Выведено в текущем ответе: {len(results)}")
    print()

    for index, event in enumerate(results, start=1):
        place = event.get("place") or {}
        location = event.get("location") or {}
        categories = ", ".join(event.get("categories") or []) or "n/a"
        print(f"{index}. [{event.get('id')}] {event.get('title')}")
        print(f"   Даты: {first_date_range(event)}")
        print(f"   Место: {place.get('title') or 'n/a'}")
        print(f"   Город: {location.get('name') or location.get('slug') or 'n/a'}")
        print(f"   Категории: {categories}")
        print(f"   Бесплатно: {event.get('is_free')}")
        print(f"   Цена: {event.get('price') or 'n/a'}")
        print(f"   URL: {event.get('site_url') or 'n/a'}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Получить события из KudaGo API и вывести их в консоль."
    )
    parser.add_argument(
        "--location",
        default="msk",
        help="Город KudaGo, например msk, spb, ekb. По умолчанию: msk",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=10,
        help="Сколько событий запросить. Максимум 100. По умолчанию: 10",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=14,
        help="На сколько дней вперёд искать события. По умолчанию: 14",
    )
    parser.add_argument(
        "--free-only",
        action="store_true",
        help="Запрашивать только бесплатные события.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    is_free = True if args.free_only else None
    url = build_url(
        location=args.location,
        page_size=min(args.page_size, 100),
        days_ahead=args.days_ahead,
        is_free=is_free,
    )

    print("Запрашиваем URL:")
    print(url)
    print()

    payload = fetch_events(url)
    print_events(payload)


if __name__ == "__main__":
    main()
