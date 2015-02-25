import psycopg2
import sys
import random
import string
class Voucher:
    def __init__(self,phone_number,user_id):
        self.phone_number=phone_number
        self.voucher_number=self.create_voucher_number()
        self.user_id=user_id
    def save(self):
        con=None
        try:
            con= psycopg2.connect(database='vumi_db',user='vumi_login',
            password='asiimwe18',host='localhost',port=5432)
            cursor = con.cursor()
            query = """
            INSERT INTO voucherapp_voucher
                (phone_number,voucher_number,user_id,created_at)
            VALUES
                (%(phone_number)s, %(voucher_number)s,%(user_id)s, now())
            RETURNING id, phone_number, voucher_number,user_id
            """ 
            params = {
            'phone_number': self.phone_number,
            'voucher_number': self.voucher_number
            'user_id':self.user_id
            }
            cursor.execute(query, params)
            con.commit()
        except psycopg2.DatabaseError, e:
            print 'Error %s' % e    
            sys.exit(1)
    
    
        finally:
            if con:
                con.close()
    def get_voucher(self, voucher_number):
        con=None
        try:
            con= psycopg2.connect(database='vumi_db',user='vumi_login',password='asiimwe18',host='localhost',port=5432)
            query ="""
                       SELECT id, phone_number, voucher_number
                       FROM voucherapp_voucher
                       WHERE voucher_number = %(voucher_number)s
            """ 
            params = {'voucher_number': voucher_number}
            cursor = con.cursor()
            cursor.execute(query, params)
            result = cursor.fetchall()
            if len(result) > 0:
                return result[0]
            else:
                return None
        except psycopg2.DatabaseError, e:
            print 'Error %s' % e
            sys.exit(1)
        finally:
            if con:
                con.close()
    def create_voucher_number(self):
            length=7
            while True:
                voucher_number=''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(length))
                if not(self.get_voucher(voucher_number)):
                    break
            return voucher_number
