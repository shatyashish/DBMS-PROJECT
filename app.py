from flask import Flask, render_template, request, redirect, url_for, flash, session
from database import connect_db
from datetime import date
from functools import wraps

app = Flask(__name__)
app.secret_key = "a1e9d5ad6798a40c1e2679323921032515bb9e7866d3982eff8d9eaeb544b4fe"


# ROLE-BASED ACCESS CONTROL
def role_required(*allowed_roles):
    """Require login and an allowed role. Admin can access every module."""
    def decorator(view_function):
        @wraps(view_function)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "error")
                return redirect(url_for("home"))
            if session.get("role") != "Admin" and session.get("role") not in allowed_roles:
                flash("You are not authorized to access this page.", "error")
                return redirect(url_for("dashboard"))
            return view_function(*args, **kwargs)
        return wrapper
    return decorator


# HOME PAGE
@app.route("/")
def home():
    return render_template("index.html")


# LOGIN (plain-text password comparison for the current project database)
@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Please enter both username and password.", "error")
        return redirect(url_for("home"))

    db = connect_db()
    if db is None:
        flash("Database connection failed.", "error")
        return redirect(url_for("home"))

    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT User_ID, Name, Role, Password_Hash
            FROM Users_Auth
            WHERE Name = %s
        """, (username,))
        user = cursor.fetchone()

        if user and user["Password_Hash"] == password:
            session["user_id"] = user["User_ID"]
            session["user_name"] = user["Name"]
            session["role"] = user["Role"]
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")
        return redirect(url_for("home"))

    except Exception as e:
        print("Login Error:", e)
        flash("Unable to login. Please try again.", "error")
        return redirect(url_for("home"))

    finally:
        cursor.close()
        db.close()


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))



# DASHBOARD
@app.route("/dashboard")
@role_required("Doctor", "Pharmacist")
def dashboard():

    db = connect_db()

    total_medicines = 0
    total_patients = 0
    total_prescriptions = 0
    low_stock = 0
    expired_medicines = 0
    near_expiry_medicines = 0
    recent_inventory = []

    if db:
        cursor = db.cursor(dictionary=True)

        try:
            # Count active (non-expired) batches
            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM Batches b
                INNER JOIN Medicines m ON m.Medicine_ID = b.Medicine_ID
                WHERE b.Expiry_Date >= CURDATE()
                  AND b.Is_Removed = FALSE
                  AND m.Is_Removed = FALSE
            """)
            total_medicines = cursor.fetchone()["total"]

            # Count patients
            cursor.execute("""
                SELECT COUNT(*) AS total FROM Patients
            """)
            total_patients = cursor.fetchone()["total"]

            # Count prescriptions
            cursor.execute("""
                SELECT COUNT(*) AS total FROM Prescriptions
            """)
            total_prescriptions = cursor.fetchone()["total"]

            # Count low stock batches (active only)
            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM Batches b
                INNER JOIN Medicines m ON m.Medicine_ID = b.Medicine_ID
                WHERE b.Quantity < 50
                  AND b.Quantity > 0
                  AND b.Expiry_Date >= CURDATE()
                  AND b.Is_Removed = FALSE
                  AND m.Is_Removed = FALSE
            """)
            low_stock = cursor.fetchone()["total"]

            # Count expired batches
            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM Batches b
                INNER JOIN Medicines m ON m.Medicine_ID = b.Medicine_ID
                WHERE b.Expiry_Date < CURDATE()
                  AND b.Is_Removed = FALSE
                  AND m.Is_Removed = FALSE
            """)
            expired_medicines = cursor.fetchone()["total"]

            # Count active batches expiring within the next 30 days
            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM Batches b
                INNER JOIN Medicines m ON m.Medicine_ID = b.Medicine_ID
                WHERE b.Expiry_Date >= CURDATE()
                  AND b.Expiry_Date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
                  AND b.Quantity > 0
                  AND b.Is_Removed = FALSE
                  AND m.Is_Removed = FALSE
            """)
            near_expiry_medicines = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT
                    m.Generic_Name,
                    b.Batch_ID,
                    b.Quantity,
                    b.Expiry_Date,
                    CASE
                        WHEN b.Expiry_Date < CURDATE() THEN 'Expired'
                        WHEN b.Quantity = 0 THEN 'Out of Stock'
                        WHEN b.Quantity < 50 THEN 'Low Stock'
                        ELSE 'Available'
                    END AS Inventory_Status
                FROM Batches b
                JOIN Medicines m ON m.Medicine_ID = b.Medicine_ID
                WHERE b.Is_Removed = FALSE
                  AND m.Is_Removed = FALSE
                ORDER BY b.Batch_ID DESC
                LIMIT 5
            """)
            recent_inventory = cursor.fetchall()

        finally:
            cursor.close()
            db.close()

    return render_template(
        "dashboard.html",
        total_medicines=total_medicines,
        total_patients=total_patients,
        total_prescriptions=total_prescriptions,
        low_stock=low_stock,
        expired_medicines=expired_medicines,
        near_expiry_medicines=near_expiry_medicines,
        recent_inventory=recent_inventory
    )


# MEDICINE INVENTORY - ACTIVE BATCHES ONLY
@app.route("/medicines")
@role_required("Pharmacist")
def medicines():

    db = connect_db()
    medicine_list = []
    search = request.args.get("search", "").strip()

    if db:
        cursor = db.cursor(dictionary=True)

        try:
            query = """
                SELECT
                    m.Medicine_ID,
                    m.Generic_Name,
                    m.Brand_Name,
                    m.Category,
                    m.Unit_Price,
                    b.Batch_ID,
                    b.Quantity,
                    b.Manufacture_Date,
                    b.Expiry_Date,
                    b.Storage_Location
                FROM Medicines m
                LEFT JOIN Batches b
                    ON m.Medicine_ID = b.Medicine_ID
                    AND b.Is_Removed = FALSE
                WHERE m.Is_Removed = FALSE
                  AND (m.Generic_Name LIKE %s
                       OR m.Brand_Name LIKE %s)
                ORDER BY b.Expiry_Date ASC
            """

            cursor.execute(
                query,
                (f"%{search}%", f"%{search}%")
            )

            medicine_list = cursor.fetchall()

        finally:
            cursor.close()
            db.close()

    return render_template(
        "medicines.html",
        medicines=medicine_list,
        search=search,
        today=date.today()
    )


# EXPIRED AND NEAR-EXPIRY MEDICINES
@app.route("/expiry_tracking")
@role_required("Pharmacist")
def expiry_tracking():
    db = connect_db()
    expired_list = []
    near_expiry_list = []
    search = request.args.get("search", "").strip()

    if db is None:
        return "Database connection failed.", 500

    cursor = db.cursor(dictionary=True)
    try:
        search_pattern = f"%{search}%"

        cursor.execute("""
            SELECT m.Medicine_ID, m.Generic_Name, m.Brand_Name, m.Category,
                   m.Unit_Price, b.Batch_ID, b.Quantity, b.Manufacture_Date,
                   b.Expiry_Date, b.Storage_Location
            FROM Medicines m
            INNER JOIN Batches b ON m.Medicine_ID = b.Medicine_ID
            WHERE b.Expiry_Date < CURDATE()
              AND b.Is_Removed = FALSE AND m.Is_Removed = FALSE
              AND (m.Generic_Name LIKE %s OR m.Brand_Name LIKE %s)
            ORDER BY b.Expiry_Date ASC
        """, (search_pattern, search_pattern))
        expired_list = cursor.fetchall()

        cursor.execute("""
            SELECT m.Medicine_ID, m.Generic_Name, m.Brand_Name, m.Category,
                   m.Unit_Price, b.Batch_ID, b.Quantity, b.Manufacture_Date,
                   b.Expiry_Date, b.Storage_Location
            FROM Medicines m
            INNER JOIN Batches b ON m.Medicine_ID = b.Medicine_ID
            WHERE b.Expiry_Date >= CURDATE()
              AND b.Expiry_Date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
              AND b.Quantity > 0
              AND b.Is_Removed = FALSE AND m.Is_Removed = FALSE
              AND (m.Generic_Name LIKE %s OR m.Brand_Name LIKE %s)
            ORDER BY b.Expiry_Date ASC
        """, (search_pattern, search_pattern))
        near_expiry_list = cursor.fetchall()
    finally:
        cursor.close()
        db.close()

    return render_template(
        "expired_medicines.html",
        medicines=expired_list,
        near_expiry_medicines=near_expiry_list,
        search=search
    )


# ADD MEDICINE TO MYSQL DATABASE
@app.route("/add_medicine", methods=["POST"])
@role_required("Pharmacist")
def add_medicine():

    generic_name = request.form.get("generic_name", "").strip()
    brand_name = request.form.get("brand_name", "").strip()
    category = request.form.get("category", "").strip()
    unit_price = request.form.get("unit_price", "").strip()

    quantity = request.form.get("quantity", "").strip()
    manufacture_date = request.form.get("manufacture_date", "")
    expiry_date = request.form.get("expiry_date", "")
    storage_location = request.form.get("storage_location", "").strip()

    if not generic_name or not unit_price or not quantity:
        return "Please fill all required fields.", 400

    try:
        unit_price = float(unit_price)
        quantity = int(quantity)

        if unit_price < 0 or quantity <= 0:
            return "Invalid price or quantity.", 400

        if not manufacture_date or not expiry_date:
            return "Please enter both dates.", 400

        if expiry_date <= manufacture_date:
            return "Expiry date must be after manufacture date.", 400

        # Prevent adding already-expired batches
        from datetime import date
        if date.fromisoformat(expiry_date) < date.today():
            return "Cannot add an already-expired medicine batch.", 400

        db = connect_db()

        if db is None:
            return "Database connection failed.", 500

        cursor = db.cursor()

        try:
            cursor.execute("""
                INSERT INTO Medicines
                (Generic_Name, Brand_Name, Category, Unit_Price)
                VALUES (%s, %s, %s, %s)
            """, (
                generic_name,
                brand_name or None,
                category or None,
                unit_price
            ))

            medicine_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO Batches
                (Medicine_ID, Quantity, Manufacture_Date,
                 Expiry_Date, Storage_Location)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                medicine_id,
                quantity,
                manufacture_date,
                expiry_date,
                storage_location or None
            ))

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            cursor.close()
            db.close()

        return redirect(url_for("medicines", added=1))

    except ValueError:
        return "Please enter valid price, quantity, and dates.", 400

    except Exception as e:
        print("Add Medicine Error:", e)
        return "Unable to save medicine. Check terminal.", 500


# EDIT MEDICINE ROUTE
@app.route("/edit_medicine", methods=["POST"])
@role_required("Pharmacist")
def edit_medicine():

    medicine_id = request.form.get("medicine_id")
    batch_id = request.form.get("batch_id")

    generic_name = request.form.get("generic_name", "").strip()
    brand_name = request.form.get("brand_name", "").strip()
    category = request.form.get("category", "").strip()

    try:
        unit_price = float(request.form.get("unit_price"))
        quantity = int(request.form.get("quantity"))

        manufacture_date = request.form.get("manufacture_date")
        expiry_date = request.form.get("expiry_date")
        storage_location = request.form.get("storage_location", "").strip()

        if not medicine_id or not batch_id or not generic_name:
            return "Missing required medicine details.", 400

        if unit_price < 0 or quantity < 0:
            return "Invalid price or quantity.", 400

        if not manufacture_date or not expiry_date:
            return "Please enter both dates.", 400

        if expiry_date <= manufacture_date:
            return "Expiry date must be after manufacture date.", 400

        if date.fromisoformat(expiry_date) < date.today():
            return "Cannot set a batch expiry date in the past.", 400

        db = connect_db()

        if db is None:
            return "Database connection failed.", 500

        cursor = db.cursor()

        try:
            cursor.execute("""
                SELECT Batch_ID
                FROM Batches
                WHERE Batch_ID = %s
                  AND Medicine_ID = %s
                  AND Is_Removed = FALSE
                  AND Expiry_Date >= CURDATE()
            """, (batch_id, medicine_id))

            existing_batch = cursor.fetchone()

            if existing_batch is None:
                raise Exception("Batch ID does not match this medicine.")

            cursor.execute("""
                UPDATE Medicines
                SET Generic_Name = %s,
                    Brand_Name = %s,
                    Category = %s,
                    Unit_Price = %s
                WHERE Medicine_ID = %s
            """, (
                generic_name,
                brand_name or None,
                category or None,
                unit_price,
                medicine_id
            ))

            cursor.execute("""
                UPDATE Batches
                SET Quantity = %s,
                    Manufacture_Date = %s,
                    Expiry_Date = %s,
                    Storage_Location = %s
                WHERE Batch_ID = %s
                AND Medicine_ID = %s
            """, (
                quantity,
                manufacture_date,
                expiry_date,
                storage_location or None,
                batch_id,
                medicine_id
            ))

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            cursor.close()
            db.close()

        return redirect(url_for("medicines", updated=1))

    except ValueError:
        return "Please enter valid price and quantity.", 400

    except Exception as e:
        print("Edit Medicine Error:", e)
        return "Unable to update medicine. Check terminal.", 500



# REMOVE MEDICINE FROM ACTIVE INVENTORY (SOFT REMOVE)
# The medicine row and its historical batch/prescription records are preserved.
@app.route("/remove_medicine", methods=["POST"])
@role_required("Pharmacist")
def remove_medicine():
    medicine_id = request.form.get("medicine_id", "").strip()

    if not medicine_id.isdigit():
        return "Please select a valid medicine.", 400

    db = connect_db()
    if db is None:
        return "Database connection failed.", 500

    cursor = db.cursor()

    try:
        # Lock the medicine row to avoid concurrent changes during validation.
        cursor.execute("""
            SELECT Medicine_ID, Is_Removed
            FROM Medicines
            WHERE Medicine_ID = %s
            FOR UPDATE
        """, (medicine_id,))
        medicine = cursor.fetchone()

        if medicine is None:
            db.rollback()
            return "Medicine not found.", 404

        if medicine[1]:
            db.rollback()
            return redirect(url_for("medicines", removed=1))

        # Do not archive a medicine that still has any stock in an active batch.
        cursor.execute("""
            SELECT COUNT(*)
            FROM Batches
            WHERE Medicine_ID = %s
              AND Is_Removed = FALSE
              AND Quantity > 0
        """, (medicine_id,))
        active_stock_count = cursor.fetchone()[0]

        if active_stock_count:
            db.rollback()
            return (
                "This medicine still has stock in one or more active batches. "
                "Remove eligible expired batches or dispense/use the remaining "
                "stock before removing the medicine.",
                409
            )

        # Preserve all prescription and dispensing history.
        cursor.execute("""
            SELECT COUNT(*)
            FROM Prescription_Items
            WHERE Medicine_ID = %s
        """, (medicine_id,))
        prescription_count = cursor.fetchone()[0]

        if prescription_count:
            db.rollback()
            return (
                "This medicine is linked to prescription history and cannot "
                "be removed from the active inventory.",
                409
            )

        cursor.execute("""
            UPDATE Medicines
            SET Is_Removed = TRUE
            WHERE Medicine_ID = %s
              AND Is_Removed = FALSE
        """, (medicine_id,))

        if cursor.rowcount == 0:
            db.rollback()
            return "Medicine was not removed. Please refresh and try again.", 409

        db.commit()
        return redirect(url_for("medicines", removed=1))

    except Exception as e:
        db.rollback()
        print("Remove Medicine Error:", e)
        return "Unable to remove medicine. Check the terminal.", 500

    finally:
        cursor.close()
        db.close()


# ==========================================
# PATIENT MANAGEMENT
# ==========================================

# DISPLAY AND SEARCH PATIENTS
@app.route("/patients")
@role_required("Doctor", "Pharmacist")
def patients():

    db = connect_db()
    patient_list = []
    search = request.args.get("search", "").strip()

    if db:
        cursor = db.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT Patient_ID, Name, Age, Gender, Contact
                FROM Patients
                WHERE Name LIKE %s
                ORDER BY Patient_ID DESC
            """, (f"%{search}%",))

            patient_list = cursor.fetchall()

        finally:
            cursor.close()
            db.close()

    return render_template(
        "patients.html",
        patients=patient_list,
        search=search
    )


# ADD NEW PATIENT
@app.route("/add_patient", methods=["POST"])
@role_required("Doctor", "Pharmacist")
def add_patient():

    name = request.form.get("name", "").strip()
    age = request.form.get("age", "").strip()
    gender = request.form.get("gender", "").strip()
    contact = request.form.get("contact", "").strip()

    if not name:
        return "Patient name is required.", 400

    try:
        age_value = int(age) if age else None

        if age_value is not None and not 0 <= age_value <= 130:
            return "Please enter a valid age.", 400

        if len(contact) > 15:
            return "Contact number must not exceed 15 characters.", 400

        if gender and gender not in ["Male", "Female", "Other"]:
            return "Invalid gender selection.", 400

        db = connect_db()

        if db is None:
            return "Database connection failed.", 500

        cursor = db.cursor()

        try:
            cursor.execute("""
                INSERT INTO Patients
                (Name, Age, Gender, Contact)
                VALUES (%s, %s, %s, %s)
            """, (
                name,
                age_value,
                gender or None,
                contact or None
            ))

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            cursor.close()
            db.close()

        return redirect(url_for("patients", added=1))

    except ValueError:
        return "Please enter a valid age.", 400

    except Exception as e:
        print("Add Patient Error:", e)
        return "Unable to save patient. Check terminal.", 500


# ==========================================
# EDIT PATIENT
# ==========================================

@app.route("/edit_patient", methods=["POST"])
@role_required("Doctor", "Pharmacist")
def edit_patient():

    patient_id = request.form.get("patient_id")
    name = request.form.get("name", "").strip()
    age = request.form.get("age", "").strip()
    gender = request.form.get("gender", "").strip()
    contact = request.form.get("contact", "").strip()

    if not patient_id or not name:
        return "Patient ID and name are required.", 400

    try:
        age_value = int(age) if age else None

        if age_value is not None and not 0 <= age_value <= 130:
            return "Invalid age.", 400

        if gender and gender not in ["Male", "Female", "Other"]:
            return "Invalid gender.", 400

        if len(contact) > 15:
            return "Contact number must not exceed 15 characters.", 400

        db = connect_db()

        if db is None:
            return "Database connection failed.", 500

        cursor = db.cursor()

        try:
            cursor.execute("""
                UPDATE Patients
                SET Name = %s,
                    Age = %s,
                    Gender = %s,
                    Contact = %s
                WHERE Patient_ID = %s
            """, (
                name,
                age_value,
                gender or None,
                contact or None,
                patient_id
            ))

            if cursor.rowcount == 0:
                return "Patient not found.", 404

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            cursor.close()
            db.close()

        return redirect(url_for("patients", updated=1))

    except ValueError:
        return "Please enter a valid age.", 400

    except Exception as e:
        print("Edit Patient Error:", e)
        return "Unable to update patient.", 500


# ==========================================
# DELETE PATIENT
# ==========================================

@app.route("/delete_patient/<int:patient_id>", methods=["POST"])
@role_required("Doctor", "Pharmacist")
def delete_patient(patient_id):

    db = connect_db()

    if db is None:
        return "Database connection failed.", 500

    cursor = db.cursor()

    try:
        cursor.execute("""
            DELETE FROM Patients
            WHERE Patient_ID = %s
        """, (patient_id,))

        if cursor.rowcount == 0:
            return "Patient not found.", 404

        db.commit()

        return redirect(url_for("patients", deleted=1))

    except Exception as e:
        db.rollback()
        print("Delete Patient Error:", e)
        return (
            "Patient cannot be deleted. "
            "The patient may have linked prescriptions.",
            409
        )

    finally:
        cursor.close()
        db.close()


# ==========================================
# PRESCRIPTION MANAGEMENT
# ==========================================

# DISPLAY PRESCRIPTIONS AND LOAD FORM OPTIONS
@app.route("/prescriptions")
@role_required("Doctor")
def prescriptions():

    db = connect_db()

    prescription_list = []
    patient_list = []
    doctor_list = []
    medicine_list = []

    search = request.args.get("search", "").strip()

    if db is None:
        return "Database connection failed.", 500

    cursor = db.cursor(dictionary=True)

    try:
        # LOAD PATIENTS
        cursor.execute("""
            SELECT Patient_ID, Name
            FROM Patients
            ORDER BY Name
        """)
        patient_list = cursor.fetchall()

        # LOAD DOCTORS ONLY
        cursor.execute("""
            SELECT User_ID, Name
            FROM Users_Auth
            WHERE Role = 'Doctor'
            ORDER BY Name
        """)
        doctor_list = cursor.fetchall()

        # LOAD MEDICINES
        cursor.execute("""
            SELECT Medicine_ID, Generic_Name, Brand_Name
            FROM Medicines
            WHERE Is_Removed = FALSE
            ORDER BY Generic_Name
        """)
        medicine_list = cursor.fetchall()

        # LOAD PRESCRIPTIONS
        cursor.execute("""
            SELECT
                p.Prescription_ID,
                p.Patient_ID,
                p.Doctor_ID,
                p.Date_Issued,
                p.Status,
                pa.Name AS Patient_Name,
                u.Name AS Doctor_Name
            FROM Prescriptions p
            INNER JOIN Patients pa
                ON p.Patient_ID = pa.Patient_ID
            INNER JOIN Users_Auth u
                ON p.Doctor_ID = u.User_ID
            WHERE pa.Name LIKE %s
            ORDER BY p.Prescription_ID DESC
        """, (f"%{search}%",))

        prescription_list = cursor.fetchall()

        # LOAD MEDICINE ITEMS FOR EACH PRESCRIPTION
        for prescription in prescription_list:

            cursor.execute("""
                SELECT
                    pi.Item_ID,
                    pi.Medicine_ID,
                    pi.Prescribed_Quantity,
                    m.Generic_Name,
                    m.Brand_Name
                FROM Prescription_Items pi
                INNER JOIN Medicines m
                    ON pi.Medicine_ID = m.Medicine_ID
                WHERE pi.Prescription_ID = %s
                ORDER BY pi.Item_ID
            """, (prescription["Prescription_ID"],))

            prescription["items"] = cursor.fetchall()

    finally:
        cursor.close()
        db.close()

    return render_template(
        "prescriptions.html",
        prescriptions=prescription_list,
        patients=patient_list,
        doctors=doctor_list,
        medicines=medicine_list,
        search=search,
        today=date.today().isoformat()
    )


# CREATE PRESCRIPTION WITH MULTIPLE MEDICINES
@app.route("/add_prescription", methods=["POST"])
@role_required("Doctor")
def add_prescription():

    patient_id = request.form.get("patient_id", "").strip()
    doctor_id = request.form.get("doctor_id", "").strip()
    date_issued = request.form.get("date_issued", "").strip()

    medicine_ids = request.form.getlist("medicine_id[]")
    quantities = request.form.getlist("quantity[]")

    if not patient_id or not doctor_id or not date_issued:
        return "Please select a patient, doctor and issue date.", 400

    if not medicine_ids or len(medicine_ids) != len(quantities):
        return "Please add at least one medicine with its quantity.", 400

    try:
        patient_id = int(patient_id)
        doctor_id = int(doctor_id)

        items = []

        for medicine_id, quantity in zip(medicine_ids, quantities):

            medicine_id = int(medicine_id)
            quantity = int(quantity)

            if quantity <= 0:
                return "Prescribed quantities must be greater than zero.", 400

            items.append((medicine_id, quantity))

        if len(set(item[0] for item in items)) != len(items):
            return "Please select each medicine only once.", 400

        db = connect_db()

        if db is None:
            return "Database connection failed.", 500

        cursor = db.cursor()

        try:
            # VERIFY PATIENT
            cursor.execute("""
                SELECT Patient_ID
                FROM Patients
                WHERE Patient_ID = %s
            """, (patient_id,))

            if cursor.fetchone() is None:
                raise ValueError("Selected patient does not exist.")

            # VERIFY DOCTOR ROLE
            cursor.execute("""
                SELECT User_ID
                FROM Users_Auth
                WHERE User_ID = %s
                AND Role = 'Doctor'
            """, (doctor_id,))

            if cursor.fetchone() is None:
                raise ValueError("Selected user is not a valid doctor.")

            # VERIFY MEDICINES
            for medicine_id, quantity in items:

                cursor.execute("""
                    SELECT Medicine_ID
                    FROM Medicines
                    WHERE Medicine_ID = %s
                      AND Is_Removed = FALSE
                """, (medicine_id,))

                if cursor.fetchone() is None:
                    raise ValueError("A selected medicine does not exist.")

            # CREATE PRESCRIPTION
            cursor.execute("""
                INSERT INTO Prescriptions
                (Patient_ID, Doctor_ID, Date_Issued, Status)
                VALUES (%s, %s, %s, 'Pending')
            """, (patient_id, doctor_id, date_issued))

            prescription_id = cursor.lastrowid

            # ADD PRESCRIPTION ITEMS
            for medicine_id, quantity in items:

                cursor.execute("""
                    INSERT INTO Prescription_Items
                    (Prescription_ID, Medicine_ID, Prescribed_Quantity)
                    VALUES (%s, %s, %s)
                """, (
                    prescription_id,
                    medicine_id,
                    quantity
                ))

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            cursor.close()
            db.close()

        return redirect(url_for("prescriptions", added=1))

    except ValueError as e:
        return str(e), 400

    except Exception as e:
        print("Add Prescription Error:", e)
        return "Unable to save prescription. Check terminal.", 500




# ==========================================
# EDIT PRESCRIPTION
# ==========================================

@app.route("/edit_prescription", methods=["POST"])
@role_required("Doctor")
def edit_prescription():

    prescription_id = request.form.get("prescription_id", "").strip()
    patient_id = request.form.get("patient_id", "").strip()
    doctor_id = request.form.get("doctor_id", "").strip()
    date_issued = request.form.get("date_issued", "").strip()

    medicine_ids = request.form.getlist("medicine_id[]")
    quantities = request.form.getlist("quantity[]")

    if not prescription_id or not patient_id or not doctor_id or not date_issued:
        return "Please complete all required prescription fields.", 400

    if not medicine_ids or len(medicine_ids) != len(quantities):
        return "Add at least one medicine and its quantity.", 400

    try:
        prescription_id = int(prescription_id)
        patient_id = int(patient_id)
        doctor_id = int(doctor_id)

        items = []
        for medicine_id, quantity in zip(medicine_ids, quantities):
            medicine_id = int(medicine_id)
            quantity = int(quantity)

            if quantity <= 0:
                return "Prescribed quantities must be greater than zero.", 400

            items.append((medicine_id, quantity))

        if len({medicine_id for medicine_id, _ in items}) != len(items):
            return "Please select each medicine only once.", 400

        db = connect_db()
        if db is None:
            return "Database connection failed.", 500

        cursor = db.cursor()

        try:
            # Lock the prescription while checking and updating it.
            cursor.execute("""
                SELECT Prescription_ID
                FROM Prescriptions
                WHERE Prescription_ID = %s
                FOR UPDATE
            """, (prescription_id,))

            if cursor.fetchone() is None:
                raise ValueError("Prescription not found.")

            # A prescription with dispensing history must not be edited.
            cursor.execute("""
                SELECT Record_ID
                FROM Dispensary_Records
                WHERE Prescription_ID = %s
                LIMIT 1
            """, (prescription_id,))

            if cursor.fetchone() is not None:
                raise ValueError(
                    "This prescription already has dispensing records "
                    "and cannot be edited."
                )

            cursor.execute("""
                SELECT Patient_ID
                FROM Patients
                WHERE Patient_ID = %s
            """, (patient_id,))

            if cursor.fetchone() is None:
                raise ValueError("Selected patient does not exist.")

            cursor.execute("""
                SELECT User_ID
                FROM Users_Auth
                WHERE User_ID = %s AND Role = 'Doctor'
            """, (doctor_id,))

            if cursor.fetchone() is None:
                raise ValueError("Selected user is not a valid doctor.")

            for medicine_id, quantity in items:
                cursor.execute("""
                    SELECT Medicine_ID
                    FROM Medicines
                    WHERE Medicine_ID = %s
                      AND Is_Removed = FALSE
                """, (medicine_id,))

                if cursor.fetchone() is None:
                    raise ValueError(
                        f"Medicine ID {medicine_id} does not exist."
                    )

            cursor.execute("""
                UPDATE Prescriptions
                SET Patient_ID = %s,
                    Doctor_ID = %s,
                    Date_Issued = %s
                WHERE Prescription_ID = %s
            """, (patient_id, doctor_id, date_issued, prescription_id))

            # Replace the prescription's medicine items in the same transaction.
            cursor.execute("""
                DELETE FROM Prescription_Items
                WHERE Prescription_ID = %s
            """, (prescription_id,))

            for medicine_id, quantity in items:
                cursor.execute("""
                    INSERT INTO Prescription_Items
                    (Prescription_ID, Medicine_ID, Prescribed_Quantity)
                    VALUES (%s, %s, %s)
                """, (prescription_id, medicine_id, quantity))

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            cursor.close()
            db.close()

        return redirect(url_for("prescriptions", updated=1))

    except ValueError as e:
        return str(e), 400

    except Exception as e:
        print("Edit Prescription Error:", e)
        return "Unable to update prescription. Check the terminal.", 500



# UPDATE PRESCRIPTION STATUS
@app.route("/update_prescription_status", methods=["POST"])
@role_required("Doctor")
def update_prescription_status():

    prescription_id = request.form.get("prescription_id")
    status = request.form.get("status")

    allowed_statuses = ["Pending", "Cancelled", "Completed"]

    if status not in allowed_statuses:
        return "Invalid prescription status.", 400

    db = connect_db()

    if db is None:
        return "Database connection failed.", 500

    cursor = db.cursor()

    try:
        cursor.execute("""
            UPDATE Prescriptions
            SET Status = %s
            WHERE Prescription_ID = %s
              AND Status <> 'Completed'
        """, (status, prescription_id))

        if cursor.rowcount == 0:
            return "Prescription not found.", 404

        db.commit()

    except Exception as e:
        db.rollback()
        print("Prescription Status Error:", e)
        return "Unable to update prescription status.", 500

    finally:
        cursor.close()
        db.close()

    return redirect(url_for("prescriptions", updated=1))


# DELETE PRESCRIPTION SAFELY
@app.route("/delete_prescription/<int:prescription_id>", methods=["POST"])
@role_required("Doctor")
def delete_prescription(prescription_id):

    db = connect_db()

    if db is None:
        return "Database connection failed.", 500

    cursor = db.cursor()

    try:
        # DO NOT DELETE A PRESCRIPTION ALREADY DISPENSED
        cursor.execute("""
            SELECT Record_ID
            FROM Dispensary_Records
            WHERE Prescription_ID = %s
            LIMIT 1
        """, (prescription_id,))

        if cursor.fetchone() is not None:
            return (
                "This prescription has dispensing records "
                "and cannot be deleted.",
                409
            )

        cursor.execute("""
            DELETE FROM Prescription_Items
            WHERE Prescription_ID = %s
        """, (prescription_id,))

        cursor.execute("""
            DELETE FROM Prescriptions
            WHERE Prescription_ID = %s
        """, (prescription_id,))

        if cursor.rowcount == 0:
            db.rollback()
            return "Prescription not found.", 404

        db.commit()

    except Exception as e:
        db.rollback()
        print("Delete Prescription Error:", e)
        return "Unable to delete prescription.", 500

    finally:
        cursor.close()
        db.close()

    return redirect(url_for("prescriptions", deleted=1))







# REMOVE EXPIRED BATCH FROM ACTIVE INVENTORY (preserve the database row/history)
@app.route("/remove_expired_batch/<int:batch_id>", methods=["POST"])
@role_required("Pharmacist")
def remove_expired_batch(batch_id):
    db = connect_db()
    if db is None:
        return "Database connection failed.", 500

    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE Batches
            SET Is_Removed = TRUE
            WHERE Batch_ID = %s
              AND Expiry_Date < CURDATE()
              AND Quantity > 0
              AND Is_Removed = FALSE
        """, (batch_id,))

        if cursor.rowcount == 0:
            db.rollback()
            return "Batch not found or cannot be removed.", 400

        db.commit()
    except Exception as e:
        db.rollback()
        print("Remove Expired Batch Error:", e)
        return "Unable to remove batch. Check terminal.", 500
    finally:
        cursor.close()
        db.close()

    return redirect(url_for("medicines"))


# DISPENSING MANAGEMENT
@app.route("/dispensing", methods=["GET", "POST"])
@role_required("Pharmacist")
def dispensing():
    db = connect_db()
    if db is None:
        return "Database connection failed. Please check database.py.", 500

    cursor = db.cursor(dictionary=True, buffered=True)
    message = request.args.get("message", "")
    message_type = request.args.get("type", "success")

    try:
        if request.method == "POST":
            prescription_id = request.form.get("prescription_id")
            pharmacist_id = request.form.get("pharmacist_id")

            if not prescription_id or not pharmacist_id:
                return redirect(url_for(
                    "dispensing",
                    message="Please select a prescription and pharmacist.",
                    type="error"
                ))

            db.start_transaction()

            cursor.execute("""
                SELECT Prescription_ID, Status
                FROM Prescriptions
                WHERE Prescription_ID = %s
                FOR UPDATE
            """, (prescription_id,))
            prescription = cursor.fetchone()

            if not prescription:
                db.rollback()
                return redirect(url_for(
                    "dispensing", message="Prescription not found.", type="error"
                ))

            if prescription["Status"] != "Pending":
                db.rollback()
                return redirect(url_for(
                    "dispensing",
                    message="Only pending prescriptions can be dispensed.",
                    type="error"
                ))

            cursor.execute("""
                SELECT User_ID
                FROM Users_Auth
                WHERE User_ID = %s AND Role = 'Pharmacist'
            """, (pharmacist_id,))
            if cursor.fetchone() is None:
                db.rollback()
                return redirect(url_for(
                    "dispensing",
                    message="Please select a valid pharmacist.",
                    type="error"
                ))

            cursor.execute("""
                SELECT Medicine_ID,
                       SUM(Prescribed_Quantity) AS Prescribed_Quantity
                FROM Prescription_Items
                WHERE Prescription_ID = %s
                GROUP BY Medicine_ID
            """, (prescription_id,))
            prescribed_items = cursor.fetchall()

            if not prescribed_items:
                db.rollback()
                return redirect(url_for(
                    "dispensing",
                    message="This prescription has no medicine items.",
                    type="error"
                ))

            cursor.execute("""
                SELECT b.Medicine_ID,
                       COALESCE(SUM(dr.Quantity_Dispensed), 0) AS Dispensed_Quantity
                FROM Dispensary_Records dr
                JOIN Batches b ON dr.Batch_ID = b.Batch_ID
                WHERE dr.Prescription_ID = %s
                GROUP BY b.Medicine_ID
            """, (prescription_id,))
            already_dispensed = {
                row["Medicine_ID"]: row["Dispensed_Quantity"]
                for row in cursor.fetchall()
            }

            # FEFO: use the eligible batch with the earliest expiry date first.
            for item in prescribed_items:
                medicine_id = item["Medicine_ID"]
                remaining = (
                    item["Prescribed_Quantity"]
                    - already_dispensed.get(medicine_id, 0)
                )
                if remaining <= 0:
                    continue

                cursor.execute("""
                    SELECT Batch_ID, Quantity, Expiry_Date
                    FROM Batches
                    WHERE Medicine_ID = %s
                      AND Quantity > 0
                      AND Expiry_Date >= CURDATE()
                      AND Is_Removed = FALSE
                    ORDER BY Expiry_Date ASC, Batch_ID ASC
                    FOR UPDATE
                """, (medicine_id,))
                batches = cursor.fetchall()
                available = sum(batch["Quantity"] for batch in batches)

                if available < remaining:
                    cursor.execute("""
                        SELECT Generic_Name
                        FROM Medicines
                        WHERE Medicine_ID = %s
                    """, (medicine_id,))
                    medicine = cursor.fetchone()
                    medicine_name = (
                        medicine["Generic_Name"]
                        if medicine else f"Medicine ID {medicine_id}"
                    )
                    db.rollback()
                    return redirect(url_for(
                        "dispensing",
                        message=(
                            f"Insufficient unexpired stock for {medicine_name}. "
                            f"Required: {remaining}, Available: {available}."
                        ),
                        type="error"
                    ))

                to_dispense = remaining
                for batch in batches:
                    if to_dispense <= 0:
                        break

                    dispense_qty = min(batch["Quantity"], to_dispense)

                    # The database AFTER INSERT trigger decrements batch stock.
                    # Do not update Batches.Quantity here as well.
                    cursor.execute("""
                        INSERT INTO Dispensary_Records
                        (Prescription_ID, Batch_ID, Quantity_Dispensed,
                         Dispense_Date, Pharmacist_ID)
                        VALUES (%s, %s, %s, CURDATE(), %s)
                    """, (
                        prescription_id,
                        batch["Batch_ID"],
                        dispense_qty,
                        pharmacist_id
                    ))
                    to_dispense -= dispense_qty

            cursor.execute("""
                UPDATE Prescriptions
                SET Status = 'Completed'
                WHERE Prescription_ID = %s
            """, (prescription_id,))
            db.commit()

            return redirect(url_for(
                "dispensing",
                message="Prescription dispensed successfully!",
                type="success"
            ))

        # Pending prescriptions
        cursor.execute("""
            SELECT p.Prescription_ID, p.Date_Issued, p.Status,
                   pt.Patient_ID, pt.Name AS Patient_Name,
                   u.Name AS Doctor_Name
            FROM Prescriptions p
            JOIN Patients pt ON p.Patient_ID = pt.Patient_ID
            JOIN Users_Auth u ON p.Doctor_ID = u.User_ID
            WHERE p.Status = 'Pending'
            ORDER BY p.Date_Issued DESC, p.Prescription_ID DESC
        """)
        prescriptions_list = cursor.fetchall()

        for prescription in prescriptions_list:
            cursor.execute("""
                SELECT pi.Medicine_ID, m.Generic_Name, m.Brand_Name,
                       SUM(pi.Prescribed_Quantity) AS Prescribed_Quantity
                FROM Prescription_Items pi
                JOIN Medicines m ON pi.Medicine_ID = m.Medicine_ID
                WHERE pi.Prescription_ID = %s
                GROUP BY pi.Medicine_ID, m.Generic_Name, m.Brand_Name
                ORDER BY m.Generic_Name
            """, (prescription["Prescription_ID"],))
            items = cursor.fetchall()

            for item in items:
                cursor.execute("""
                    SELECT COALESCE(SUM(Quantity), 0) AS Available_Stock
                    FROM Batches
                    WHERE Medicine_ID = %s
                      AND Quantity > 0
                      AND Expiry_Date >= CURDATE()
                      AND Is_Removed = FALSE
                """, (item["Medicine_ID"],))
                item["Available_Stock"] = cursor.fetchone()["Available_Stock"]

                cursor.execute("""
                    SELECT COALESCE(SUM(dr.Quantity_Dispensed), 0)
                           AS Dispensed_Quantity
                    FROM Dispensary_Records dr
                    JOIN Batches b ON dr.Batch_ID = b.Batch_ID
                    WHERE dr.Prescription_ID = %s
                      AND b.Medicine_ID = %s
                """, (prescription["Prescription_ID"], item["Medicine_ID"]))
                item["Already_Dispensed"] = cursor.fetchone()["Dispensed_Quantity"]
                item["Remaining_Quantity"] = max(
                    0,
                    item["Prescribed_Quantity"] - item["Already_Dispensed"]
                )

            prescription["items"] = items

        cursor.execute("""
            SELECT User_ID, Name
            FROM Users_Auth
            WHERE Role = 'Pharmacist'
            ORDER BY Name
        """)
        pharmacists = cursor.fetchall()

        cursor.execute("""
            SELECT dr.Record_ID, dr.Prescription_ID,
                   pt.Name AS Patient_Name,
                   m.Generic_Name, m.Brand_Name,
                   b.Batch_ID, dr.Quantity_Dispensed, dr.Dispense_Date,
                   pharmacist.Name AS Pharmacist_Name
            FROM Dispensary_Records dr
            JOIN Prescriptions p ON dr.Prescription_ID = p.Prescription_ID
            JOIN Patients pt ON p.Patient_ID = pt.Patient_ID
            JOIN Batches b ON dr.Batch_ID = b.Batch_ID
            JOIN Medicines m ON b.Medicine_ID = m.Medicine_ID
            JOIN Users_Auth pharmacist ON dr.Pharmacist_ID = pharmacist.User_ID
            ORDER BY dr.Record_ID DESC
        """)
        dispensing_history = cursor.fetchall()

        return render_template(
            "dispensing.html",
            prescriptions=prescriptions_list,
            pharmacists=pharmacists,
            dispensing_history=dispensing_history,
            message=message,
            message_type=message_type
        )

    except Exception as e:
        db.rollback()
        print("Dispensing Error:", e)
        return redirect(url_for(
            "dispensing",
            message="Dispensing failed. Check the terminal for details.",
            type="error"
        ))
    finally:
        cursor.close()
        db.close()


# RUN FLASK APPLICATION
if __name__ == "__main__":
    app.run(debug=True)
