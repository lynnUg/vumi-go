# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'Voucher'
        db.create_table(u'voucherapp_voucher', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('voucher_number', self.gf('django.db.models.fields.CharField')(unique=True, max_length=12, blank=True)),
            ('phone_number', self.gf('django.db.models.fields.CharField')(max_length=15)),
            ('created_at', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
        ))
        db.send_create_signal(u'voucherapp', ['Voucher'])


    def backwards(self, orm):
        # Deleting model 'Voucher'
        db.delete_table(u'voucherapp_voucher')


    models = {
        u'voucherapp.voucher': {
            'Meta': {'object_name': 'Voucher'},
            'created_at': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'phone_number': ('django.db.models.fields.CharField', [], {'max_length': '15'}),
            'voucher_number': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '12', 'blank': 'True'})
        }
    }

    complete_apps = ['voucherapp']