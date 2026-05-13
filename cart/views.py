from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Cart, CartItem
from .serializers import CartSerializer, CartItemSerializer
import requests
import os
import logging

logger = logging.getLogger(__name__)

class CartViewSet(viewsets.ViewSet):
    # CENTRALIZAMOS el control de stock a través del catalog-service
    CATALOG_URL = os.getenv('CATALOG_SERVICE_URL', 'http://127.0.0.1:8002/api/products')
    INVENTORY_URL = os.getenv('INVENTORY_SERVICE_URL', 'http://127.0.0.1:8003/api/inventory')

    def get_cart(self, user_id):
        cart, created = Cart.objects.get_or_create(user_id=user_id)
        return cart

    def list(self, request):
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response({"error": "user_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        cart = self.get_cart(user_id)
        serializer = CartSerializer(cart)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def add_item(self, request):
        user_id = request.data.get('user_id')
        product_id = request.data.get('product_id')
        product_name = request.data.get('product_name', '')
        price = request.data.get('price')
        quantity = int(request.data.get('quantity', 1))

        if not all([user_id, product_id, price]):
            return Response({"error": "Faltan datos requeridos"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Reservar stock llamando al CATALOG-SERVICE
        try:
            payload = {"items": [{"product_id": product_id, "quantity": quantity}]}
            cat_resp = requests.post(f"{self.CATALOG_URL}/bulk_reduce_stock/", json=payload, timeout=10)
            
            if cat_resp.status_code != 200:
                return Response(
                    {"error": "No hay suficiente stock disponible."}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            logger.error(f"Error connecting to catalog: {str(e)}")
            return Response(
                {"error": "El servicio de catálogo no está disponible."}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        # 2. Agregar al carrito
        cart = self.get_cart(user_id)
        item, created = CartItem.objects.get_or_create(
            cart=cart, 
            product_id=product_id,
            defaults={'price_at_addition': price, 'product_name': product_name, 'quantity': 0}
        )
        
        item.quantity += quantity
        item.price_at_addition = price
        item.save()

        return Response(CartSerializer(cart).data)

    @action(detail=False, methods=['post'])
    def update_quantity(self, request):
        user_id = request.data.get('user_id')
        item_id = request.data.get('item_id')
        new_quantity = int(request.data.get('quantity', 1))

        if not all([user_id, item_id]):
            return Response({"error": "Faltan datos"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            item = CartItem.objects.get(id=item_id, cart__user_id=user_id)
            old_quantity = item.quantity
            diff = new_quantity - old_quantity

            if diff > 0:
                # Reservar más vía Catalog
                payload = {"items": [{"product_id": item.product_id, "quantity": diff}]}
                cat_resp = requests.post(f"{self.CATALOG_URL}/bulk_reduce_stock/", json=payload, timeout=10)
                if cat_resp.status_code != 200:
                    return Response({"error": "No hay más stock disponible."}, status=status.HTTP_400_BAD_REQUEST)
            elif diff < 0:
                # Liberar stock vía Catalog
                payload = {"items": [{"product_id": item.product_id, "quantity": abs(diff)}]}
                requests.post(f"{self.CATALOG_URL}/bulk_restore_stock/", json=payload, timeout=10)

            if new_quantity > 0:
                item.quantity = new_quantity
                item.save()
            else:
                payload = {"items": [{"product_id": item.product_id, "quantity": old_quantity}]}
                requests.post(f"{self.CATALOG_URL}/bulk_restore_stock/", json=payload, timeout=10)
                item.delete()
        except CartItem.DoesNotExist:
            return Response({"error": "Item no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(CartSerializer(item.cart).data)

    @action(detail=False, methods=['post'])
    def remove_item(self, request):
        user_id = request.data.get('user_id')
        item_id = request.data.get('item_id')
        is_checkout = request.data.get('is_checkout', False)

        try:
            item = CartItem.objects.get(id=item_id, cart__user_id=user_id)
            cart = item.cart
            
            if not is_checkout:
                payload = {"items": [{"product_id": item.product_id, "quantity": item.quantity}]}
                requests.post(f"{self.CATALOG_URL}/bulk_restore_stock/", json=payload, timeout=10)
            
            item.delete()
            return Response(CartSerializer(cart).data)
        except CartItem.DoesNotExist:
            return Response({"error": "Item no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def clear(self, request):
        user_id = request.data.get('user_id')
        is_checkout = request.data.get('is_checkout', False)
        
        if not user_id:
            return Response({"error": "user_id es requerido"}, status=status.HTTP_400_BAD_REQUEST)
        
        cart = self.get_cart(user_id)
        items = cart.items.all()
        
        if not is_checkout:
            restore_items = [{"product_id": i.product_id, "quantity": i.quantity} for i in items]
            if restore_items:
                try:
                    requests.post(f"{self.CATALOG_URL}/bulk_restore_stock/", json={"items": restore_items}, timeout=10)
                except Exception as e:
                    logger.error(f"Failed to restore stock: {str(e)}")
                
        items.delete()
        return Response(CartSerializer(cart).data)

    @action(detail=False, methods=['post'])
    def bulk_remove(self, request):
        user_id = request.data.get('user_id')
        item_ids = request.data.get('item_ids', [])
        is_checkout = request.data.get('is_checkout', False)
        
        if not user_id or not isinstance(item_ids, list):
            return Response({"error": "user_id y lista son requeridos"}, status=status.HTTP_400_BAD_REQUEST)
            
        cart = self.get_cart(user_id)
        items_to_del = CartItem.objects.filter(cart=cart, id__in=item_ids)
        
        if not is_checkout:
            restore_items = [{"product_id": i.product_id, "quantity": i.quantity} for i in items_to_del]
            if restore_items:
                try:
                    requests.post(f"{self.CATALOG_URL}/bulk_restore_stock/", json={"items": restore_items}, timeout=10)
                except Exception as e:
                    logger.error(f"Failed to restore: {str(e)}")
                    
        items_to_del.delete()
        return Response(CartSerializer(cart).data)
