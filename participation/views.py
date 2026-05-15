from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone

from activities.models import Activity
from .models import Participation
from .serializers import ActivityParticipantSerializer, ActivityJoinRequestSerializer


class ActivityJoinView(APIView):
    """POST /activities/:id/join — вступить без подтверждения."""
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id, status=Activity.Status.ACTIVE)

        # KudaGo-событие без организатора — нельзя вступить (некому подтверждать)
        if activity.source == Activity.Source.KUDAGO and activity.organizer_id is None:
            return Response(
                {'error': {'code': 'NO_ORGANIZER', 'message': 'У этого события пока нет организатора'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if activity.organizer == request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Организатор не может участвовать в своей активности'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        if activity.requires_approval:
            return Response(
                {'error': {'code': 'REQUIRES_APPROVAL', 'message': 'Эта активность требует подтверждения заявки'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if activity.pref_max_participants:
            accepted_count = activity.participations.filter(
                status__in=[Participation.Status.ACCEPTED, Participation.Status.ATTENDED]
            ).count()
            if activity.organizer_id:
                accepted_count += 1
            if accepted_count >= activity.pref_max_participants:
                return Response(
                    {'error': {'code': 'ACTIVITY_FULL', 'message': 'Нет свободных мест'}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        participation, created = Participation.objects.get_or_create(
            activity=activity,
            user=request.user,
            defaults={'status': Participation.Status.ACCEPTED},
        )

        if not created and participation.status != Participation.Status.REJECTED:
            return Response(
                {'error': {'code': 'ALREADY_JOINED', 'message': 'Вы уже участвуете в этой активности'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not created:
            participation.status = Participation.Status.ACCEPTED
            participation.save()

        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityRequestMeView(APIView):
    """POST/DELETE /activities/:id/join-requests/me — подать / отменить заявку."""
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id, status=Activity.Status.ACTIVE)

        # KudaGo-событие без организатора — нельзя подать заявку (некому подтверждать)
        if activity.source == Activity.Source.KUDAGO and activity.organizer_id is None:
            return Response(
                {'error': {'code': 'NO_ORGANIZER', 'message': 'У этого события пока нет организатора'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if activity.organizer == request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Организатор не может подавать заявку на свою активность'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        participation, created = Participation.objects.get_or_create(
            activity=activity,
            user=request.user,
            defaults={'status': Participation.Status.PENDING},
        )

        if not created:
            return Response(
                {'error': {'code': 'ALREADY_REQUESTED', 'message': 'Заявка уже существует'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from notifications.services import notify_join_request
        notify_join_request(
            organizer=activity.organizer,
            applicant=request.user,
            activity=activity,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, activity_id):
        participation = get_object_or_404(
            Participation,
            activity_id=activity_id,
            user=request.user,
            status=Participation.Status.PENDING,
        )
        participation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityLeaveView(APIView):
    """DELETE /activities/:id/participants/me — выйти из активности."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, activity_id):
        participation = get_object_or_404(
            Participation,
            activity_id=activity_id,
            user=request.user,
            status=Participation.Status.ACCEPTED,
        )
        participation.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityJoinRequestApproveView(APIView):
    """POST /activities/:id/join-requests/:user_id/approve — одобрить заявку."""
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id, user_id):
        activity = get_object_or_404(Activity, id=activity_id)

        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Только организатор может одобрять заявки'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        participation = get_object_or_404(
            Participation,
            activity_id=activity_id,
            user_id=user_id,
            status=Participation.Status.PENDING,
        )

        if activity.pref_max_participants:
            accepted_count = activity.participations.filter(
                status__in=[Participation.Status.ACCEPTED, Participation.Status.ATTENDED]
            ).count()
            if activity.organizer_id:
                accepted_count += 1
            if accepted_count >= activity.pref_max_participants:
                return Response(
                    {'error': {'code': 'ACTIVITY_FULL', 'message': 'Нет свободных мест'}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        participation.status = Participation.Status.ACCEPTED
        participation.save()

        from notifications.services import notify_join_request_approved
        notify_join_request_approved(
            applicant=participation.user,
            activity=activity,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityJoinRequestRejectView(APIView):
    """POST /activities/:id/join-requests/:user_id/reject — отклонить заявку."""
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id, user_id):
        activity = get_object_or_404(Activity, id=activity_id)

        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Только организатор может отклонять заявки'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        participation = get_object_or_404(
            Participation,
            activity_id=activity_id,
            user_id=user_id,
            status=Participation.Status.PENDING,
        )
        participation.status = Participation.Status.REJECTED
        participation.save()

        from notifications.services import notify_join_request_rejected
        notify_join_request_rejected(
            applicant=participation.user,
            activity=activity,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityParticipantsView(APIView):
    """GET /activities/:id/participants — список участников."""
    permission_classes = [IsAuthenticated]

    def get(self, request, activity_id):
        get_object_or_404(Activity, id=activity_id)

        limit = min(int(request.query_params.get('limit', 30)), 50)
        cursor = request.query_params.get('cursor')

        queryset = Participation.objects.filter(
            activity_id=activity_id,
            status__in=[Participation.Status.ACCEPTED, Participation.Status.ATTENDED],
        ).select_related('user')

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more else None

        return Response({
            'items': ActivityParticipantSerializer(items, many=True).data,
            'next_cursor': next_cursor,
            'has_more': has_more,
        })


class ActivityJoinRequestsView(APIView):
    """GET /activities/:id/join-requests — список pending заявок для организатора."""
    permission_classes = [IsAuthenticated]

    def get(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id)

        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Только организатор может видеть заявки'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        limit = min(int(request.query_params.get('limit', 20)), 50)
        cursor = request.query_params.get('cursor')

        queryset = Participation.objects.filter(
            activity_id=activity_id,
            status=Participation.Status.PENDING,
        ).select_related('user')

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more else None

        return Response({
            'items': ActivityJoinRequestSerializer(items, many=True).data,
            'next_cursor': next_cursor,
            'has_more': has_more,
        })


class ActivityAttendanceView(APIView):
    """POST /activities/:id/attendance — отметить посещение вручную."""
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id)

        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Только организатор может отмечать посещение'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        user_id = request.data.get('user_id')
        if not user_id:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'user_id обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        participation = get_object_or_404(
            Participation,
            activity_id=activity_id,
            user_id=user_id,
            status=Participation.Status.ACCEPTED,
        )
        participation.status = Participation.Status.ATTENDED
        participation.attendance_marked_at = timezone.now()
        participation.save()

        return Response(status=status.HTTP_204_NO_CONTENT)
