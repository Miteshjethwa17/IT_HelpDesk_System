from flask import Flask, render_template, request, redirect, session, url_for, make_response, flash
from database import db
import ticket
import secrets
from datetime import datetime, timedelta
app = Flask(__name__)
app.secret_key = "helpdesk_secret_key"

@app.context_processor
def inject_theme():
    return {
        "theme": session.get("theme", "Light")
    }


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return redirect("/login")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        user = db.fetch_one(
            """
            SELECT *
            FROM Users
            WHERE Email=? AND PasswordHash=?
            """,
            (email, password)
        )

        if user:

            session["user_id"] = user.UserID
            session["user_name"] = user.FullName
            session["role"] = user.Role

            # Default theme
            if "theme" not in session:
                session["theme"] = "Light"

            if user.Role == "Admin":
                return redirect("/dashboard")

            elif user.Role == "Support":
                return redirect("/support-dashboard")

            elif user.Role == "Employee":
                return redirect("/employee-dashboard")

        return render_template(
            "login.html",
            error="Invalid Email or Password"
        )

    return render_template("login.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form.get("email", "").strip()

        if not email:
            return render_template(
                "forgot_password.html",
                error="Please enter your email address."
            )

        user = db.fetch_one(
            """
            SELECT UserID, FullName, Email
            FROM Users
            WHERE Email = ?
            """,
            (email,)
        )

        if not user:
            return render_template(
                "forgot_password.html",
                error="No account found with this email address."
            )

        # Generate secure reset token
        reset_token = secrets.token_urlsafe(32)

        # Token valid for 15 minutes
        expiry = datetime.now() + timedelta(minutes=15)

        db.execute(
            """
            UPDATE Users
            SET ResetToken = ?,
                ResetTokenExpiry = ?
            WHERE UserID = ?
            """,
            (reset_token, expiry, user.UserID),
            commit=True
        )

        return redirect(
            url_for("reset_password", token=reset_token)
        )

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):

    user = db.fetch_one(
        """
        SELECT UserID, FullName, Email, ResetToken, ResetTokenExpiry
        FROM Users
        WHERE ResetToken = ?
        """,
        (token,)
    )

    # Token invalid
    if not user:
        return render_template(
            "reset_password.html",
            error="Invalid or expired password reset link."
        )

    # Token expired
    if not user.ResetTokenExpiry or user.ResetTokenExpiry < datetime.now():
        return render_template(
            "reset_password.html",
            error="This password reset link has expired. Please request a new one."
        )

    if request.method == "POST":

        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not new_password or not confirm_password:
            return render_template(
                "reset_password.html",
                error="Please fill in both password fields."
            )

        if new_password != confirm_password:
            return render_template(
                "reset_password.html",
                error="Passwords do not match."
            )

        if len(new_password) < 6:
            return render_template(
                "reset_password.html",
                error="Password must be at least 6 characters."
            )

        # Update password and remove reset token
        db.execute(
            """
            UPDATE Users
            SET PasswordHash = ?,
                ResetToken = NULL,
                ResetTokenExpiry = NULL
            WHERE UserID = ?
            """,
            (new_password, user.UserID),
            commit=True
        )

        return redirect("/login")

    return render_template("reset_password.html")


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        fullname = request.form.get("fullname")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")

        if password != confirm:

            return render_template(
                "register.html",
                error="Passwords do not match."
            )

        existing_user = db.fetch_one(
            """
            SELECT *
            FROM Users
            WHERE Email=?
            """,
            (email,)
        )

        if existing_user:

            return render_template(
                "register.html",
                error="Email already exists."
            )

        db.execute(
            """
            INSERT INTO Users
            (
                FullName,
                Email,
                PasswordHash,
                Role
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                fullname,
                email,
                password,
                "Employee"
            ),
            commit=True
        )

        return redirect("/login")

    return render_template("register.html")


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session or session.get("role") != "Admin":
        return redirect("/login")

    total = db.fetch_scalar(
        "SELECT COUNT(*) FROM Tickets"
    )

    open_count = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Status='Open'
        """
    )

    pending_count = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Status='Pending'
        """
    )

    progress_count = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Status='In Progress'
        """
    )

    resolved_count = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Status='Resolved'
        """
    )

    # =====================================================
    # UNREAD NOTIFICATION COUNT
    # =====================================================

    notification_count = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM dbo.Notifications
        WHERE UserID = ?
          AND IsRead = 0
        """,
        (session["user_id"],)
    )

    notification_count = notification_count or 0

    recent_tickets = db.fetch_all(
        """
        SELECT TOP 5
            TicketID,
            Title,
            Status,
            Priority
        FROM Tickets
        ORDER BY TicketID DESC
        """
    )

    return render_template(
        "dashboard.html",
        total=total,
        open_tickets=open_count,
        pending=pending_count,
        progress=progress_count,
        resolved=resolved_count,
        recent_tickets=recent_tickets,
        notification_count=notification_count,
        theme=session.get("theme", "Light")
    )
# =========================================================
# DASHBOARD SEARCH
# =========================================================

@app.route("/dashboard-search")
def dashboard_search():

    if "user_id" not in session:
        return redirect("/login")

    search = request.args.get("search", "").strip()

    tickets = []

    if search:

        tickets = db.fetch_all(
            """
            SELECT
                TicketID,
                Title,
                Status,
                Priority
            FROM Tickets
            WHERE
                CAST(TicketID AS VARCHAR) LIKE ?
                OR Title LIKE ?
            ORDER BY TicketID DESC
            """,
            (
                "%" + search + "%",
                "%" + search + "%"
            )
        )

    return render_template(
        "view_tickets.html",
        tickets=tickets,
        search=search,
        status=None
    )

# =========================================================
# NOTIFICATIONS
# =========================================================

@app.route("/notifications")
def notifications():

    if "user_id" not in session:
        return redirect("/login")

    notifications = db.fetch_all(
        """
        SELECT TOP 20
            NotificationID,
            UserID,
            TicketID,
            Title,
            Message,
            IsRead,
            CreatedAt
        FROM dbo.Notifications
        WHERE UserID = ?
        ORDER BY CreatedAt DESC
        """,
        (session["user_id"],)
    )

    response = make_response(
        render_template(
            "notifications.html",
            notifications=notifications
        )
    )

    # -----------------------------------------------------
    # PREVENT BROWSER CACHE
    # -----------------------------------------------------

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response
# =========================================================
# OPEN NOTIFICATION
# =========================================================

@app.route("/notification/<int:notification_id>")
def open_notification(notification_id):

    # -----------------------------------------------------
    # LOGIN CHECK
    # -----------------------------------------------------

    if "user_id" not in session:
        return redirect("/login")

    # -----------------------------------------------------
    # GET NOTIFICATION FOR LOGGED-IN USER
    # -----------------------------------------------------

    notification = db.fetch_one(
        """
        SELECT
            NotificationID,
            UserID,
            TicketID,
            Title,
            Message,
            IsRead,
            CreatedAt
        FROM dbo.Notifications
        WHERE NotificationID = ?
          AND UserID = ?
        """,
        (
            notification_id,
            session["user_id"]
        )
    )

    # -----------------------------------------------------
    # NOTIFICATION NOT FOUND
    # -----------------------------------------------------

    if not notification:
        return redirect("/notifications")

    # -----------------------------------------------------
    # MARK AS READ
    # -----------------------------------------------------

    db.execute(
        """
        UPDATE dbo.Notifications
        SET IsRead = 1
        WHERE NotificationID = ?
          AND UserID = ?
        """,
        (
            notification_id,
            session["user_id"]
        ),
        commit=True
    )

    # -----------------------------------------------------
    # IF NOTIFICATION HAS TICKET
    # -----------------------------------------------------

    if notification.TicketID:

        return redirect(
            url_for(
                "edit_ticket",
                id=notification.TicketID
            )
        )

    # -----------------------------------------------------
    # NO TICKET
    # -----------------------------------------------------

    return redirect("/notifications")

# =========================================================
# EMPLOYEE DASHBOARD
# =========================================================

@app.route("/employee-dashboard")
def employee_dashboard():

    # Login check
    if "user_id" not in session:
        return redirect("/login")

    # Only Employee can access Employee Dashboard
    if session.get("role") != "Employee":
     return redirect("/login")

    user_id = session["user_id"]

    # =====================================================
    # TOTAL TICKETS
    # =====================================================

    total_result = db.fetch_one(
        """
        SELECT COUNT(*) AS Total
        FROM Tickets
        WHERE CreatedBy = ?
        """,
        (user_id,)
    )

    total = total_result.Total if total_result else 0


    # =====================================================
    # OPEN TICKETS
    # =====================================================

    open_result = db.fetch_one(
        """
        SELECT COUNT(*) AS Total
        FROM Tickets
        WHERE CreatedBy = ?
        AND Status = 'Open'
        """,
        (user_id,)
    )

    open_tickets = open_result.Total if open_result else 0


    # =====================================================
    # PENDING TICKETS
    # =====================================================

    pending_result = db.fetch_one(
        """
        SELECT COUNT(*) AS Total
        FROM Tickets
        WHERE CreatedBy = ?
        AND Status = 'Pending'
        """,
        (user_id,)
    )

    pending = pending_result.Total if pending_result else 0


    # =====================================================
    # IN PROGRESS TICKETS
    # =====================================================

    progress_result = db.fetch_one(
        """
        SELECT COUNT(*) AS Total
        FROM Tickets
        WHERE CreatedBy = ?
        AND Status = 'In Progress'
        """,
        (user_id,)
    )

    progress = progress_result.Total if progress_result else 0


    # =====================================================
    # RESOLVED TICKETS
    # =====================================================

    resolved_result = db.fetch_one(
        """
        SELECT COUNT(*) AS Total
        FROM Tickets
        WHERE CreatedBy = ?
        AND Status = 'Resolved'
        """,
        (user_id,)
    )

    resolved = resolved_result.Total if resolved_result else 0


    # =====================================================
    # RECENT TICKETS
    # =====================================================

    recent_tickets = db.fetch_all(
        """
        SELECT
            T.TicketID,
            T.Title,
            T.Status,
            T.Priority,
            U.FullName AS AssignedTo
        FROM Tickets T

        LEFT JOIN Users U
            ON T.AssignedTo = U.UserID

        WHERE T.CreatedBy = ?

        ORDER BY T.TicketID DESC
        """,
        (user_id,)
    )


    # =====================================================
    # RENDER EMPLOYEE DASHBOARD
    # =====================================================

    return render_template(
        "employee_dashboard.html",
        total=total,
        open_tickets=open_tickets,
        pending=pending,
        progress=progress,
        resolved=resolved,
        recent_tickets=recent_tickets
    )

# =========================================================
# SUPPORT DASHBOARD
# =========================================================

@app.route("/support-dashboard")
def support_dashboard():

    if "user_id" not in session:
        return redirect("/login")

    tickets = db.fetch_all(
        """
        SELECT
            TicketID,
            Title,
            Status,
            Priority
        FROM Tickets
        WHERE AssignedTo=?
        ORDER BY TicketID DESC
        """,
        (session["user_id"],)
    )

    # Unread notifications for logged-in Support Engineer
    unread_notifications = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Notifications
        WHERE UserID = ?
          AND IsRead = 0
        """,
        (session["user_id"],)
    )

    return render_template(
        "support_dashboard.html",
        tickets=tickets,
        unread_notifications=unread_notifications
    )


# =========================================================
# CREATE TICKET
# =========================================================
@app.route("/create-ticket", methods=["GET", "POST"])
def create_ticket():

    # =====================================================
    # 1. LOGIN CHECK
    # =====================================================

    if "user_id" not in session:
        return redirect("/login")

    # =====================================================
    # 2. ONLY EMPLOYEE CAN CREATE TICKET
    # =====================================================

    if session.get("role") != "Employee":
        return redirect("/login")

    # =====================================================
    # 3. GET CATEGORIES
    # =====================================================

    categories = db.fetch_all(
        """
        SELECT
            MIN(CategoryID) AS CategoryID,
            CategoryName
        FROM Categories
        GROUP BY CategoryName
        ORDER BY CategoryName
        """
    )

    # =====================================================
    # 4. GET REQUEST
    # =====================================================

    if request.method == "GET":

        return render_template(
            "create_ticket.html",
            categories=categories
        )

    # =====================================================
    # 5. GET FORM DATA
    # =====================================================

    title = request.form.get("title", "").strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    priority = request.form.get("priority")

    category_id = request.form.get(
        "category_id"
    )

    # =====================================================
    # 6. VALIDATION - TITLE
    # =====================================================

    if not title:

        return render_template(
            "create_ticket.html",
            categories=categories,
            error="Please enter ticket title."
        )

    # =====================================================
    # 7. VALIDATION - DESCRIPTION
    # =====================================================

    if not description:

        return render_template(
            "create_ticket.html",
            categories=categories,
            error="Please enter ticket description."
        )

    # =====================================================
    # 8. VALIDATION - PRIORITY
    # =====================================================

    if not priority:

        return render_template(
            "create_ticket.html",
            categories=categories,
            error="Please select ticket priority."
        )

    # =====================================================
    # 9. VALIDATION - CATEGORY
    # =====================================================

    if not category_id:

        return render_template(
            "create_ticket.html",
            categories=categories,
            error="Please select ticket category."
        )

    # =====================================================
    # 10. CREATE TICKET
    # =====================================================

    try:

        # =================================================
        # INSERT NEW TICKET
        # =================================================

        db.execute(
            """
            INSERT INTO Tickets
            (
                Title,
                Description,
                Status,
                Priority,
                CreatedBy,
                CategoryID,
                CreatedDate
            )
            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                GETDATE()
            )
            """,
            (
                title,
                description,
                "Open",
                priority,
                session["user_id"],
                int(category_id)
            ),
            commit=True
        )

        # =================================================
        # 11. GET NEWLY CREATED TICKET ID
        # =================================================

        new_ticket = db.fetch_one(
            """
            SELECT TOP 1
                TicketID
            FROM Tickets
            WHERE CreatedBy = ?
            ORDER BY TicketID DESC
            """,
            (
                session["user_id"],
            )
        )

        # =================================================
        # 12. CHECK TICKET ID
        # =================================================

        if new_ticket:

            ticket_id = new_ticket.TicketID

            # =============================================
            # 13. GET ALL ADMIN USERS
            # =============================================

            admin_users = db.fetch_all(
                """
                SELECT
                    UserID
                FROM Users
                WHERE Role = 'Admin'
                """
            )

            # =============================================
            # 14. CREATE NOTIFICATION FOR ADMINS
            # =============================================

            for admin in admin_users:

                db.execute(
                    """
                    INSERT INTO Notifications
                    (
                        UserID,
                        TicketID,
                        Title,
                        Message,
                        IsRead,
                        CreatedAt
                    )
                    VALUES
                    (
                        ?,
                        ?,
                        ?,
                        ?,
                        0,
                        GETDATE()
                    )
                    """,
                    (
                        admin.UserID,
                        ticket_id,
                        "New Ticket Created",
                        f"A new support ticket #{ticket_id} has been created and requires attention."
                    ),
                    commit=True
                )

            # =============================================
            # 15. PRINT SUCCESS
            # =============================================

            print(
                "========================================"
            )

            print(
                "TICKET CREATED SUCCESSFULLY"
            )

            print(
                "Ticket ID:",
                ticket_id
            )

            print(
                "Notifications created for Admins"
            )

            print(
                "========================================"
            )

        else:

            print(
                "Ticket created but TicketID not found."
            )

        # =================================================
        # 16. REDIRECT EMPLOYEE
        # =================================================

        return redirect(
            "/employee-dashboard"
        )

    # =====================================================
    # 17. ERROR HANDLING
    # =====================================================

    except Exception as e:

        print(
            "========================================"
        )

        print(
            "CREATE TICKET ERROR:",
            e
        )

        print(
            "========================================"
        )

        return render_template(
            "create_ticket.html",
            categories=categories,
            error="Unable to create ticket. Please try again."
        )

# =========================================================
# VIEW TICKETS
# =========================================================

@app.route("/view-tickets")
def view_tickets():

    if "user_id" not in session:
        return redirect("/login")

    search = request.args.get("search")
    status = request.args.get("status")

    query = """
        SELECT
            T.TicketID,
            T.Title,
            T.Status,
            T.Priority,
            U.FullName AS AssignedTo
        FROM Tickets T
        LEFT JOIN Users U
            ON T.AssignedTo = U.UserID
        WHERE 1=1
    """

    params = []

    if search:

        query += """
            AND T.Title LIKE ?
        """

        params.append(
            "%" + search + "%"
        )

    if status:

        query += """
            AND T.Status = ?
        """

        params.append(status)

    query += """
        ORDER BY T.TicketID DESC
    """

    tickets = db.fetch_all(
        query,
        tuple(params)
    )

    return render_template(
        "view_tickets.html",
        tickets=tickets,
        search=search,
        status=status
    )

# =========================================================
# ASSIGN TICKET
# =========================================================

@app.route("/assign-ticket/<int:id>", methods=["GET", "POST"])
def assign_ticket(id):

    # Login Check
    if "user_id" not in session or session.get("role") != "Admin":
     return redirect("/login")

    # Assign Ticket
    if request.method == "POST":

        support_id = request.form.get("support")

        # Validate support engineer selection
        if not support_id:
            return redirect(f"/assign-ticket/{id}")

        # Get ticket details
        ticket = db.fetch_one(
            """
            SELECT TicketID, Title
            FROM Tickets
            WHERE TicketID=?
            """,
            (id,)
        )

        # Check ticket exists
        if not ticket:
            return redirect("/view-tickets")

        # Update ticket assignment
        db.execute(
            """
            UPDATE Tickets
            SET AssignedTo=?
            WHERE TicketID=?
            """,
            (
                int(support_id),
                id
            ),
            commit=True
        )

        # Create notification for Support Engineer
        db.execute(
            """
            INSERT INTO Notifications
            (
                UserID,
                TicketID,
                Title,
                Message,
                IsRead,
                CreatedAt
            )
            VALUES (?, ?, ?, ?, 0, GETDATE())
            """,
            (
                int(support_id),
                ticket.TicketID,
                "New Ticket Assigned",
                f"Ticket #{ticket.TicketID} - {ticket.Title} has been assigned to you."
            ),
            commit=True
        )

        return redirect("/view-tickets")

    # Ticket Details
    ticket = db.fetch_one(
        """
        SELECT *
        FROM Tickets
        WHERE TicketID=?
        """,
        (id,)
    )

    # Ticket not found
    if not ticket:
        return redirect("/view-tickets")

    # Get Support Engineers
    supports = db.fetch_all(
        """
        SELECT UserID,
               FullName
        FROM Users
        WHERE Role='Support'
        ORDER BY FullName
        """
    )

    return render_template(
        "assign_ticket.html",
        ticket=ticket,
        supports=supports
    )

# =========================================================
# SUPPORT TICKET
# =========================================================

@app.route(
    "/support-ticket/<int:id>",
    methods=["GET", "POST"]
)
def support_ticket(id):

    if "user_id" not in session:
        return redirect("/login")

    # Only Support Engineer can access
    if session.get("role") != "Support":
        return redirect("/login")

    # =========================
    # GET TICKET
    # =========================

    ticket = db.fetch_one(
        """
        SELECT *
        FROM Tickets
        WHERE TicketID=?
          AND AssignedTo=?
        """,
        (
            id,
            session["user_id"]
        )
    )

    # Ticket is not assigned to this Support Engineer
    if not ticket:
        return redirect("/support-dashboard")

    # =========================
    # UPDATE TICKET
    # =========================

    if request.method == "POST":

        status = request.form.get("status")
        comment = request.form.get("comment")

        db.execute(
            """
            UPDATE Tickets
            SET Status=?
            WHERE TicketID=?
              AND AssignedTo=?
            """,
            (
                status,
                id,
                session["user_id"]
            ),
            commit=True
        )

        # =========================
        # ADD COMMENT
        # =========================

        if comment and comment.strip():

            db.execute(
                """
                INSERT INTO TicketComments
                (
                    TicketID,
                    UserID,
                    Comment
                )
                VALUES
                (
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    id,
                    session["user_id"],
                    comment.strip()
                ),
                commit=True
            )

        return redirect(
            f"/support-ticket/{id}"
        )

    # =========================
    # GET COMMENTS
    # =========================

    comments = db.fetch_all(
        """
        SELECT
            TC.Comment,
            TC.CreatedAt,
            U.FullName
        FROM TicketComments TC
        JOIN Users U
            ON TC.UserID = U.UserID
        WHERE TC.TicketID=?
        ORDER BY TC.CreatedAt DESC
        """,
        (id,)
    )

    return render_template(
        "support_ticket.html",
        ticket=ticket,
        comments=comments
    )
# =========================================================
# USER MANAGEMENT
# =========================================================

@app.route("/users")
def users():

    if "user_id" not in session:
        return redirect("/login")

    # Only Admin can manage users
    if session.get("role") != "Admin":
        return redirect("/dashboard")

    search = request.args.get("search", "")

    if search:

        users_list = db.fetch_all(
            """
            SELECT
                UserID,
                FullName,
                Email,
                Role
            FROM Users
            WHERE
                FullName LIKE ?
                OR Email LIKE ?
                OR Role LIKE ?
            ORDER BY UserID DESC
            """,
            (
                f"%{search}%",
                f"%{search}%",
                f"%{search}%"
            )
        )

    else:

        users_list = db.fetch_all(
            """
            SELECT
                UserID,
                FullName,
                Email,
                Role
            FROM Users
            ORDER BY UserID DESC
            """
        )

    return render_template(
        "users.html",
        users=users_list
    )
# =========================================================
# CREATE NEW USER
# =========================================================

@app.route("/create-user", methods=["GET", "POST"])
def create_user():

    # Login check
    if "user_id" not in session:
        return redirect("/login")

    # Only Admin can create users
    if session.get("role") != "Admin":
        return redirect("/login")

    # =========================
    # GET REQUEST
    # =========================

    if request.method == "GET":

        return render_template(
            "create_user.html"
        )

    # =========================
    # POST REQUEST
    # =========================

    fullname = request.form.get("fullname", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "").strip()

    # =========================
    # VALIDATION
    # =========================

    if not fullname:
        return render_template(
            "create_user.html",
            error="Please enter full name."
        )

    if not email:
        return render_template(
            "create_user.html",
            error="Please enter email."
        )

    if not password:
        return render_template(
            "create_user.html",
            error="Please enter password."
        )

    if role not in ["Employee", "Support"]:
        return render_template(
            "create_user.html",
            error="Please select a valid role."
        )

    # =========================
    # CHECK DUPLICATE EMAIL
    # =========================

    existing_user = db.fetch_one(
        """
        SELECT UserID
        FROM Users
        WHERE Email=?
        """,
        (email,)
    )

    if existing_user:

        return render_template(
            "create_user.html",
            error="Email already registered."
        )

    # =========================
    # INSERT USER
    # =========================

    try:

        db.execute(
            """
            INSERT INTO Users
            (
                FullName,
                Email,
                PasswordHash,
                Role
            )
            VALUES
            (
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                fullname,
                email,
                password,
                role
            ),
            commit=True
        )

        flash("User created successfully!", "success")
        return redirect("/users")


    except Exception as e:

        print(
            "Create User Error:",
            e
        )

        return render_template(
            "create_user.html",
            error="Unable to create user. Please try again."
        )

# =========================================================
# EDIT USER
# =========================================================

@app.route(
    "/edit-user/<int:id>",
    methods=["GET", "POST"]
)
def edit_user(id):

    if "user_id" not in session:
        return redirect("/login")

        # Only Admin can edit users
    if session.get("role") != "Admin":
        return redirect("/login")
    
    if request.method == "POST":

        fullname = request.form.get("fullname")
        email = request.form.get("email")
        role = request.form.get("role")

        db.execute(
            """
            UPDATE Users
            SET
                FullName=?,
                Email=?,
                Role=?
            WHERE UserID=?
            """,
            (
                fullname,
                email,
                role,
                id
            ),
            commit=True
        )
        flash("User updated successfully!", "success")

        return redirect(
            "/users"
        )

    user = db.fetch_one(
        """
        SELECT
            UserID,
            FullName,
            Email,
            Role
        FROM Users
        WHERE UserID=?
        """,
        (id,)
    )

    if not user:
        return redirect(
            "/users"
        )

    return render_template(
        "edit_user.html",
        user=user
    )


# =========================================================
# DELETE USER
# =========================================================

@app.route(
    "/delete-user/<int:id>"
)
def delete_user(id):

    if "user_id" not in session:
        return redirect("/login")

        # Only Admin can delete users
    if session.get("role") != "Admin":
        return redirect("/login")
    
    try:

        db.execute(
            """
            DELETE FROM Users
            WHERE UserID=?
            """,
            (id,),
            commit=True
        )
        flash("User deleted successfully!", "success")

    except Exception as e:

        print(
            "Delete User Error:",
            e
        )

    return redirect(
        "/users"
    )


# =========================================================
# EDIT TICKET
# =========================================================

@app.route(
    "/edit-ticket/<int:id>",
    methods=["GET", "POST"]
)
def edit_ticket(id):

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        title = request.form.get("title")
        description = request.form.get("description")
        priority = request.form.get("priority")
        status = request.form.get("status")

        db.execute(
            """
            UPDATE Tickets
            SET
                Title=?,
                Description=?,
                Priority=?,
                Status=?
            WHERE TicketID=?
            """,
            (
                title,
                description,
                priority,
                status,
                id
            ),
            commit=True
        )

        return redirect(
            "/view-tickets"
        )

    ticket = db.fetch_one(
        """
        SELECT *
        FROM Tickets
        WHERE TicketID=?
        """,
        (id,)
    )

    return render_template(
        "edit_ticket.html",
        ticket=ticket
    )


# =========================================================
# DELETE TICKET
# =========================================================

@app.route(
    "/delete-ticket/<int:id>"
)
def delete_ticket(id):

    if "user_id" not in session:
        return redirect("/login")

    try:

        db.execute(
            """
            DELETE FROM Tickets
            WHERE TicketID=?
            """,
            (id,),
            commit=True
        )

    except Exception as e:

        print(
            "Delete Ticket Error:",
            e
        )

    return redirect(
        "/view-tickets"
    )


# =========================================================
# REPORTS
# =========================================================

@app.route("/reports")
def reports():

    if "user_id" not in session:
        return redirect("/login")

    total = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        """
    )

    open_tickets = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Status='Open'
        """
    )

    pending = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Status='Pending'
        """
    )

    progress = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Status='In Progress'
        """
    )

    resolved = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Status='Resolved'
        """
    )

    high = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Priority='High'
        """
    )

    medium = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Priority='Medium'
        """
    )

    low = db.fetch_scalar(
        """
        SELECT COUNT(*)
        FROM Tickets
        WHERE Priority='Low'
        """
    )

    return render_template(
        "reports.html",
        total=total,
        open_tickets=open_tickets,
        pending=pending,
        progress=progress,
        resolved=resolved,
        high=high,
        medium=medium,
        low=low
    )

# =========================================================
# SETTINGS
# =========================================================

@app.route("/settings", methods=["GET", "POST"])
def settings():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    message = None
    error = None

    # -----------------------------------------------------
    # POST - SAVE SETTINGS
    # -----------------------------------------------------

    if request.method == "POST":

        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip()

        theme = request.form.get(
            "theme",
            "Light"
        )

        current_password = request.form.get(
            "current_password",
            ""
        ).strip()

        new_password = request.form.get(
            "new_password",
            ""
        ).strip()


        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not fullname or not email:

            error = "Full Name and Email are required."

        else:

            try:

                # -----------------------------------------
                # UPDATE PROFILE
                # -----------------------------------------

                db.execute(
                    """
                    UPDATE Users
                    SET
                        FullName=?,
                        Email=?
                    WHERE UserID=?
                    """,
                    (
                        fullname,
                        email,
                        user_id
                    ),
                    commit=True
                )


                # -----------------------------------------
                # UPDATE SESSION NAME
                # -----------------------------------------

                session["user_name"] = fullname


                # -----------------------------------------
                # SAVE THEME
                # -----------------------------------------

                session["theme"] = theme


                # -----------------------------------------
                # CHANGE PASSWORD
                # -----------------------------------------

                if current_password or new_password:

                    if not current_password or not new_password:

                        error = (
                            "Enter both current password "
                            "and new password."
                        )

                    else:

                        password_user = db.fetch_one(
                            """
                            SELECT PasswordHash
                            FROM Users
                            WHERE UserID=?
                            """,
                            (user_id,)
                        )


                        if password_user:

                            stored_password = (
                                password_user.PasswordHash
                            )


                            # Check current password

                            if stored_password == current_password:

                                db.execute(
                                    """
                                    UPDATE Users
                                    SET PasswordHash=?
                                    WHERE UserID=?
                                    """,
                                    (
                                        new_password,
                                        user_id
                                    ),
                                    commit=True
                                )

                                message = (
                                    "Profile, theme and password "
                                    "updated successfully."
                                )

                            else:

                                error = (
                                    "Current password is incorrect."
                                )

                        else:

                            error = "User not found."

                else:

                    message = (
                        "Settings updated successfully."
                    )


            except Exception as e:

                print(
                    "Settings Error:",
                    e
                )

                error = (
                    "Unable to update settings. "
                    "Please try again."
                )


    # -----------------------------------------------------
    # GET UPDATED USER
    # -----------------------------------------------------

    user = db.fetch_one(
        """
        SELECT
            UserID,
            FullName,
            Email,
            Role
        FROM Users
        WHERE UserID=?
        """,
        (user_id,)
    )


    # -----------------------------------------------------
    # CURRENT THEME
    # -----------------------------------------------------

    theme = session.get(
        "theme",
        "Light"
    )


    return render_template(
        "settings.html",

        user=user,

        message=message,

        error=error,

        theme=theme
    )


## =========================================================
# EMPLOYEE VIEW TICKET
# =========================================================

@app.route("/employee-ticket/<int:id>")
def employee_ticket(id):

    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") != "Employee":
        return redirect("/login")

    # Get ticket details
    ticket = db.fetch_one(
        """
        SELECT
            t.TicketID,
            t.Title,
            t.Description,
            t.Status,
            t.Priority,
            t.CreatedDate,
            c.CategoryName,
            u.FullName AS AssignedTo
        FROM Tickets t

        LEFT JOIN Categories c
            ON t.CategoryID = c.CategoryID

        LEFT JOIN Users u
            ON t.AssignedTo = u.UserID

        WHERE t.TicketID = ?
          AND t.CreatedBy = ?
        """,
        (
            id,
            session["user_id"]
        )
    )

    if not ticket:
        return "Ticket Not Found", 404

    # Get comments / updates for this ticket
    comments = db.fetch_all(
        """
        SELECT
            tc.Comment,
            tc.CreatedAt,
            u.FullName AS CommentBy
        FROM TicketComments tc

        LEFT JOIN Users u
            ON tc.UserID = u.UserID

        WHERE tc.TicketID = ?

        ORDER BY tc.CreatedAt ASC
        """,
        (id,)
    )

    return render_template(
        "employee_ticket.html",
        ticket=ticket,
        comments=comments
    )
# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )