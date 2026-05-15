"""
Management command для импорта событий из KudaGo API.

Использование:
    python manage.py import_kudago --location msk --days-ahead 30 --dry-run
    python manage.py import_kudago --location spb --categories concert,theater
    python manage.py import_kudago --days-ahead 1 --page-size 15 --max-pages 1

По умолчанию импортирует события на 30 дней вперёд для всех городов.
"""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand

from activities.models import Activity
from files.models import File

from timezonefinder import TimezoneFinder

logger = logging.getLogger(__name__)

API_BASE_URL = "https://kudago.com/public-api/v1.4/events/"
LOCATION_API_URL = "https://kudago.com/public-api/v1.4/locations/{slug}/"

# Определитель часового пояса по координатам (инициализируем один раз)
_tz_finder: Any = None

def _get_timezone(lat: float, lon: float) -> str | None:
    """Определяет часовой пояс по координатам через timezonefinder.

    Возвращает None, если координаты (0, 0) или таймзона не найдена.
    """
    if lat == 0.0 and lon == 0.0:
        return None
    global _tz_finder
    if _tz_finder is None:
        _tz_finder = TimezoneFinder()
    return _tz_finder.timezone_at(lat=lat, lng=lon)

DEFAULT_FIELDS = ",".join(
    [
        "id",
        "title",
        "short_title",
        "slug",
        "description",
        "body_text",
        "tagline",
        "dates",
        "place",
        "location",
        "categories",
        "tags",
        "price",
        "is_free",
        "age_restriction",
        "images",
        "site_url",
    ]
)

# Маппинг категорий KudaGo → наши category_id/subcategory_id
KUDAGO_CATEGORY_MAPPING = {
    "theater": ("creative", "theater"),
    "theatre": ("creative", "theater"),
    "concert": ("music", "concerts"),
    "exhibition": ("creative", "exhibition"),
    "cinema": ("cinema", "movies"),
    "movie": ("cinema", "movies"),
    "sport": ("sport", "fitness"),
    "education": ("education", "science"),
    "festival": ("music", "concerts"),
    "party": ("music", "concerts"),
    "quest": ("games", "quiz"),
    "children": ("creative", "crafts"),
    "master-class": ("creative", "crafts"),
    "tour": ("nature", "excursion"),
    "excursion": ("nature", "excursion"),
    "walk": ("nature", "excursion"),
    "quiz": ("games", "quiz"),
    "dance": ("creative", "dance"),
    "literature": ("creative", "writing"),
    "business": ("education", "business"),
    "psychology": ("education", "psychology"),
    "language": ("education", "languages"),
    "photo": ("creative", "photography"),
    "fashion": ("creative", "design"),
}

# Правила на основе ключевых слов для подкатегорий
CATEGORY_RULES: list[dict[str, Any]] = [
    # Творчество (creative)
    {"category_id": "creative", "subcategory_id": "painting", "keywords": [
        "живопись", "живописи", "акварель", "акварелью", "масло", "холст", "картина", "картины",
        "рисование", "рисованию", "рисовать", "рисунок", "рисунки",
        "пленэр", "этюд", "пастель", "пастелью", "акрил", "акрилом", "гуашь", "гуашью",
        "painting", "watercolor", "художник", "художественный", "студия рисования",
    ]},
    {"category_id": "creative", "subcategory_id": "drawing", "keywords": [
        "скетч", "скетчинг", "набросок", "графика", "иллюстрация", "иллюстрации",
        "комикс", "комикса", "drawing", "sketch", "comic",
        "зарисовка", "карандаш", "тушь", "линер",
    ]},
    {"category_id": "creative", "subcategory_id": "crafts", "keywords": [
        "рукоделие", "поделки", "handmade", "шитьё", "шитье", "вязание", "вышивка",
        "мастер-класс", "мастер класс", "craft", "diy", "лепка", "керамика", "парфюм",
    ]},
    {"category_id": "creative", "subcategory_id": "theater", "keywords": [
        "спектакль", "театр", "пьеса", "постановка", "актёр", "актер", "актриса",
        "сцена", "режиссёр", "режиссер", "theatre", "theater", "drama", "play",
        "актёрское мастерство", "актерское мастерство",
    ]},
    {"category_id": "creative", "subcategory_id": "exhibition", "keywords": [
        "выставка", "экспозиция", "галерея", "музей", "вернисаж", "exhibition", "gallery", "museum",
    ]},
    {"category_id": "creative", "subcategory_id": "photography", "keywords": [
        "фото", "фотография", "съёмка", "съемка", "photo", "photography",
    ]},
    {"category_id": "creative", "subcategory_id": "dance", "keywords": [
        "танец", "танцы", "хореография", "балет", "dance", "ballet",
    ]},
    {"category_id": "creative", "subcategory_id": "design", "keywords": [
        "дизайн", "графический дизайн", "интерьер", "design",
    ]},
    {"category_id": "creative", "subcategory_id": "writing", "keywords": [
        "писатель", "литература", "поэзия", "проза", "writing", "literature", "poetry",
    ]},
    {"category_id": "creative", "subcategory_id": "sculpture", "keywords": [
        "скульптура", "скульптор", "лепка", "ваяние", "sculpture", "sculptor",
    ]},
    {"category_id": "creative", "subcategory_id": "pottery", "keywords": [
        "керамика", "гончар", "гончарный", "глина", "pottery", "ceramics",
    ]},
    {"category_id": "creative", "subcategory_id": "calligraphy", "keywords": [
        "каллиграфия", "чистописание", "calligraphy",
    ]},
    # Образование (education)
    {"category_id": "education", "subcategory_id": "public-speaking", "keywords": [
        "ораторское мастерство", "публичные выступления", "риторика", "красноречие", "public speaking", "speech",
    ]},
    {"category_id": "education", "subcategory_id": "business", "keywords": [
        "бизнес", "стартап", "менеджмент", "маркетинг", "предпринимательство", "business", "startup", "management",
    ]},
    {"category_id": "education", "subcategory_id": "psychology", "keywords": [
        "психология", "психотерапия", "коучинг", "личностный рост", "psychology", "coaching",
    ]},
    {"category_id": "education", "subcategory_id": "science", "keywords": [
        "лекция", "лекторий", "наука", "семинар", "конференция", "исследование", "science", "lecture", "seminar",
    ]},
    {"category_id": "education", "subcategory_id": "history", "keywords": [
        "история", "археология", "history", "historical",
    ]},
    {"category_id": "education", "subcategory_id": "languages", "keywords": [
        "английский", "немецкий", "французский", "испанский", "язык", "language",
    ]},
    {"category_id": "education", "subcategory_id": "programming", "keywords": [
        "программирование", "кодинг", "python", "javascript", "java", "разработка", "coding", "programming",
    ]},
    {"category_id": "education", "subcategory_id": "math", "keywords": [
        "математика", "алгебра", "геометрия", "math", "mathematics",
    ]},
    {"category_id": "education", "subcategory_id": "philosophy", "keywords": [
        "философия", "philosophy",
    ]},
    {"category_id": "education", "subcategory_id": "finance", "keywords": [
        "финансы", "инвестиции", "трейдинг", "криптовалюта", "finance", "investing",
    ]},
    # Игры (games)
    {"category_id": "games", "subcategory_id": "quiz", "keywords": [
        "квиз", "викторина", "интеллектуальная игра", "мозгобойня", "quiz", "trivia",
        "интеллектуальная вечеринка", "brainstorm", "что где когда",
    ]},
    {"category_id": "games", "subcategory_id": "board-games", "keywords": [
        "настольные игры", "настолки", "игротека", "board game",
    ]},
    {"category_id": "games", "subcategory_id": "mafia", "keywords": ["мафия", "mafia"]},
    {"category_id": "games", "subcategory_id": "chess", "keywords": ["шахматы", "chess"]},
    {"category_id": "games", "subcategory_id": "poker", "keywords": ["покер", "poker"]},
    {"category_id": "games", "subcategory_id": "video-games", "keywords": ["видеоигры", "киберспорт", "video game", "esports"]},
    {"category_id": "games", "subcategory_id": "card-games", "keywords": ["карточные игры", "карты", "дурак", "покер", "бридж", "card game"]},
    {"category_id": "games", "subcategory_id": "dnd", "keywords": ["dnd", "d&d", "данжен", "подземелья", "драконы", "ролевая игра", "ролёвка"]},
    # Музыка (music)
    {"category_id": "music", "subcategory_id": "concerts", "keywords": [
        "концерт", "фестиваль", "выступление", "группа", "оркестр", "concert", "festival", "live",
    ]},
    {"category_id": "music", "subcategory_id": "karaoke", "keywords": ["караоке", "karaoke"]},
    {"category_id": "music", "subcategory_id": "guitar", "keywords": ["гитара", "guitar"]},
    {"category_id": "music", "subcategory_id": "piano", "keywords": ["пианино", "фортепиано", "рояль", "piano"]},
    {"category_id": "music", "subcategory_id": "drums", "keywords": ["барабаны", "ударные", "drums"]},
    {"category_id": "music", "subcategory_id": "singing", "keywords": ["вокал", "пение", "петь", "singing", "vocal"]},
    {"category_id": "music", "subcategory_id": "djing", "keywords": ["диджей", "djing", "dj"]},
    {"category_id": "music", "subcategory_id": "production", "keywords": ["музыкальное производство", "саунд-дизайн", "аранжировка", "music production"]},
    # Еда (food)
    {"category_id": "food", "subcategory_id": "cooking", "keywords": [
        "кулинарный", "готовка", "шеф-повар", "рецепт", "cooking", "culinary",
    ]},
    {"category_id": "food", "subcategory_id": "restaurants", "keywords": [
        "ресторан", "кафе", "ужин", "обед", "restaurant", "cafe", "dinner",
    ]},
    {"category_id": "food", "subcategory_id": "wine-tasting", "keywords": ["вино", "дегустация", "wine", "tasting"]},
    {"category_id": "food", "subcategory_id": "coffee", "keywords": ["кофе", "coffee", "бариста"]},
    {"category_id": "food", "subcategory_id": "baking", "keywords": ["выпечка", "печь", "хлеб", "десерт", "baking"]},
    {"category_id": "food", "subcategory_id": "tea", "keywords": ["чай", "чаепитие", "tea"]},
    {"category_id": "food", "subcategory_id": "vegetarian", "keywords": ["вегетарианство", "веган", "веганство", "vegetarian", "vegan"]},
    {"category_id": "food", "subcategory_id": "street-food", "keywords": ["стритфуд", "уличная еда", "фудтрак", "street food"]},
    # Природа (nature)
    {"category_id": "nature", "subcategory_id": "excursion", "keywords": [
        "экскурсия", "прогулка", "обзорная", "гид", "экскурсовод", "excursion", "tour", "walk",
    ]},
    {"category_id": "nature", "subcategory_id": "hiking", "keywords": ["поход", "треккинг", "восхождение", "hiking", "trekking"]},
    {"category_id": "nature", "subcategory_id": "camping", "keywords": ["кемпинг", "палатка", "camping"]},
    {"category_id": "nature", "subcategory_id": "fishing", "keywords": ["рыбалка", "fishing"]},
    {"category_id": "nature", "subcategory_id": "gardening", "keywords": ["садоводство", "огород", "цветы", "gardening"]},
    {"category_id": "nature", "subcategory_id": "picnic", "keywords": ["пикник", "picnic"]},
    {"category_id": "nature", "subcategory_id": "bird-watching", "keywords": ["наблюдение за птицами", "бердвотчинг", "bird watching", "орнитология"]},
    {"category_id": "nature", "subcategory_id": "mushroom-picking", "keywords": ["грибы", "грибная охота", "тихая охота", "mushroom"]},
    # Кино (cinema)
    {"category_id": "cinema", "subcategory_id": "movies", "keywords": ["кино", "фильм", "кинопоказ", "movie", "film", "cinema"]},
    {"category_id": "cinema", "subcategory_id": "film-club", "keywords": ["киноклуб", "film club"]},
    {"category_id": "cinema", "subcategory_id": "series", "keywords": ["сериал", "сериалы", "series"]},
    {"category_id": "cinema", "subcategory_id": "filmmaking", "keywords": ["кинопроизводство", "сценарий", "режиссура", "filmmaking"]},
    {"category_id": "cinema", "subcategory_id": "documentary", "keywords": ["документальный", "документалистика", "documentary"]},
    {"category_id": "cinema", "subcategory_id": "animation", "keywords": ["анимация", "мультфильм", "animation"]},
    # Спорт (sport)
    {"category_id": "sport", "subcategory_id": "fitness", "keywords": ["фитнес", "тренировка", "fitness", "workout"]},
    {"category_id": "sport", "subcategory_id": "yoga", "keywords": ["йога", "yoga"]},
    {"category_id": "sport", "subcategory_id": "running", "keywords": ["бег", "марафон", "running", "marathon"]},
    {"category_id": "sport", "subcategory_id": "football", "keywords": ["футбол", "football", "soccer"]},
    {"category_id": "sport", "subcategory_id": "basketball", "keywords": ["баскетбол", "basketball"]},
    {"category_id": "sport", "subcategory_id": "tennis", "keywords": ["теннис", "tennis"]},
    {"category_id": "sport", "subcategory_id": "swimming", "keywords": ["плавание", "бассейн", "swimming"]},
    {"category_id": "sport", "subcategory_id": "cycling", "keywords": ["велоспорт", "велогонка", "cycling"]},
    {"category_id": "sport", "subcategory_id": "boxing", "keywords": ["бокс", "boxing"]},
    {"category_id": "sport", "subcategory_id": "martial-arts", "keywords": ["единоборства", "каратэ", "карате", "дзюдо", "самбо", "martial arts"]},
    {"category_id": "sport", "subcategory_id": "volleyball", "keywords": ["волейбол", "volleyball"]},
    {"category_id": "sport", "subcategory_id": "hockey", "keywords": ["хоккей", "hockey"]},
    {"category_id": "sport", "subcategory_id": "skating", "keywords": ["коньки", "каток", "skating"]},
    {"category_id": "sport", "subcategory_id": "skiing", "keywords": ["лыжи", "skiing"]},
    {"category_id": "sport", "subcategory_id": "climbing", "keywords": ["скалолазание", "climbing"]},
]

SUBCATEGORY_BY_CATEGORY: dict[str, set[str]] = {
    "sport": {"running", "football", "basketball", "volleyball", "tennis", "yoga", "fitness", "swimming", "cycling", "hockey", "skating", "skiing", "boxing", "martial-arts", "climbing"},
    "creative": {"drawing", "photography", "painting", "sculpture", "crafts", "pottery", "design", "writing", "calligraphy", "theater", "exhibition", "dance"},
    "education": {"languages", "programming", "math", "science", "history", "philosophy", "psychology", "finance", "business", "public-speaking"},
    "games": {"board-games", "card-games", "video-games", "mafia", "chess", "poker", "dnd", "quiz"},
    "music": {"concerts", "karaoke", "guitar", "piano", "drums", "singing", "djing", "production"},
    "food": {"cooking", "baking", "restaurants", "wine-tasting", "coffee", "tea", "vegetarian", "street-food"},
    "nature": {"hiking", "camping", "picnic", "bird-watching", "gardening", "fishing", "mushroom-picking", "excursion"},
    "cinema": {"movies", "film-club", "series", "filmmaking", "documentary", "animation"},
}


# ===== Вспомогательные функции =====


def _fetch_json(url: str) -> dict[str, Any]:
    """GET-запрос к KudaGo API и парсинг JSON."""
    request = Request(
        url,
        headers={
            "User-Agent": "wedo-kudago-import/1.0",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urlopen(request, timeout=30) as response:
        body = response.read()
    return __import__("json").loads(body.decode("utf-8"))


def _strip_html(value: Any) -> str:
    import re
    text = str(value or "")
    text = text.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    text = text.replace("</p><p>", "\n\n").replace("</p> <p>", "\n\n")
    text = text.replace("<p>", "").replace("</p>", "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _normalize_text(value: Any) -> str:
    return _strip_html(value).lower()


def _count_keyword_matches(text: str, keyword: str) -> int:
    """Подсчитывает вхождения keyword в text со stem-эвристикой для русских окончаний.

    Аналог countKeywordMatches() из JS-скрипта.
    """
    if not text or not keyword:
        return 0
    # Точное вхождение подстроки
    if keyword in text:
        return text.count(keyword)
    # Stem-эвристика для русских окончаний (keyword >= 5 символов)
    if len(keyword) >= 5:
        stem = keyword[:-1]
        if len(stem) >= 4 and stem in text:
            return text.count(stem)
    return 0


def _normalize_title(value: Any) -> str:
    import re
    text = str(value or "")
    text = re.sub(r"\s*\(\d{1,2}\s+[а-яё.]+\)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _should_distrust_education_category(event: dict[str, Any]) -> bool:
    """Проверяет, не является ли education-категория ошибочной (творчество или игры).

    Аналог shouldDistrustEducationCategory() из JS-скрипта.
    """
    text = _normalize_text(" ".join(
        str(x) for x in [
            event.get("title", ""),
            event.get("short_title", ""),
            event.get("description", ""),
            event.get("body_text", ""),
            event.get("tagline", ""),
            *(event.get("tags") or []),
            event.get("slug", ""),
        ] if x
    ))

    creative_signals = [
        "мастер-класс", "мастер класс", "живоп", "рисова", "акварел", "пастел",
        "акрил", "гуаш", "скетч", "комикс", "иллюстрац", "фото", "фотограф",
        "актёр", "актер", "театр", "сцена", "танц", "хореограф", "дизайн",
        "керамик", "лепк", "рукодел", "шить", "вязани", "парфюм", "творческ",
    ]
    games_signals = [
        "квиз", "викторин", "мозгобойн", "что где когда", "интеллектуальная игра",
    ]

    return any(s in text for s in creative_signals) or any(s in text for s in games_signals)


def _normalize_coords(
    lat: float, lon: float,
    preferred_timezone: str | None = None,
) -> tuple[float, float]:
    """Нормализует координаты, детектит перепутанные lat/lon (swapped).

    Аналог normalizeCoords() из JS-скрипта.
    Если обе координаты равны 0 — возвращает (0.0, 0.0).
    """
    if lat == 0.0 and lon == 0.0:
        return (0.0, 0.0)

    def is_valid_lat(v: float) -> bool:
        return -90.0 <= v <= 90.0

    def is_valid_lon(v: float) -> bool:
        return -180.0 <= v <= 180.0

    primary = (lat, lon)
    swapped = (lon, lat)

    primary_valid = is_valid_lat(primary[0]) and is_valid_lon(primary[1])
    swapped_valid = is_valid_lat(swapped[0]) and is_valid_lon(swapped[1])

    if not primary_valid and not swapped_valid:
        return None
    if not primary_valid and swapped_valid:
        return swapped
    if primary_valid and not swapped_valid:
        return primary

    # Частый кейс KudaGo: lat/lon в РФ приезжают наоборот
    # Например: lat=37.61 lon=55.75 -> это почти наверняка swapped
    if primary[0] < 45 and primary[1] > 45:
        return swapped

    if preferred_timezone:
        primary_tz = _get_timezone(primary[0], primary[1])
        swapped_tz = _get_timezone(swapped[0], swapped[1])
        if swapped_tz == preferred_timezone and primary_tz != preferred_timezone:
            return swapped
        if primary_tz == preferred_timezone:
            return primary

    return primary


def _parse_price(event: dict[str, Any]) -> float:
    if event.get("is_free"):
        return 0.0
    raw = str(event.get("price") or "").strip().lower()
    if not raw or raw == "0" or "бесплат" in raw:
        return 0.0
    import re
    numbers = re.findall(r"\d[\d\s]*(?:[.,]\d+)?", raw)
    if not numbers:
        return 0.0
    first = numbers[0].replace(" ", "").replace(",", ".")
    try:
        return round(float(first), 2)
    except (ValueError, TypeError):
        return 0.0


def _parse_age_restriction(value: Any) -> int | None:
    raw = str(value or "").strip()
    import re
    match = re.search(r"(\d{1,2})\s*\+", raw)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, TypeError):
            return None
    return None


def _pick_category(event: dict[str, Any]) -> tuple[str, str | None] | None:
    """Определяет category_id и subcategory_id для события из KudaGo.

    Возвращает None, если категорию не удалось определить.
    Аналог pickCategory() из JS-скрипта.
    """
    # 1. Пробуем маппинг по категориям KudaGo
    kudago_categories = event.get("categories") or []
    kudago_match = None
    for cat in kudago_categories:
        normalized = str(cat).lower().strip()
        if normalized in KUDAGO_CATEGORY_MAPPING:
            kudago_match = KUDAGO_CATEGORY_MAPPING[normalized]
            break

    # 2. Анализ текста по ключевым словам
    haystack = _normalize_text(" ".join(
        str(x) for x in [
            event.get("title", ""),
            event.get("short_title", ""),
            event.get("description", ""),
            event.get("body_text", ""),
            event.get("tagline", ""),
            *(event.get("tags") or []),
            event.get("slug", ""),
        ] if x
    ))

    keyword_scores: dict[str, dict[str, Any]] = {}
    for rule in CATEGORY_RULES:
        score = 0
        for keyword in rule["keywords"]:
            kw_lower = keyword.lower()
            count = _count_keyword_matches(haystack, kw_lower)
            if count > 0:
                weight = 3 if len(keyword) > 5 else 1
                title_normalized = _normalize_text(event.get("title", ""))
                if _count_keyword_matches(title_normalized, kw_lower) > 0:
                    weight += 5
                score += count * weight
        if score > 0:
            key = f"{rule['category_id']}:{rule['subcategory_id']}"
            if key not in keyword_scores or score > keyword_scores[key]["score"]:
                keyword_scores[key] = {"category_id": rule["category_id"], "subcategory_id": rule["subcategory_id"], "score": score}

    keyword_winner = max(keyword_scores.values(), key=lambda x: x["score"]) if keyword_scores else None

    # 3. Если есть маппинг KudaGo — используем его (с исключением для education)
    if kudago_match:
        cat_id, subcat_id = kudago_match
        if (
            cat_id == "education"
            and keyword_winner
            and keyword_winner["category_id"] != "education"
            and (_should_distrust_education_category(event) or keyword_winner["score"] >= 3)
        ):
            return keyword_winner["category_id"], keyword_winner["subcategory_id"]
        return cat_id, subcat_id

    # 4. Если нет маппинга — используем победителя по ключевым словам
    if keyword_winner:
        return keyword_winner["category_id"], keyword_winner["subcategory_id"]

    # 5. Не удалось определить категорию
    return None


def _pick_subcategory(category_id: str, event: dict[str, Any]) -> str | None:
    """Уточняет subcategory_id на основе ключевых слов.

    Аналог pickSubcategory() из JS-скрипта.
    """
    haystack = _normalize_text(" ".join(
        str(x) for x in [
            event.get("title", ""),
            event.get("short_title", ""),
            event.get("description", ""),
            event.get("body_text", ""),
            *(event.get("tags") or []),
            event.get("slug", ""),
        ] if x
    ))

    title_normalized = _normalize_text(event.get("title", ""))

    candidates = [r for r in CATEGORY_RULES if r["category_id"] == category_id]
    winner = None
    for rule in candidates:
        score = 0
        for keyword in rule["keywords"]:
            kw_lower = keyword.lower()
            count = _count_keyword_matches(haystack, kw_lower)
            if count > 0:
                weight = 3 if len(keyword) > 5 else 1
                if _count_keyword_matches(title_normalized, kw_lower) > 0:
                    weight += 5
                score += count * weight
        if score > 0 and (not winner or score > winner["score"]):
            winner = {"subcategory_id": rule["subcategory_id"], "score": score}

    if winner:
        return winner["subcategory_id"]

    known = SUBCATEGORY_BY_CATEGORY.get(category_id)
    if known:
        return next(iter(known))
    return None


def _download_and_save_image(image_url: str, kudago_id: int, index: int) -> int | None:
    """Скачивает изображение, обрабатывает (ресайз + JPEG) и сохраняет как обычное фото."""
    from files.views import _process_image

    try:
        req = Request(
            image_url,
            headers={"User-Agent": "wedo-kudago-import/1.0"},
        )
        with urlopen(req, timeout=15) as response:
            raw_bytes = response.read()

        if not raw_bytes:
            return None

        # Обрабатываем через _process_image (ресайз, EXIF-транспонирование, JPEG quality=85)
        processed_bytes = _process_image(raw_bytes)

        # Генерируем уникальное имя файла (всегда .jpg, т.к. на выходе JPEG)
        filename = f"{uuid.uuid4().hex}.jpg"

        # Сохраняем в media/activities/ как обычные фото
        storage_key = f"activities/{filename}"
        full_path = os.path.join(settings.MEDIA_ROOT, storage_key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(processed_bytes)

        # Создаём запись в таблице files
        file_obj = File.objects.create(
            storage_key=storage_key,
            original_name=f"kudago_{kudago_id}_{index}.jpg",
            mime_type="image/jpeg",
            size=len(processed_bytes),
        )
        return file_obj.id

    except (HTTPError, URLError, OSError) as exc:
        logger.warning("Failed to download image %s: %s", image_url, exc)
        return None


def _parse_image_urls(images: list[dict[str, Any]]) -> list[str]:
    """Извлекает URL изображений из ответа KudaGo API."""
    urls: list[str] = []
    for image in images or []:
        if not isinstance(image, dict):
            continue
        url = (
            image.get("image")
            or image.get("url")
            or (image.get("thumbnails") or {}).get("640x384")
            or (image.get("thumbnails") or {}).get("144x96")
        )
        if url and url not in urls:
            urls.append(url)
    return urls[:4]


def _map_event_to_activity(
    event: dict[str, Any],
    location_slug: str,
    actual_since: int,
    actual_until: int,
) -> list[dict[str, Any]]:
    """Преобразует событие из KudaGo API в список словарей для создания Activity.

    Для каждой даты события в пределах [actual_since, actual_until]
    создаётся отдельный Activity.
    """
    event_id = event.get("id", "?")
    dates = event.get("dates") or []
    if not dates:
        logger.warning("Событие %s пропущено: нет дат (dates=%s)", event_id, dates)
        return []

    place = event.get("place") or {}
    location_data = event.get("location") or {}

    category_result = _pick_category(event)
    if category_result is None:
        logger.warning(
            "Событие %s пропущено: не удалось определить категорию "
            "(categories=%s, title=%s)",
            event_id, event.get("categories"), event.get("title"),
        )
        return []
    category_id, subcategory_id = category_result
    if not subcategory_id:
        subcategory_id = _pick_subcategory(category_id, event)

    # Уточнение для творческих мастер-классов: crafts → painting/drawing
    if category_id == "creative" and subcategory_id == "crafts":
        text = _normalize_title(
            f"{event.get('description') or ''} {event.get('title') or ''}"
        )
        if any(kw in text for kw in ("живоп", "акварел", "масл", "пастел")):
            subcategory_id = "painting"
        elif any(kw in text for kw in ("рисова", "скетч", "комикс", "иллюстрац")):
            subcategory_id = "drawing"

    # Определяем формат
    is_online = location_data.get("slug") == "online" and not place
    fmt = "online" if is_online else "offline"

    # Координаты с нормализацией (определение перепутанных lat/lon)
    coords = place.get("coords") or {}
    raw_lat = float(coords.get("lat", 0)) if coords.get("lat") else 0.0
    raw_lon = float(coords.get("lon", 0)) if coords.get("lon") else 0.0
    lat, lon = _normalize_coords(raw_lat, raw_lon)

    # Определяем часовой пояс по координатам
    time_zone = _get_timezone(lat, lon)
    if time_zone is None:
        logger.warning(
            "Событие %s пропущено: нет координат места "
            "(coords=%s, place=%s)",
            event_id, coords, place.get("title"),
        )
        return []

    title = _normalize_title(event.get("short_title") or event.get("title") or "")
    body = _strip_html(event.get("body_text") or event.get("description") or "")
    if body:
        description = body
    else:
        tagline = event.get("tagline")
        description = f"{title} · {_strip_html(tagline)}" if tagline else title

    site_url = event.get("site_url") or ""
    if not site_url:
        logger.warning(
            "Событие %s пропущено: нет site_url (title=%s)",
            event_id, event.get("title"),
        )
        return []

    price = _parse_price(event)
    age_from = _parse_age_restriction(event.get("age_restriction"))

    # Фильтруем даты по временному окну и создаём Activity на каждую
    activities: list[dict[str, Any]] = []
    for date_index, date_entry in enumerate(dates):
        try:
            start_ts = float(date_entry["start"])
        except (KeyError, TypeError, ValueError):
            continue

        # Пропускаем даты вне запрошенного окна
        if start_ts < actual_since or start_ts > actual_until:
            continue

        try:
            end_ts = float(date_entry.get("end", date_entry["start"]))
        except (TypeError, ValueError):
            end_ts = start_ts

        start_at = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end_at = datetime.fromtimestamp(end_ts, tz=timezone.utc)

        activity = {
            "source": Activity.Source.KUDAGO,
            "organizer": None,
            "kudago_id": event["id"],
            "kudago_url": site_url,
            "title": title,
            "description": description,
            "category_id": category_id,
            "subcategory_id": subcategory_id,
            "format": fmt,
            "status": Activity.Status.ACTIVE,
            "location_latitude": lat,
            "location_longitude": lon,
            "location_address": place.get("address") or f"{location_data.get('name', '')}, {place.get('title', '')}",
            "location_name": place.get("title") or place.get("short_title") or title,
            "location_settlement": location_data.get("name") or location_slug,
            "location_region": location_data.get("name") or location_slug,
            "location_country": "Россия",
            "start_at": start_at,
            "end_at": end_at,
            "time_zone": time_zone,
            "price": price,
            "pref_age_from": age_from,
            "requires_approval": False,
            "photo_file_ids": [],
        }

        # Если is_free — принудительно ставим цену 0
        if event.get("is_free"):
            activity["price"] = 0.0

        activities.append(activity)

    return activities


class Command(BaseCommand):
    help = "Импортирует события из KudaGo API в базу данных."

    def add_arguments(self, parser):
        parser.add_argument(
            "--location",
            default="",
            help="Город KudaGo (msk, spb, ekb и т.д.). По умолчанию: все города",
        )
        parser.add_argument(
            "--days-ahead",
            type=int,
            default=30,
            help="На сколько дней вперёд импортировать события. По умолчанию: 30",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="Размер страницы (макс. 100). По умолчанию: 100",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=0,
            help="Максимальное количество страниц для импорта (0 = без ограничения)",
        )
        parser.add_argument(
            "--categories",
            default=None,
            help="Фильтр по категориям KudaGo, например: concert,theater",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Режим проверки: не создавать записи в БД, только вывести статистику",
        )
        parser.add_argument(
            "--skip-photos",
            action="store_true",
            help="Не скачивать фото (только метаданные)",
        )

    def handle(self, *args, **options):
        location_slug = options["location"]
        days_ahead = options["days_ahead"]
        page_size = min(options["page_size"], 100)
        max_pages = options["max_pages"]
        categories = options["categories"]
        dry_run = options["dry_run"]
        skip_photos = options["skip_photos"]

        now = datetime.now(timezone.utc)
        actual_since = int(now.timestamp())
        actual_until = int((now + timedelta(days=days_ahead)).timestamp())

        location_label = location_slug if location_slug else "все города"
        self.stdout.write(f"Импорт событий KudaGo для города: {location_label}")
        self.stdout.write(f"Период: {now.isoformat()} — {(now + timedelta(days=days_ahead)).isoformat()}")
        if max_pages > 0:
            self.stdout.write(f"Максимум страниц: {max_pages}")
        if categories:
            self.stdout.write(f"Фильтр по категориям: {categories}")
        if dry_run:
            self.stdout.write(self.style.WARNING("РЕЖИМ DRY-RUN: изменения в БД не будут сохранены"))
        self.stdout.write("")

        # Собираем все события через пагинацию
        all_events: list[dict[str, Any]] = []
        page = 1

        while True:
            params: dict[str, Any] = {
                "lang": "ru",
                "page": page,
                "page_size": page_size,
                "fields": DEFAULT_FIELDS,
                "expand": "dates,place,location,images",
                "text_format": "text",
                "actual_since": actual_since,
                "actual_until": actual_until,
                "order_by": "-publication_date",
            }
            if location_slug:
                params["location"] = location_slug
            if categories:
                params["categories"] = categories

            url = f"{API_BASE_URL}?{urlencode(params)}"
            self.stdout.write(f"Запрос страницы {page}...")

            try:
                payload = _fetch_json(url)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Ошибка запроса: {exc}"))
                break

            results = payload.get("results") or []
            if not results:
                break

            all_events.extend(results)
            self.stdout.write(f"  Получено событий: {len(results)} (всего: {len(all_events)})")

            if max_pages > 0 and page >= max_pages:
                self.stdout.write(f"  Достигнут лимит страниц ({max_pages})")
                break

            if not payload.get("next"):
                break
            page += 1

        self.stdout.write(f"\nВсего получено событий из API: {len(all_events)}")
        self.stdout.write("")

        # Фильтруем дубликаты (уже есть в БД) по паре (kudago_id, start_at)
        existing_pairs: set[tuple[int, datetime]] = set(
            Activity.objects.filter(
                kudago_id__isnull=False,
                source=Activity.Source.KUDAGO,
            ).values_list("kudago_id", "start_at")
        )

        # Собираем все Activity из новых событий
        all_activities_data: list[tuple[dict[str, Any], dict[str, Any]]] = []  # (activity_data, event)
        for event in all_events:
            activities_data = _map_event_to_activity(event, location_slug, actual_since, actual_until)
            for ad in activities_data:
                pair = (ad["kudago_id"], ad["start_at"])
                if pair not in existing_pairs:
                    all_activities_data.append((ad, event))
                    existing_pairs.add(pair)

        duplicates = len(all_events) - len(all_activities_data)

        self.stdout.write(f"Новых активностей: {len(all_activities_data)}")
        self.stdout.write(f"Пропущено (дубликаты): {duplicates}")
        self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("DRY-RUN завершён. Никаких изменений не сделано."))
            return

        # Создаём активности
        created_count = 0
        photo_count = 0
        error_count = 0

        for activity_data, event in all_activities_data:
            try:
                activity = Activity.objects.create(**activity_data)

                # Скачиваем фото
                if not skip_photos:
                    image_urls = _parse_image_urls(event.get("images") or [])
                    file_ids: list[int] = []
                    for idx, img_url in enumerate(image_urls):
                        file_id = _download_and_save_image(img_url, event["id"], idx)
                        if file_id:
                            file_ids.append(file_id)
                            photo_count += 1
                    if file_ids:
                        activity.photo_file_ids = file_ids
                        activity.save(update_fields=["photo_file_ids"])

                created_count += 1
                if created_count % 10 == 0:
                    self.stdout.write(f"  Создано: {created_count}...")

            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Ошибка при создании активности (kudago_id={activity_data.get('kudago_id')}): {exc}"))
                error_count += 1

        # Итог
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Импорт завершён ==="))
        self.stdout.write(f"  Город: {location_slug}")
        self.stdout.write(f"  Создано активностей: {created_count}")
        self.stdout.write(f"  Скачано фото: {photo_count}")
        self.stdout.write(f"  Пропущено (дубликаты): {duplicates}")
        self.stdout.write(f"  Ошибок: {error_count}")
