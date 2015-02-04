from django import forms 

from go.voucherapp.models import Voucher


class VoucherForm(forms.ModelForm):
        phone_number= forms.CharField(required=True)
        voucher_number=forms.CharField(required=False)
	class Meta:
             model= Voucher
             fields=('phone_number','voucher_number')
