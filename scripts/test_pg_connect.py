import psycopg2

URL = 'postgresql://shopsquire:shopsquire@localhost:5433/shopsquire_test'

try:
    conn = psycopg2.connect(URL)
    conn.close()
    print('ok')
except Exception as e:
    print('error:', e)
