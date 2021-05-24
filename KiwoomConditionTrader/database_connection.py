import sqlite3


class StockDatabase(object):
    def __init__(self):
        self.conn = sqlite3.connect("stock_order_history.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_stocks (
        buy_order_number VARCHAR PRIMARY KEY,
        stock_code VARCHAR,
        amount INT,
        price FLOAT,
        sell_order_number text)
        """)

    def add_stock_order_history(self, buy_order_number, stock_code, amount, price):
        self.cursor.execute("INSERT INTO condition_stocks(buy_order_number, stock_code, amount, price) VALUES(?,?,?,?)",
                            (buy_order_number,
                             stock_code,
                             amount,
                             price))
        self.conn.commit()

    def add_sell_order_history(self, buy_order_number, sell_order_number):
        self.cursor.execute("UPDATE condition_stocks SET sell_order_number=? WHERE buy_order_number=?",
                            (sell_order_number,
                             buy_order_number))
        self.conn.commit()

    def remove_stock_order_history(self, sell_order_number):
        self.cursor.execute("DELETE FROM condition_stocks WHERE sell_order_number=?", (sell_order_number,))
        self.conn.commit()

    def get_all_stock_order_history(self):
        self.cursor.execute("""
        SELECT buy_order_number,
               stock_code,
               amount,
               price,
               sell_order_number
        FROM condition_stocks
             """)
        return self.cursor.fetchall()

    def get_stock_order_history(self, buy_order_number):
        self.cursor.execute("""
        SELECT 
        buy_order_number,
        stock_code, 
        amount, 
        price, 
        sell_order_number  
        FROM condition_stocks WHERE buy_order_number=?""", (buy_order_number,))
        return self.cursor.fetchall()


if __name__ == '__main__':
    db = StockDatabase()
    # # db.add_stock_order_history('000000', '068270', 1, 60000)
    print(db.get_all_stock_order_history())
