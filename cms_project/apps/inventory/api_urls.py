from django.urls import path

from apps.inventory import api_views

urlpatterns = [
    path("items/", api_views.ItemListCreateAPIView.as_view(), name="api_items"),
    path(
        "items/<int:pk>/", api_views.ItemDetailAPIView.as_view(), name="api_item_detail"
    ),
    path("stock/add/", api_views.StockAddAPIView.as_view(), name="api_stock_add"),
    path("inventory/", api_views.InventoryViewAPIView.as_view(), name="api_inventory"),
    path("dispense/", api_views.DispenseAPIView.as_view(), name="api_dispense"),
]
