from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Cart, CartItem
from .serializers import CartSerializer, CartItemSerializer

class CartViewSet(viewsets.ViewSet):
    # En un entorno real, usaríamos el user_id del token JWT
    # Por ahora permitiremos pasar el user_id en la query o body para pruebas
    
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
            return Response({"error": "Missing data"}, status=status.HTTP_400_BAD_REQUEST)

        cart = self.get_cart(user_id)
        item, created = CartItem.objects.get_or_create(
            cart=cart, 
            product_id=product_id,
            defaults={'price_at_addition': price, 'product_name': product_name, 'quantity': 0}
        )
        
        item.quantity += quantity
        item.price_at_addition = price # Actualizar al precio más reciente si es necesario
        item.save()

        return Response(CartSerializer(cart).data)

    @action(detail=False, methods=['post'])
    def update_quantity(self, request):
        user_id = request.data.get('user_id')
        item_id = request.data.get('item_id')
        quantity = int(request.data.get('quantity', 1))

        if not all([user_id, item_id]):
            return Response({"error": "Missing data"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            item = CartItem.objects.get(id=item_id, cart__user_id=user_id)
            if quantity > 0:
                item.quantity = quantity
                item.save()
            else:
                item.delete()
        except CartItem.DoesNotExist:
            return Response({"error": "Item not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(CartSerializer(item.cart).data)

    @action(detail=False, methods=['post'])
    def remove_item(self, request):
        user_id = request.data.get('user_id')
        item_id = request.data.get('item_id')

        try:
            item = CartItem.objects.get(id=item_id, cart__user_id=user_id)
            cart = item.cart
            item.delete()
            return Response(CartSerializer(cart).data)
        except CartItem.DoesNotExist:
            return Response({"error": "Item not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['post'])
    def clear(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({"error": "user_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        cart = self.get_cart(user_id)
        cart.items.all().delete()
        return Response(CartSerializer(cart).data)
