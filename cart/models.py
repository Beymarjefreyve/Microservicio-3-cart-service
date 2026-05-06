from django.db import models

class Cart(models.Model):
    user_id = models.IntegerField(unique=True) # ID from auth-service
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for User {self.user_id}"

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_price(self):
        return sum(item.subtotal for item in self.items.all())

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    product_id = models.IntegerField() # ID from catalog-service
    product_name = models.CharField(max_length=255, blank=True)
    price_at_addition = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    @property
    def subtotal(self):
        return self.price_at_addition * self.quantity

    def __str__(self):
        return f"{self.quantity} x Product {self.product_id} in Cart {self.cart.id}"
