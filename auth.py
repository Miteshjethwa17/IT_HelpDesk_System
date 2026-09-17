"""
Authentication and authorization module for the IT Help Desk System.
Handles user login, registration, password hashing, and role-based access.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import List, Optional

from database import Database, DatabaseError, db


class AuthError(Exception):
    """Raised when authentication or authorization fails."""

    pass


class Role:
    """Application role constants."""

    ADMIN = "Admin"
    SUPPORT_AGENT = "Support Agent"
    EMPLOYEE = "Employee"

    ALL = (ADMIN, SUPPORT_AGENT, EMPLOYEE)


@dataclass
class User:
    """Represents an authenticated application user."""

    user_id: int
    full_name: str
    email: str
    role: str

    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def is_support_agent(self) -> bool:
        return self.role == Role.SUPPORT_AGENT

    def is_employee(self) -> bool:
        return self.role == Role.EMPLOYEE

    def can_manage_users(self) -> bool:
        return self.is_admin()

    def can_manage_all_tickets(self) -> bool:
        return self.is_admin() or self.is_support_agent()

    def can_assign_tickets(self) -> bool:
        return self.is_admin() or self.is_support_agent()

    def can_delete_tickets(self) -> bool:
        return self.is_admin()

    def __str__(self) -> str:
        return f"{self.full_name} ({self.role})"


class PasswordHasher:
    """Handles secure password hashing and verification."""

    @staticmethod
    def hash_password(password: str) -> str:
        """Return a salted SHA-256 hash in 'salt:hash' format."""
        salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
        return f"{salt}:{digest}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        """Verify a plain-text password against a stored hash."""
        try:
            salt, expected = stored_hash.split(":", 1)
        except ValueError:
            return False
        digest = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
        return secrets.compare_digest(digest, expected)


class AuthService:
    """Provides authentication and user management operations."""

    EMAIL_PATTERN = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

    def __init__(self, database: Database = db) -> None:
        self._db = database
        self._current_user: Optional[User] = None

    @property
    def current_user(self) -> Optional[User]:
        return self._current_user

    def is_logged_in(self) -> bool:
        return self._current_user is not None

    def logout(self) -> None:
        self._current_user = None

    def require_login(self) -> User:
        """Return the current user or raise AuthError if not logged in."""
        if self._current_user is None:
            raise AuthError("You must be logged in to perform this action.")
        return self._current_user

    def require_role(self, *roles: str) -> User:
        """Return the current user if their role is allowed, else raise AuthError."""
        user = self.require_login()
        if user.role not in roles:
            raise AuthError(
                f"Access denied. Required role(s): {', '.join(roles)}."
            )
        return user

    def _row_to_user(self, row) -> User:
        return User(
            user_id=row.UserID,
            full_name=row.FullName,
            email=row.Email,
            role=row.Role,
        )

    def _validate_email(self, email: str) -> None:
        email = email.strip()
        if not email:
            raise AuthError("Email is required.")
        if not self.EMAIL_PATTERN.match(email):
            raise AuthError("Invalid email format.")

    def _validate_password(self, password: str) -> None:
        if not password:
            raise AuthError("Password is required.")
        if len(password) < 6:
            raise AuthError("Password must be at least 6 characters long.")

    def _validate_full_name(self, full_name: str) -> None:
        if not full_name or not full_name.strip():
            raise AuthError("Full name is required.")
        if len(full_name.strip()) > 100:
            raise AuthError("Full name must not exceed 100 characters.")

    def _validate_role(self, role: str) -> None:
        if role not in Role.ALL:
            raise AuthError(
                f"Invalid role. Choose one of: {', '.join(Role.ALL)}."
            )

    def email_exists(self, email: str) -> bool:
        """Check whether an email is already registered."""
        count = self._db.fetch_scalar(
            "SELECT COUNT(*) FROM Users WHERE Email = ?;",
            (email.strip().lower(),),
        )
        return count > 0

    def login(self, email: str, password: str) -> User:
        """
        Authenticate a user by email and password.

        Returns:
            User object on success.

        Raises:
            AuthError: If credentials are invalid.
        """
        self._validate_email(email)
        self._validate_password(password)

        try:
            row = self._db.fetch_one(
                """
                SELECT UserID, FullName, Email, PasswordHash, Role
                FROM Users
                WHERE Email = ?;
                """,
                (email.strip().lower(),),
            )
        except DatabaseError as exc:
            raise AuthError("Login failed due to a database error.") from exc

        if row is None:
            raise AuthError("Invalid email or password.")

        if password != row.PasswordHash:
         raise AuthError("Invalid email or password.")

        user = self._row_to_user(row)
        self._current_user = user
        return user

    def register(
        self,
        full_name: str,
        email: str,
        password: str,
        role: str = Role.EMPLOYEE,
    ) -> User:
        """
        Register a new user account.

        Returns:
            The newly created User object.

        Raises:
            AuthError: If validation fails or email already exists.
        """
        self._validate_full_name(full_name)
        self._validate_email(email)
        self._validate_password(password)
        self._validate_role(role)

        normalized_email = email.strip().lower()

        if self.email_exists(normalized_email):
            raise AuthError("An account with this email already exists.")

        password_hash = PasswordHasher.hash_password(password)

        try:
            self._db.execute(
                """
                INSERT INTO Users (FullName, Email, PasswordHash, Role)
                VALUES (?, ?, ?, ?);
                """,
                (full_name.strip(), normalized_email, password_hash, role),
                commit=True,
            )
            user_id = self._db.get_last_insert_id()
            if user_id is None:
                raise AuthError("Registration failed. Could not retrieve user ID.")

            user = User(
                user_id=user_id,
                full_name=full_name.strip(),
                email=normalized_email,
                role=role,
            )
            return user
        except DatabaseError as exc:
            raise AuthError(f"Registration failed: {exc}") from exc

    def register_by_admin(
        self,
        full_name: str,
        email: str,
        password: str,
        role: str,
    ) -> User:
        """Register a user (admin-only). Any role may be assigned."""
        self.require_role(Role.ADMIN)
        return self.register(full_name, email, password, role)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Fetch a user by ID without changing the current session."""
        try:
            row = self._db.fetch_one(
                """
                SELECT UserID, FullName, Email, Role
                FROM Users
                WHERE UserID = ?;
                """,
                (user_id,),
            )
        except DatabaseError as exc:
            raise AuthError(f"Unable to fetch user: {exc}") from exc

        if row is None:
            return None
        return self._row_to_user(row)

    def get_all_users(self) -> List[User]:
        """Return all registered users (admin-only)."""
        self.require_role(Role.ADMIN)
        try:
            rows = self._db.fetch_all(
                """
                SELECT UserID, FullName, Email, Role
                FROM Users
                ORDER BY FullName;
                """
            )
        except DatabaseError as exc:
            raise AuthError(f"Unable to fetch users: {exc}") from exc

        return [self._row_to_user(row) for row in rows]

    def get_support_agents(self) -> List[User]:
        """Return all users with the Support Agent role."""
        try:
            rows = self._db.fetch_all(
                """
                SELECT UserID, FullName, Email, Role
                FROM Users
                WHERE Role = ?;
                ORDER BY FullName;
                """,
                (Role.SUPPORT_AGENT,),
            )
        except DatabaseError as exc:
            raise AuthError(f"Unable to fetch support agents: {exc}") from exc

        return [self._row_to_user(row) for row in rows]

    def change_password(
        self,
        current_password: str,
        new_password: str,
    ) -> None:
        """Change the logged-in user's password."""
        user = self.require_login()
        self._validate_password(new_password)

        try:
            row = self._db.fetch_one(
                "SELECT PasswordHash FROM Users WHERE UserID = ?;",
                (user.user_id,),
            )
        except DatabaseError as exc:
            raise AuthError(f"Unable to verify password: {exc}") from exc

        if row is None or not PasswordHasher.verify_password(
            current_password, row.PasswordHash
        ):
            raise AuthError("Current password is incorrect.")

        new_hash = PasswordHasher.hash_password(new_password)
        try:
            self._db.execute(
                "UPDATE Users SET PasswordHash = ? WHERE UserID = ?;",
                (new_hash, user.user_id),
                commit=True,
            )
        except DatabaseError as exc:
            raise AuthError(f"Password update failed: {exc}") from exc


# Shared authentication service instance
auth = AuthService()
