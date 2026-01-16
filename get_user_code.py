import sqlite3

def get_code():
    try:
        conn = sqlite3.connect('sf6viewer.db')
        c = conn.cursor()
        c.execute("SELECT user_code FROM players LIMIT 1")
        row = c.fetchone()
        if row:
            print(f"Found User Code: {row[0]}")
        else:
            print("No user code found in DB.")
        conn.close()
    except Exception as e:
        print(e)
        
if __name__ == "__main__":
    get_code()
