from rest_framework import serializers

from .models import BankAccount, LedgerEntry, Merchant, Payout


class PayoutRequestSerializer(serializers.Serializer):
    #validates the incoming payout request body
    amount_paise = serializers.IntegerField(min_value=100)
    bank_account_id = serializers.UUIDField()

    def validate_amount_paise(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

    def validate_bank_account_id(self, value):
        merchant = self.context.get("merchant")
        if not merchant:
            raise serializers.ValidationError("Merchant context required")
        if not BankAccount.objects.filter(id=value, merchant=merchant).exists():
            raise serializers.ValidationError(
                "Bank account not found or does not belong to this merchant"
            )
        return value


class PayoutResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = [
            "id",
            "merchant_id",
            "bank_account_id",
            "amount_paise",
            "status",
            "attempts",
            "created_at",
            "updated_at",
        ]
