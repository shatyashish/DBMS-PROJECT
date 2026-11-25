import mysql.connector

def connect_db():
    try:
        connection = mysql.connector.connect(
            host="localhost",
            port=3306,
            user="root",
            password="Mrsoni2374@",
            database="medcycle"
        )
        return connection

    except mysql.connector.Error as error:
        print("Database Error:", error)
        return None


if __name__ == "__main__":
    db = connect_db()

    if db:
        print("MedCycle Database Connected Successfully!")
        db.close()