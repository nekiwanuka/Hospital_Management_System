from datetime import timedelta

from django.db.models import Min, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import branch_queryset_for_user
from apps.inventory.models import Batch, Item
from apps.inventory.serializers import (
    BatchSerializer,
    BatchStockEntrySerializer,
    DispenseCreateSerializer,
    DispenseSerializer,
    InventoryListItemSerializer,
    ItemSerializer,
    inventory_dashboard_payload,
)


def _has_inventory_role(user):
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or user.role
            in {
                "pharmacist",
                "lab_technician",
                "radiology_technician",
                "doctor",
                "cashier",
                "system_admin",
                "director",
            }
        )
    )


class ItemListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not _has_inventory_role(request.user):
            raise PermissionDenied("You do not have access to medical stores API.")

    def get_queryset(self):  # type: ignore[override]
        queryset = branch_queryset_for_user(
            self.request.user,
            Item.objects.select_related("category", "brand").order_by("item_name"),
        )
        q = (self.request.GET.get("q") or "").strip()
        if q:
            queryset = queryset.filter(
                Q(item_name__icontains=q)
                | Q(generic_name__icontains=q)
                | Q(barcode__icontains=q)
            )
        return queryset


class ItemDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not _has_inventory_role(request.user):
            raise PermissionDenied("You do not have access to medical stores API.")

    def get_queryset(self):  # type: ignore[override]
        return branch_queryset_for_user(
            self.request.user,
            Item.objects.select_related("category", "brand"),
        )

    def destroy(self, request, *args, **kwargs):
        if not (
            request.user.is_superuser
            or request.user.role in {"director", "system_admin"}
        ):
            raise PermissionDenied(
                "Only director or system admin can delete from medical stores."
            )
        return super().destroy(request, *args, **kwargs)


class StockAddAPIView(generics.CreateAPIView):
    serializer_class = BatchStockEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not _has_inventory_role(request.user):
            raise PermissionDenied("You do not have access to medical stores API.")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = serializer.save()
        output = BatchSerializer(batch)
        return Response(output.data, status=status.HTTP_201_CREATED)


class InventoryViewAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _has_inventory_role(request.user):
            raise PermissionDenied("You do not have access to medical stores API.")

        queryset = branch_queryset_for_user(
            request.user,
            Item.objects.select_related("category", "brand")
            .prefetch_related("batches")
            .order_by("item_name"),
        )

        q = (request.GET.get("q") or "").strip()
        category_id = (request.GET.get("category") or "").strip()
        expiring_soon = (request.GET.get("expiring_soon") or "").strip().lower()
        out_of_stock = (request.GET.get("out_of_stock") or "").strip().lower()

        if q:
            queryset = queryset.filter(
                Q(item_name__icontains=q)
                | Q(generic_name__icontains=q)
                | Q(barcode__icontains=q)
            )

        if category_id.isdigit():
            queryset = queryset.filter(category_id=int(category_id))

        today = timezone.localdate()
        in_30_days = today + timedelta(days=30)

        queryset = queryset.annotate(
            quantity_on_hand=Coalesce(Sum("batches__quantity_remaining"), 0),
            next_expiry=Min("batches__exp_date"),
        )

        if expiring_soon in {"1", "true", "yes"}:
            queryset = queryset.filter(
                batches__quantity_remaining__gt=0,
                batches__exp_date__gte=today,
                batches__exp_date__lte=in_30_days,
            ).distinct()

        if out_of_stock in {"1", "true", "yes"}:
            queryset = queryset.filter(quantity_on_hand__lte=0)

        data = InventoryListItemSerializer(queryset, many=True).data
        payload = inventory_dashboard_payload(request.user, queryset)
        return Response(
            {
                "summary": payload.get("summary", {}),
                "items": data,
            },
            status=status.HTTP_200_OK,
        )


class DispenseAPIView(generics.CreateAPIView):
    serializer_class = DispenseCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not _has_inventory_role(request.user):
            raise PermissionDenied("You do not have access to medical stores API.")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dispense = serializer.save()
        output = DispenseSerializer(dispense)
        return Response(output.data, status=status.HTTP_201_CREATED)
