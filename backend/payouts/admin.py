from django.contrib import admin

from .models import BankAccount, IdempotencyKey, LedgerEntry, Merchant, Payout

#admin registration for all 3 models
@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ["name", "id", "created_at"]
    readonly_fields = ["id", "created_at"]


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ["account_holder_name", "account_number", "ifsc_code", "merchant"]
    readonly_fields = ["id", "created_at"]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ["entry_type", "amount_paise", "merchant", "description", "created_at"]
    list_filter = ["entry_type", "merchant"]
    readonly_fields = ["id", "created_at"]


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ["key", "merchant", "response_status", "created_at"]
    list_filter = ["merchant"]
    readonly_fields = ["created_at"]


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ["id", "merchant", "amount_paise", "status", "attempts", "created_at"]
    list_filter = ["status", "merchant"]
    readonly_fields = ["id", "created_at", "updated_at"]
