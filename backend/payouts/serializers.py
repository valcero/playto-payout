from rest_framework import serializers

from .models import BankAccount, LedgerEntry, Merchant, Payout


class MerchantSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = ["id", "name", "balance", "created_at"]

    def get_balance(self, obj):
        return obj.get_balance()


class MerchantListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ["id", "name", "created_at"]


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ["id", "account_number", "ifsc_code", "account_holder_name", "created_at"]


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ["id", "entry_type", "amount_paise", "description", "reference_id", "created_at"]


class PayoutRequestSerializer(serializers.Serializer):
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
