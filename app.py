from flask import Flask, render_template, request, redirect, url_for, session
from hostel_data import hostel_data
import re, random

app = Flask(__name__)
app.secret_key = "secret123"

users = {}         # {username: {"password":..., "email":..., "gender":..., "age":...}}
applications = []  # saved applications after payment

# ---------------- Helpers ----------------
def parse_price_to_int(price_str):
    """example: '₹6000/month' -> 6000 (int). Returns 0 if parse fails."""
    if not price_str:
        return 0
    m = re.search(r'(\d[\d,]*)', price_str.replace(',', ''))
    if m:
        return int(m.group(1))
    return 0

def find_hostel_by_city_and_name(city, hostel_name):
    """Search nested hostel_data and return (hostel_obj, place_name) or (None, None)."""
    places = hostel_data.get(city, {})
    for place_name, hostels in places.items():
        for h in hostels:
            if h.get("name") == hostel_name:
                return h, place_name
    return None, None

def finalize_booking_and_append(app_data):
    """Decrease vacancy, assign room_number and append to applications."""
    city = app_data["location"]
    hostel_name = app_data["hostel_name"]
    hostel, place = find_hostel_by_city_and_name(city, hostel_name)
    if not hostel:
        return False, "Hostel not found."

    if "vacancy" not in hostel:
        hostel["vacancy"] = hostel["rooms"]

    if hostel["vacancy"] <= 0:
        return False, "No vacancy."

    # decrease vacancy and compute room number
    hostel["vacancy"] -= 1
    # room index assigned = total rooms - current vacancy
    assigned_index = hostel["rooms"] - hostel["vacancy"]
    room_number = f"{city[:2].upper()}-{100 + assigned_index}"
    app_data["room_number"] = room_number

    # append application
    applications.append(app_data)
    return True, None

# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("index.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirm = request.form.get("confirm")
        email = request.form.get("email")
        gender = request.form.get("gender")
        age = request.form.get("age")

        strong_pass = re.match(r'^(?=.*[0-9])(?=.*[!@#$%^&*])[A-Za-z0-9!@#$%^&*]{8,}$', password)

        if not username or not password or not email or not gender or not age:
            error = "Please fill all fields."
        elif password != confirm:
            error = "Passwords do not match."
        elif not strong_pass:
            error = "Password must be at least 8 characters long and include a number and special character."
        elif username in users:
            error = "Username already exists."
        else:
            users[username] = {
                "password": password,
                "email": email,
                "gender": gender,
                "age": age
            }
            return redirect(url_for("login"))

    return render_template("register.html", error=error)

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        # admin login
        if username == "admin" and password == "admin123":
            session["username"] = "admin"
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))
        # student login
        if username in users and users[username]["password"] == password:
            session["username"] = username
            session["role"] = "student"
            return redirect(url_for("dashboard"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)

# ---------------- ADMIN LOGIN (separate if needed) ----------------
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == "admin" and password == "admin123":
            session["username"] = "admin"
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))
        error = "Invalid admin credentials."
    return render_template("admin_login.html", error=error)

# ---------------- DASHBOARD (Student) ----------------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("login"))

    selected_city = None
    selected_place = None
    places = []
    results = []

    if request.method == "POST":
        selected_city = request.form.get("location")
        selected_place = request.form.get("place")
        if selected_city and selected_city in hostel_data:
            places = list(hostel_data[selected_city].keys())
            if selected_place and selected_place in hostel_data[selected_city]:
                results = hostel_data[selected_city][selected_place]

    return render_template(
        "dashboard.html",
        locations=list(hostel_data.keys()),
        selected_location=selected_city,
        selected_place=selected_place,
        places=places,
        results=results
    )

# ---------------- APPLY (Student) ----------------
@app.route("/apply/<location>/<hostel_name>", methods=["GET", "POST"])
def apply(location, hostel_name):
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("login"))

    hostel, place = find_hostel_by_city_and_name(location, hostel_name)
    if not hostel:
        return "Hostel not found", 404

    if request.method == "POST":
        room_type = request.form.get("room_type")
        duration = request.form.get("duration")
        food_req = request.form.get("food_requirement")
        phone = request.form.get("phone")
        email = users[session["username"]]["email"]

        # phone validation
        if not phone or len(phone) != 10 or not phone.isdigit():
            return render_template("apply.html", location=location, hostels=[hostel],
                                   error="Please enter a valid 10-digit phone number.")

        # store pending application in session (wait until payment to finalize)
        session["pending_application"] = {
            "student": session["username"],
            "email": email,
            "phone": phone,
            "location": location,
            "hostel_name": hostel_name,
            "room_type": room_type,
            "duration": duration,
            "food_requirement": food_req
        }

        # compute amount from hostel.price
        amount = parse_price_to_int(hostel.get("price"))
        session["pending_application"]["amount"] = amount

        return redirect(url_for("payment_options"))

    return render_template("apply.html", location=location, hostels=[hostel])

# ---------------- PAYMENT OPTIONS ----------------
@app.route("/payment_options", methods=["GET", "POST"])
def payment_options():
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("login"))

    app_data = session.get("pending_application")
    if not app_data:
        return redirect(url_for("dashboard"))

    hostel_obj, _ = find_hostel_by_city_and_name(app_data["location"], app_data["hostel_name"])
    amount = app_data.get("amount", 0)

    if request.method == "POST":
        method = request.form.get("payment_method")
        if method == "Card":
            return redirect(url_for("pay_card"))
        elif method == "UPI":
            return redirect(url_for("pay_upi"))
        elif method == "Cash":
            return redirect(url_for("pay_cash"))
        else:
            return render_template("payment_options.html", error="Select a payment method.", amount=amount)

    return render_template("payment_options.html", amount=amount)

# ---------------- PAY - CARD ----------------
@app.route("/pay_card", methods=["GET", "POST"])
def pay_card():
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("login"))
    app_data = session.get("pending_application")
    if not app_data:
        return redirect(url_for("dashboard"))
    amount = app_data.get("amount", 0)

    if request.method == "POST":
        card_number = request.form.get("card_number", "").strip()
        name_on_card = request.form.get("name_on_card", "").strip()
        expiry = request.form.get("expiry", "").strip()
        cvv = request.form.get("cvv", "").strip()

        # basic validations
        if len(card_number) < 12 or not card_number.isdigit():
            return render_template("card_payment.html", amount=amount, error="Enter a valid card number.")
        if not cvv.isdigit() or len(cvv) not in (3,4):
            return render_template("card_payment.html", amount=amount, error="Enter a valid CVV.")

        # for demo: generate an OTP and set in session (we'll accept any 4-digit OR the shown OTP)
        otp = random.randint(1000, 9999)
        session["payment_otp"] = str(otp)
        # store card details temporarily (not used further)
        session["card_info"] = {"card_number": card_number[-4:], "name": name_on_card}
        return redirect(url_for("card_otp"))

    return render_template("card_payment.html", amount=amount)

# ---------------- CARD OTP ----------------
@app.route("/card_otp", methods=["GET", "POST"])
def card_otp():
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("login"))
    app_data = session.get("pending_application")
    if not app_data:
        return redirect(url_for("dashboard"))
    shown_otp = session.get("payment_otp", None)
    amount = app_data.get("amount", 0)

    if request.method == "POST":
        entered = request.form.get("otp", "").strip()
        # demo: accept any 4-digit OTP OR the one we generated
        if (entered.isdigit() and len(entered) == 4):
            # finalize booking
            app_data["payment_method"] = "Card"
            app_data["payment_details"] = {"card_last4": session.get("card_info", {}).get("card_number")}
            app_data["status"] = "Paid"
            ok, err = finalize_booking_and_append(app_data)
            session.pop("pending_application", None)
            session.pop("payment_otp", None)
            session.pop("card_info", None)
            if not ok:
                return render_template("card_otp.html", amount=amount, error=err)
            return render_template("success.html", **applications[-1])
        else:
            return render_template("card_otp.html", amount=amount, error="Enter a 4-digit OTP (demo accepts any).", shown_otp=shown_otp)

    return render_template("card_otp.html", amount=amount, shown_otp=shown_otp)

# ---------------- PAY - UPI ----------------
@app.route("/pay_upi", methods=["GET", "POST"])
def pay_upi():
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("login"))
    app_data = session.get("pending_application")
    if not app_data:
        return redirect(url_for("dashboard"))
    amount = app_data.get("amount", 0)

    if request.method == "POST":
        # user clicks "I have paid" or enters txn id
        txn = request.form.get("txn_id", "").strip()
        app_data["payment_method"] = "UPI"
        app_data["payment_details"] = {"txn_id": txn or f"UPI-{random.randint(10000,99999)}"}
        app_data["status"] = "Paid"
        ok, err = finalize_booking_and_append(app_data)
        session.pop("pending_application", None)
        if not ok:
            return render_template("upi_payment.html", amount=amount, error=err)
        return render_template("success.html", **applications[-1])

    # GET show fake QR + scanner
    fake_qr_code_value = f"upi://pay?pa=hostel@upi&am={amount}&pn=Hostel"
    return render_template("upi_payment.html", amount=amount, qr_value=fake_qr_code_value)

# ---------------- PAY - CASH ----------------
@app.route("/pay_cash", methods=["GET", "POST"])
def pay_cash():
    if "username" not in session or session.get("role") != "student":
        return redirect(url_for("login"))
    app_data = session.get("pending_application")
    if not app_data:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        app_data["payment_method"] = "Cash on Arrival"
        app_data["payment_details"] = {}
        app_data["status"] = "Pending (Cash)"
        ok, err = finalize_booking_and_append(app_data)
        session.pop("pending_application", None)
        if not ok:
            return render_template("payment_options.html", amount=app_data.get("amount", 0), error=err)
        return render_template("success.html", **applications[-1])

    # show a confirmation page asking to confirm cash payment
    return render_template("pay_cash.html", amount=app_data.get("amount", 0))

# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin_dashboard")
def admin_dashboard():
    if "username" not in session or session.get("role") != "admin":
        return redirect(url_for("admin_login"))
    # summary by city
    summary = {}
    for city, places in hostel_data.items():
        total_rooms = 0
        total_vacant = 0
        for place, hostels in places.items():
            for h in hostels:
                total_rooms += h["rooms"]
                total_vacant += h.get("vacancy", h["rooms"])
        summary[city] = {"booked": total_rooms - total_vacant, "vacant": total_vacant}
    return render_template("admin_dashboard.html", applications=applications, summary=summary)

# ---------------- UPDATE STATUS (Admin) ----------------
@app.route("/update_status/<int:app_index>/<action>")
def update_status(app_index, action):
    if "username" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    if 0 <= app_index < len(applications):
        app_data = applications[app_index]
        city = app_data["location"]
        hostel_name = app_data["hostel_name"]
        for place, hostels in hostel_data[city].items():
            for hostel in hostels:
                if hostel["name"] == hostel_name:
                    if action == "accept":
                        if app_data["status"] != "Accepted ✅" and hostel.get("vacancy", hostel["rooms"]) > 0:
                            hostel["vacancy"] -= 1
                        app_data["status"] = "Accepted ✅"
                    elif action == "reject":
                        if app_data["status"] == "Accepted ✅":
                            hostel["vacancy"] += 1
                        app_data["status"] = "Rejected ❌"
                    break
    return redirect(url_for("admin_dashboard"))

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
