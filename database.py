"""
Database layer for the IT Help Desk Ticket Management System.
Handles SQL Server connections and query execution via pyodbc.
"""

import pyodbc
from typing import Any, List, Optional, Tuple


class DatabaseError(Exception):
    """Raised when a database operation fails."""

    pass


class Database:
    """Manages Microsoft SQL Server connections and query execution."""

    SERVER = "localhost"
    DATABASE = "HelpDeskDB"
    DRIVERS = (
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server",
    )

    def __init__(self) -> None:
        self._connection: Optional[pyodbc.Connection] = None
        self._cursor: Optional[pyodbc.Cursor] = None

    def _build_connection_string(self, driver: str) -> str:
        """Build a connection string for the given ODBC driver."""
        parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={self.SERVER}",
            f"DATABASE={self.DATABASE}",
            "Trusted_Connection=yes",
        ]
        if "18" in driver:
            parts.append("TrustServerCertificate=yes")
        return ";".join(parts) + ";"

    def connect(self) -> None:
        """Establish a connection to SQL Server using Windows Authentication."""
        if self._connection is not None:
            return

        last_error: Optional[Exception] = None
        for driver in self.DRIVERS:
            try:
                conn_str = self._build_connection_string(driver)
                self._connection = pyodbc.connect(conn_str, autocommit=False)
                self._cursor = self._connection.cursor()
                return
            except pyodbc.Error as exc:
                last_error = exc
                self._connection = None
                self._cursor = None

        raise DatabaseError(
            "Unable to connect to SQL Server. "
            "Ensure SQL Server is running and an ODBC driver is installed."
        ) from last_error

    def disconnect(self) -> None:
        """Close the cursor and connection."""
        try:
            if self._cursor is not None:
                self._cursor.close()
        finally:
            self._cursor = None

        try:
            if self._connection is not None:
                self._connection.close()
        finally:
            self._connection = None

    def is_connected(self) -> bool:
        """Return True if an active connection exists."""
        return self._connection is not None

    def _ensure_connected(self) -> None:
        """Connect if not already connected."""
        if not self.is_connected():
            self.connect()

    def execute(
        self,
        query: str,
        params: Optional[Tuple[Any, ...]] = None,
        commit: bool = False,
    ) -> None:
        """
        Execute a SQL statement (INSERT, UPDATE, DELETE).

        Args:
            query: SQL statement with optional parameter placeholders.
            params: Tuple of values bound to placeholders.
            commit: When True, commit the transaction after execution.
        """
        self._ensure_connected()
        try:
            if params:
                self._cursor.execute(query, params)
            else:
                self._cursor.execute(query)
            if commit:
                self._connection.commit()
        except pyodbc.Error as exc:
            if self._connection is not None:
                self._connection.rollback()
            raise DatabaseError(f"Query execution failed: {exc}") from exc

    def fetch_one(
        self,
        query: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> Optional[pyodbc.Row]:
        """Execute a SELECT and return a single row, or None."""
        self._ensure_connected()
        try:
            if params:
                self._cursor.execute(query, params)
            else:
                self._cursor.execute(query)
            return self._cursor.fetchone()
        except pyodbc.Error as exc:
            raise DatabaseError(f"Fetch failed: {exc}") from exc

    def fetch_all(
        self,
        query: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> List[pyodbc.Row]:
        """Execute a SELECT and return all matching rows."""
        self._ensure_connected()
        try:
            if params:
                self._cursor.execute(query, params)
            else:
                self._cursor.execute(query)
            return self._cursor.fetchall()
        except pyodbc.Error as exc:
            raise DatabaseError(f"Fetch failed: {exc}") from exc

    def fetch_scalar(
        self,
        query: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> Any:
        """Execute a SELECT and return the first column of the first row."""
        row = self.fetch_one(query, params)
        return row[0] if row is not None else None

    def commit(self) -> None:
        """Commit the current transaction."""
        self._ensure_connected()
        try:
            self._connection.commit()
        except pyodbc.Error as exc:
            raise DatabaseError(f"Commit failed: {exc}") from exc

    def rollback(self) -> None:
        """Roll back the current transaction."""
        if self._connection is not None:
            try:
                self._connection.rollback()
            except pyodbc.Error as exc:
                raise DatabaseError(f"Rollback failed: {exc}") from exc

    def get_last_insert_id(self) -> Optional[int]:
        """
        Return the identity value from the most recent INSERT on this connection.
        Must be called immediately after an INSERT on the same connection.
        """
        return self.fetch_scalar("SELECT CAST(SCOPE_IDENTITY() AS INT);")

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None and self._connection is not None:
            self.rollback()
        self.disconnect()


# Shared application database instance
db = Database()
