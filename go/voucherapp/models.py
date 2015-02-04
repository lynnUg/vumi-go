from django.db import models
import string, random
# Create your models here.
class Voucher(models.Model):
	voucher_number = models.CharField(max_length=12,unique=True,blank=True)
	phone_number  = models.CharField(max_length=15)
	created_at =  models.DateTimeField(auto_now_add=True)
        def create_voucher_number(self):
                length=7
        	return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(length))
 
        #Overriding
        def save(self, *args, **kwargs):
          #check if the row with this hash already exists.
          if not self.voucher_number:
            self.voucher_number = self.create_voucher_number() 
          super(Voucher, self).save(*args, **kwargs)
