"""Фоновые задачи для расчёта рейтингов организаторов."""
import math

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db.models import Avg
from django.utils import timezone


@shared_task
def recalculate_organizer_rating(organizer_id):
    """
    Пересчёт байесовского рейтинга организатора с временным затуханием.

    R(o) = (v_w * M_w(o) + m * C) / (v_w + m)
        v_w = Σ λ(t_i)               — эффективный взвешенный вес оценок
        M_w(o) = Σ λ(t_i)*r_i / v_w  — взвешенное среднее по оценкам
        λ(t_i) = exp(-α * Δt_i)      — временное затухание
        C — среднее по платформе (общая «уверенность по умолчанию»)
        m — параметр сглаживания (минимальное доверенное число оценок)

    Вынесено в Celery, чтобы POST /activities/:id/ratings отвечал быстро —
    клиент получает ответ сразу, пересчёт идёт фоном на воркере.
    """
    from .models import ActivityRating

    User = get_user_model()
    try:
        organizer = User.objects.get(id=organizer_id)
    except User.DoesNotExist:
        return  # организатор удалился, делать нечего

    alpha = 0.01  # скорость затухания: оценка теряет половину веса за ~70 дней
    m = 5         # минимальное доверенное число оценок

    now = timezone.now()

    ratings = list(
        ActivityRating.objects.filter(
            activity__organizer=organizer,
        ).values('rating', 'created_at')
    )

    if not ratings:
        organizer.rating = 0.0
        organizer.save(update_fields=['rating'])
        return

    # взвешенные суммы с учётом временного затухания
    weighted_sum = 0.0
    weight_total = 0.0
    for r in ratings:
        delta_t = (now - r['created_at']).days
        lam = math.exp(-alpha * delta_t)
        weighted_sum += lam * r['rating']
        weight_total += lam

    v_w = weight_total
    m_w = weighted_sum / weight_total if weight_total > 0 else 0.0

    # C — среднее по платформе (общая «средняя температура»)
    c = ActivityRating.objects.aggregate(avg=Avg('rating'))['avg'] or 0.0

    r_final = (v_w * m_w + m * c) / (v_w + m)

    organizer.rating = round(r_final, 2)
    organizer.save(update_fields=['rating'])
