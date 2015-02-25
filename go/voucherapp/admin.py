from django.contrib import admin

from go.voucherapp.models import Voucher
from go.voucherapp.forms import VoucherForm

class VoucherAdmin(admin.ModelAdmin):
	list_dislay= ('phone_number','voucher_number','user_id')
        form = VoucherForm
admin.site.register(Voucher,VoucherAdmin)
