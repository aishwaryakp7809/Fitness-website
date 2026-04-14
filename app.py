from flask import Flask, render_template, request, redirect, url_for, session, g, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "supersecret_change_this"   # change in production
DATABASE = "fitness.db"

# ---------------- DB Setup ----------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    """Create tables & seed data if empty"""
    with app.app_context():
        db = get_db()

        # Create tables (users now has points)
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                points INTEGER DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, description TEXT, duration INTEGER, level TEXT, imageUrl TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS nutrition (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, calories INTEGER, description TEXT, imageUrl TEXT
            )
        """)
        # assigned routines per user (one row per scheduled routine)
        db.execute("""
            CREATE TABLE IF NOT EXISTS routines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                videoUrl TEXT,
                scheduled_date TEXT,
                scheduled_time TEXT,
                status TEXT DEFAULT 'pending', -- pending/completed
                created_at TEXT,
                points_awarded INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        # badges / rewards earned
        db.execute("""
            CREATE TABLE IF NOT EXISTS rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                description TEXT,
                awarded_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        db.commit()

        # Basic seed workouts & nutrition (only if empty)
        if db.execute("SELECT COUNT(*) FROM workouts").fetchone()[0] == 0:
            db.executemany("""
                INSERT INTO workouts (title, description, duration, level, imageUrl)
                VALUES (?, ?, ?, ?, ?)
            """, [
                ("Full Body Beginner", "A 25-minute full body routine for beginners.", 25, "Beginner",
                    "https://images.unsplash.com/photo-1554284126-aa88f22d8b6b?auto=format&fit=crop&w=800&q=60"),
                ("HIIT Fat Burner", "20-minute high intensity interval training.", 20, "Intermediate",
                    "https://images.unsplash.com/photo-1558611848-73f7eb4001b6?auto=format&fit=crop&w=800&q=60"),
                ("Yoga Flow", "Relaxing 30-minute yoga session.", 30, "All Levels",
                    "https://images.unsplash.com/photo-1554306274-f23873d9a26a?auto=format&fit=crop&w=800&q=60")
            ])
        if db.execute("SELECT COUNT(*) FROM nutrition").fetchone()[0] == 0:
            db.executemany("""
                INSERT INTO nutrition (title, calories, description, imageUrl)
                VALUES (?, ?, ?, ?)
            """, [
                ("Protein Pancakes", 350, "High-protein breakfast to fuel workouts.",
                    "https://images.unsplash.com/photo-1551218808-94e220e084d2?auto=format&fit=crop&w=800&q=60"),
                ("Quinoa Salad", 420, "Balanced salad with veggies and quinoa.",
                    "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?auto=format&fit=crop&w=800&q=60"),
                ("Smoothie Bowl", 280, "Fruity smoothie bowl with nuts and seeds.",
                    "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=800&q=60")
            ])
        db.commit()

# ---------------- Utility: simple generator ----------------
def generate_routines_for_user(user_id, age, weight, strength_level, goal, preferred_time):
    """
    Heuristic routine generator:
    - chooses a routine type based on goal and strength_level
    - assigns a youtube link (sample) and schedules next 7 days at preferred_time
    """
    # Simple mapping of routine types to YouTube sample links0
    youtube_library = {
        "beginner_full": ("Beginner Full Body Workout", "https://www.youtube.com/watch?v=UBMk30rjy0o"),
        "hiit": ("20 Min HIIT Workout", "https://www.youtube.com/watch?v=ml6cT4AZdqI"),
        "yoga": ("30 Min Yoga Flow", "https://www.youtube.com/watch?v=v7AYKMP6rOE"),
        "mobility": ("Mobility Routine", "https://www.youtube.com/watch?v=UL0Z0m7_3E4"),
        "strength": ("Beginner Strength", "https://www.youtube.com/watch?v=U0bhE67HuDY")
    }

    # decide base routine key
    if goal.lower().find("lose") >= 0 or goal.lower().find("fat") >= 0:
        key = "hiit" if strength_level.lower() in ("intermediate", "advanced") else "beginner_full"
    elif goal.lower().find("flex") >= 0 or goal.lower().find("mobility") >= 0:
        key = "mobility"
    elif goal.lower().find("strength") >= 0 or strength_level.lower() in ("intermediate", "advanced"):
        key = "strength"
    else:
        key = "beginner_full"

    # if user is older or low strength, prefer gentle yoga/mobility
    if age and int(age) >= 55:
        key = "yoga"

    title_base, link = youtube_library.get(key, youtube_library["beginner_full"])

    # create 7-day schedule starting today
    assignments = []
    start_date = datetime.now().date()
    for i in range(7):
        d = start_date + timedelta(days=i)
        scheduled_date = d.isoformat()
        scheduled_time = preferred_time or "07:00"
        assignments.append({
            "title": f"{title_base} — Day {i+1}",
            "videoUrl": link,
            "scheduled_date": scheduled_date,
            "scheduled_time": scheduled_time
        })
    # Insert into DB
    db = get_db()
    now = datetime.now().isoformat()
    for a in assignments:
        db.execute("""
            INSERT INTO routines (user_id, title, videoUrl, scheduled_date, scheduled_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, a["title"], a["videoUrl"], a["scheduled_date"], a["scheduled_time"], now))
    db.commit()

# ---------------- Routes ----------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/assess", methods=["GET", "POST"])
def assess():
    if "user_id" not in session:
        flash("Please login to create a personalized routine.", "info")
        return redirect(url_for("login"))

    bmi = None
    bmi_status = ""

    if request.method == "POST":
        age = request.form.get("age")
        weight = request.form.get("weight")
        height = request.form.get("height")
        strength = request.form.get("strength")
        goal = request.form.get("goal")
        preferred_time = request.form.get("time")

        try:
            weight = float(weight)
            height_cm = float(height)
            height_m = height_cm / 100
            bmi = round(weight / (height_m ** 2), 2)

            # Interpret BMI result
            if bmi < 18.5:
                bmi_status = "Underweight"
            elif 18.5 <= bmi < 25:
                bmi_status = "Normal weight"
            elif 25 <= bmi < 30:
                bmi_status = "Overweight"
            else:
                bmi_status = "Obese"

        except (ValueError, ZeroDivisionError):
            flash("Invalid input for height or weight.", "danger")
            return render_template("assess.html")

        # Optional: Save routine or call generation function here
        flash("Your routine has been created!", "success")
        return render_template("assess.html", bmi=bmi, bmi_status=bmi_status)

    return render_template("assess.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not (name and email and password):
            flash("Please fill all fields", "danger")
            return render_template("signup.html")

        db = get_db()
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("Email already registered. Try login.", "danger")
            return render_template("signup.html")

        hashed = generate_password_hash(password)
        db.execute("INSERT INTO users (name,email,password) VALUES (?,?,?)", (name, email, hashed))
        db.commit()
        flash("Account created. Please login.", "success")
        return redirect(url_for("login"))
    dob = request.form.get("dob") 
    diet = request.form.get("diet")
 

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash("Logged in successfully", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials. Please try again.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("home"))

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("Please login to see the dashboard.", "info")
        return redirect(url_for("login"))

    db = get_db()
    workouts = db.execute("SELECT * FROM workouts ORDER BY id DESC").fetchall()
    routines = db.execute("SELECT * FROM routines WHERE user_id=? ORDER BY scheduled_date", (session["user_id"],)).fetchall()
    rewards = db.execute("SELECT * FROM rewards WHERE user_id=? ORDER BY awarded_at DESC", (session["user_id"],)).fetchall()
    user_row = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    food_preference = user_row["food_preference"]
    
    # Filter nutrition based on preference (match keywords)
    if food_preference == "veg":
        nutrition = db.execute("SELECT * FROM nutrition WHERE LOWER(title) LIKE '%salad%' OR LOWER(title) LIKE '%veg%' OR LOWER(title) LIKE '%quinoa%' OR LOWER(title) LIKE '%smoothie%'").fetchall()
    else:
        nutrition = db.execute("SELECT * FROM nutrition WHERE LOWER(title) LIKE '%chicken%' OR LOWER(title) LIKE '%fish%' OR LOWER(title) LIKE '%egg%'").fetchall()

    user = {
        "name": session.get("user_name", "User"),
        "progress": user_row["progress"] if user_row else 0,
        "points": user_row["points"] if user_row else 0,
        "food_preference": food_preference
    }

    return render_template("dashboard.html", workouts=workouts, nutrition=nutrition, routines=routines, rewards=rewards, user=user)

@app.route("/complete_workout/<int:wid>")
def complete_workout(wid):
    """Legacy complete button for workouts: increases progress & points"""
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    # increase progress and points
    db.execute("UPDATE users SET progress = MIN(progress + 5, 100), points = points + 5 WHERE id=?", (session["user_id"],))
    db.commit()
    check_and_award_badges(session["user_id"])
    flash("Workout completed! Progress +5% and +5 points.", "success")
    return redirect(url_for("dashboard"))

@app.route("/complete_routine/<int:rid>")
def complete_routine(rid):
    """Mark a scheduled routine as completed; award points & progress"""
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    r = db.execute("SELECT * FROM routines WHERE id=? AND user_id=?", (rid, session["user_id"])).fetchone()
    if not r:
        flash("Routine not found.", "danger")
        return redirect(url_for("dashboard"))
    if r["status"] == "completed":
        flash("You already completed this routine.", "info")
        return redirect(url_for("dashboard"))

    # award points: default 10 per routine
    points_awarded = 10
    db.execute("UPDATE routines SET status='completed', points_awarded=? WHERE id=?", (points_awarded, rid))
    db.execute("UPDATE users SET points = points + ?, progress = MIN(progress + 10, 100) WHERE id=?", (points_awarded, session["user_id"]))
    db.commit()
    # check for badges
    check_and_award_badges(session["user_id"])
    flash("Great job! Routine completed: +10% progress and +10 points.", "success")
    return redirect(url_for("dashboard"))

# ---------------- Rewards logic ----------------
def check_and_award_badges(user_id):
    """
    Award badges when points thresholds reached.
    thresholds: 50 -> 'Committed', 100 -> 'Champion'
    """
    db = get_db()
    row = db.execute("SELECT points FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return
    points = row["points"] or 0
    # helper to award if not already awarded
    def award(name, desc):
        existing = db.execute("SELECT id FROM rewards WHERE user_id=? AND name=?", (user_id, name)).fetchone()
        if not existing:
            db.execute("INSERT INTO rewards (user_id, name, description, awarded_at) VALUES (?, ?, ?, ?)",
                        (user_id, name, desc, datetime.now().isoformat()))
            db.commit()
    if points >= 50:
        award("Committed", "Completed 50 points — consistent effort!")
    if points >= 100:
        award("Champion", "Reached 100 points — excellent dedication!")

# ---------------- Run App ----------------
if __name__ == "__main__":
    # if database exists but schema older, delete for fresh start (advise user)
    # For safety, do not auto-delete. If you want fresh schema remove fitness.db manually.
    init_db()
    app.run(debug=True)