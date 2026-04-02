from datetime import timedelta

from django.db.models import Min, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics, permissions, serializers as drf_serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import branch_queryset_for_user
from apps.inventory.models import Batch, Brand, Category, Item, Supplier
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


# ── Catalogue search autocomplete ──────────────────────────────────────
class CatalogueSearchAPIView(APIView):
    """Return matching items for autocomplete (by name, barcode, SKU, generic)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _has_inventory_role(request.user):
            raise PermissionDenied()

        q = (request.GET.get("q") or "").strip()
        store = (request.GET.get("store") or "").strip()
        if len(q) < 1:
            return Response([], status=status.HTTP_200_OK)

        queryset = branch_queryset_for_user(
            request.user,
            Item.objects.filter(is_active=True, is_department_stock=False)
            .select_related("category", "brand")
            .order_by("item_name"),
        )
        queryset = queryset.filter(
            Q(item_name__icontains=q)
            | Q(generic_name__icontains=q)
            | Q(barcode__icontains=q)
            | Q(sku__icontains=q)
        )
        if store and store in dict(Item.STORE_DEPARTMENT_CHOICES):
            queryset = queryset.filter(store_department=store)

        items = queryset[:20]
        data = [
            {
                "id": item.pk,
                "item_name": item.item_name,
                "generic_name": item.generic_name,
                "sku": item.sku,
                "barcode": item.barcode,
                "item_type": item.item_type,
                "category_id": item.category_id,
                "category_name": item.category.name if item.category else "",
                "brand_id": item.brand_id,
                "brand_name": item.brand.name if item.brand else "",
                "dosage_form": item.dosage_form,
                "strength": item.strength,
                "unit_of_measure": item.unit_of_measure,
                "pack_size": item.pack_size,
                "default_pack_size_units": item.default_pack_size_units,
                "store_department": item.store_department,
                "control_status": item.control_status,
                "storage_class": item.storage_class,
                "reorder_level": item.reorder_level,
                "quantity_on_hand": item.quantity_on_hand,
            }
            for item in items
        ]
        return Response(data, status=status.HTTP_200_OK)


# ── Quick catalogue item creation ──────────────────────────────────────
class CatalogueItemCreateSerializer(drf_serializers.Serializer):
    item_name = drf_serializers.CharField(max_length=255)
    sku = drf_serializers.CharField(max_length=60, required=False, allow_blank=True)
    generic_name = drf_serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    item_type = drf_serializers.ChoiceField(
        choices=Item.ITEM_TYPE_CHOICES, default="medicine"
    )
    category_id = drf_serializers.IntegerField(required=False, allow_null=True)
    new_category_name = drf_serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    brand_id = drf_serializers.IntegerField(required=False, allow_null=True)
    new_brand_name = drf_serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    dosage_form = drf_serializers.ChoiceField(
        choices=Item.DOSAGE_FORM_CHOICES, default="other"
    )
    strength = drf_serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    unit_of_measure = drf_serializers.CharField(max_length=60)
    pack_size = drf_serializers.CharField(
        max_length=60, required=False, allow_blank=True
    )
    default_pack_size_units = drf_serializers.IntegerField(min_value=1, default=1)
    barcode = drf_serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    store_department = drf_serializers.ChoiceField(
        choices=Item.STORE_DEPARTMENT_CHOICES, default="pharmacy"
    )
    control_status = drf_serializers.ChoiceField(
        choices=Item.CONTROL_STATUS_CHOICES, default="none", required=False
    )
    storage_class = drf_serializers.ChoiceField(
        choices=Item.STORAGE_CLASS_CHOICES, default="room_temp", required=False
    )
    batch_tracking = drf_serializers.BooleanField(default=True, required=False)

    def validate(self, data):
        if (
            not data.get("category_id")
            and not (data.get("new_category_name") or "").strip()
        ):
            raise drf_serializers.ValidationError(
                {"category_id": "Select a category or provide a new category name."}
            )
        if not data.get("brand_id") and not (data.get("new_brand_name") or "").strip():
            raise drf_serializers.ValidationError(
                {"brand_id": "Select a brand or provide a new brand name."}
            )
        return data


class CatalogueItemCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _has_inventory_role(request.user):
            raise PermissionDenied()

        serializer = CatalogueItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        branch = request.user.branch

        # Resolve category
        category = None
        if data.get("category_id"):
            category = Category.objects.filter(
                branch=branch, pk=data["category_id"]
            ).first()
        if not category:
            category, _ = Category.objects.get_or_create(
                branch=branch, name=(data.get("new_category_name") or "General").strip()
            )

        # Resolve brand
        brand_obj = None
        if data.get("brand_id"):
            brand_obj = Brand.objects.filter(branch=branch, pk=data["brand_id"]).first()
        if not brand_obj:
            brand_obj, _ = Brand.objects.get_or_create(
                branch=branch, name=(data.get("new_brand_name") or "Generic").strip()
            )

        item = Item.objects.create(
            branch=branch,
            item_name=data["item_name"],
            sku=data.get("sku", ""),
            generic_name=data.get("generic_name", ""),
            item_type=data.get("item_type", "medicine"),
            category=category,
            brand=brand_obj,
            dosage_form=data.get("dosage_form", "other"),
            strength=data.get("strength", ""),
            unit_of_measure=data["unit_of_measure"],
            pack_size=data.get("pack_size", ""),
            default_pack_size_units=data.get("default_pack_size_units", 1),
            barcode=data.get("barcode", ""),
            store_department=data.get("store_department", "pharmacy"),
            control_status=data.get("control_status", "none"),
            storage_class=data.get("storage_class", "room_temp"),
            batch_tracking=data.get("batch_tracking", True),
            is_active=True,
        )

        return Response(
            {
                "id": item.pk,
                "item_name": item.item_name,
                "sku": item.sku,
                "generic_name": item.generic_name,
                "item_type": item.item_type,
                "category_id": item.category_id,
                "category_name": item.category.name,
                "brand_id": item.brand_id,
                "brand_name": brand_obj.name,
                "dosage_form": item.dosage_form,
                "strength": item.strength,
                "unit_of_measure": item.unit_of_measure,
                "pack_size": item.pack_size,
                "default_pack_size_units": item.default_pack_size_units,
                "barcode": item.barcode,
                "store_department": item.store_department,
                "control_status": item.control_status,
                "storage_class": item.storage_class,
                "quantity_on_hand": 0,
            },
            status=status.HTTP_201_CREATED,
        )


# ── Lookup helpers for dropdowns ───────────────────────────────────────
class CatBrandSupplierListAPIView(APIView):
    """Return categories, brands, and suppliers for the current branch."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _has_inventory_role(request.user):
            raise PermissionDenied()

        branch = request.user.branch
        categories = list(
            Category.objects.filter(branch=branch).order_by("name").values("id", "name")
        )
        brands = list(
            Brand.objects.filter(branch=branch)
            .order_by("name")
            .values("id", "name", "manufacturer")
        )
        suppliers = list(
            Supplier.objects.filter(branch=branch)
            .order_by("name")
            .values("id", "name", "contact")
        )
        return Response(
            {"categories": categories, "brands": brands, "suppliers": suppliers},
            status=status.HTTP_200_OK,
        )
