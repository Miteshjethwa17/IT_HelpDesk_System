"""
Ticket management module for the IT Help Desk System.
Handles creating, viewing, updating, deleting, searching, and filtering tickets.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from auth import AuthService, User, auth
from database import Database, DatabaseError, db


class TicketError(Exception):
    """Raised when a ticket operation fails."""

    pass


class TicketStatus:
    """Valid ticket status values."""

    OPEN = "Open"
    ASSIGNED = "Assigned"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"
    CLOSED = "Closed"

    ALL = (OPEN, ASSIGNED, IN_PROGRESS, RESOLVED, CLOSED)


class TicketPriority:
    """Valid ticket priority values."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"

    ALL = (LOW, MEDIUM, HIGH, CRITICAL)


@dataclass
class Ticket:
    """Represents a help desk ticket."""

    ticket_id: int
    title: str
    description: Optional[str]
    status: str
    priority: str
    created_by: int
    category_id: Optional[int]
    created_date: Optional[datetime]
    creator_name: Optional[str] = None
    category_name: Optional[str] = None
    assigned_to: Optional[int] = None
    assignee_name: Optional[str] = None

    def __str__(self) -> str:
        created = (
            self.created_date.strftime("%Y-%m-%d %H:%M")
            if self.created_date
            else "N/A"
        )
        category = self.category_name or "Uncategorized"
        return (
            f"[#{self.ticket_id}] {self.title} | {self.status} | "
            f"{self.priority} | {category} | Created: {created}"
        )


class TicketService:
    """Provides ticket CRUD, search, and filter operations."""

    BASE_SELECT = """
        SELECT
            t.TicketID,
            t.Title,
            t.Description,
            t.Status,
            t.Priority,
            t.CreatedBy,
            t.CategoryID,
            t.CreatedDate,
            u.FullName AS CreatorName,
            c.CategoryName,
            a.AssignedTo,
            au.FullName AS AssigneeName
        FROM Tickets t
        LEFT JOIN Users u ON t.CreatedBy = u.UserID
        LEFT JOIN Categories c ON t.CategoryID = c.CategoryID
        LEFT JOIN Assignments a ON t.TicketID = a.TicketID
        LEFT JOIN Users au ON a.AssignedTo = au.UserID
    """

    def __init__(
        self,
        database: Database = db,
        auth_service: AuthService = auth,
    ) -> None:
        self._db = database
        self._auth = auth_service

    def _row_to_ticket(self, row) -> Ticket:
        return Ticket(
            ticket_id=row.TicketID,
            title=row.Title,
            description=row.Description,
            status=row.Status,
            priority=row.Priority,
            created_by=row.CreatedBy,
            category_id=row.CategoryID,
            created_date=row.CreatedDate,
            creator_name=row.CreatorName,
            category_name=row.CategoryName,
            assigned_to=row.AssignedTo,
            assignee_name=row.AssigneeName,
        )

    def _validate_title(self, title: str) -> None:
        if not title or not title.strip():
            raise TicketError("Title is required.")
        if len(title.strip()) > 200:
            raise TicketError("Title must not exceed 200 characters.")

    def _validate_description(self, description: Optional[str]) -> None:
        if description is not None and len(description) > 8000:
            raise TicketError("Description must not exceed 8000 characters.")

    def _validate_status(self, status: str) -> None:
        if status not in TicketStatus.ALL:
            raise TicketError(
                f"Invalid status. Choose one of: {', '.join(TicketStatus.ALL)}."
            )

    def _validate_priority(self, priority: str) -> None:
        if priority not in TicketPriority.ALL:
            raise TicketError(
                f"Invalid priority. Choose one of: {', '.join(TicketPriority.ALL)}."
            )

    def _validate_category_id(self, category_id: int) -> None:
        count = self._db.fetch_scalar(
            "SELECT COUNT(*) FROM Categories WHERE CategoryID = ?;",
            (category_id,),
        )
        if not count:
            raise TicketError(f"Category ID {category_id} does not exist.")

    def _can_access_ticket(self, user: User, ticket: Ticket) -> bool:
        if user.can_manage_all_tickets():
            return True
        return ticket.created_by == user.user_id

    def _require_ticket_access(self, user: User, ticket: Ticket) -> None:
        if not self._can_access_ticket(user, ticket):
            raise TicketError("Access denied. You cannot view or modify this ticket.")

    def get_categories(self) -> List[Tuple[int, str]]:
        """Return all ticket categories as (id, name) tuples."""
        try:
            rows = self._db.fetch_all(
                "SELECT CategoryID, CategoryName FROM Categories ORDER BY CategoryName;"
            )
            return [(row.CategoryID, row.CategoryName) for row in rows]
        except DatabaseError as exc:
            raise TicketError(f"Unable to fetch categories: {exc}") from exc

    def create_ticket(
        self,
        title: str,
        description: str,
        category_id: int,
        priority: str = TicketPriority.MEDIUM,
    ) -> Ticket:
        """
        Create a new ticket for the logged-in user.

        Returns:
            The newly created Ticket object.
        """
        user = self._auth.require_login()
        self._validate_title(title)
        self._validate_description(description)
        self._validate_priority(priority)
        self._validate_category_id(category_id)

        try:
            self._db.execute(
                """
                INSERT INTO Tickets
                    (Title, Description, Status, Priority, CreatedBy, CategoryID, CreatedDate)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE());
                """,
                (
                    title.strip(),
                    description.strip() if description else None,
                    TicketStatus.OPEN,
                    priority,
                    user.user_id,
                    category_id,
                ),
                commit=True,
            )
            ticket_id = self._db.get_last_insert_id()
            if ticket_id is None:
                raise TicketError("Ticket created but ID could not be retrieved.")

            ticket = self.get_ticket_by_id(ticket_id)
            if ticket is None:
                raise TicketError("Ticket created but could not be loaded.")
            return ticket
        except DatabaseError as exc:
            raise TicketError(f"Failed to create ticket: {exc}") from exc

    def get_ticket_by_id(self, ticket_id: int) -> Optional[Ticket]:
        """Fetch a single ticket by ID."""
        try:
            row = self._db.fetch_one(
                f"{self.BASE_SELECT} WHERE t.TicketID = ?;",
                (ticket_id,),
            )
        except DatabaseError as exc:
            raise TicketError(f"Unable to fetch ticket: {exc}") from exc

        if row is None:
            return None
        return self._row_to_ticket(row)

    def view_ticket(self, ticket_id: int) -> Ticket:
        """Fetch a ticket with access control enforced."""
        user = self._auth.require_login()
        ticket = self.get_ticket_by_id(ticket_id)
        if ticket is None:
            raise TicketError(f"Ticket #{ticket_id} not found.")
        self._require_ticket_access(user, ticket)
        return ticket

    def get_all_tickets(self) -> List[Ticket]:
        """
        Return tickets visible to the current user.
        Admins and support agents see all tickets; employees see only their own.
        """
        user = self._auth.require_login()

        try:
            if user.can_manage_all_tickets():
                rows = self._db.fetch_all(
                    f"{self.BASE_SELECT} ORDER BY t.CreatedDate DESC;"
                )
            else:
                rows = self._db.fetch_all(
                    f"{self.BASE_SELECT} WHERE t.CreatedBy = ? ORDER BY t.CreatedDate DESC;",
                    (user.user_id,),
                )
        except DatabaseError as exc:
            raise TicketError(f"Unable to fetch tickets: {exc}") from exc

        return [self._row_to_ticket(row) for row in rows]

    def update_ticket(
        self,
        ticket_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category_id: Optional[int] = None,
    ) -> Ticket:
        """
        Update ticket fields. Employees may update their own open tickets.
        Admins and support agents may update any ticket.
        """
        user = self._auth.require_login()
        ticket = self.get_ticket_by_id(ticket_id)
        if ticket is None:
            raise TicketError(f"Ticket #{ticket_id} not found.")

        self._require_ticket_access(user, ticket)

        if user.is_employee():
            if ticket.created_by != user.user_id:
                raise TicketError("Access denied.")
            if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
                raise TicketError("Cannot update a resolved or closed ticket.")
            if status is not None and status != ticket.status:
                raise TicketError("Employees cannot change ticket status.")

        updates: List[str] = []
        params: List[Any] = []

        if title is not None:
            self._validate_title(title)
            updates.append("Title = ?")
            params.append(title.strip())

        if description is not None:
            self._validate_description(description)
            updates.append("Description = ?")
            params.append(description.strip() if description else None)

        if status is not None:
            self._validate_status(status)
            updates.append("Status = ?")
            params.append(status)

        if priority is not None:
            self._validate_priority(priority)
            updates.append("Priority = ?")
            params.append(priority)

        if category_id is not None:
            self._validate_category_id(category_id)
            updates.append("CategoryID = ?")
            params.append(category_id)

        if not updates:
            raise TicketError("No fields provided to update.")

        params.append(ticket_id)
        query = f"UPDATE Tickets SET {', '.join(updates)} WHERE TicketID = ?;"

        try:
            self._db.execute(query, tuple(params), commit=True)
        except DatabaseError as exc:
            raise TicketError(f"Failed to update ticket: {exc}") from exc

        updated = self.get_ticket_by_id(ticket_id)
        if updated is None:
            raise TicketError("Ticket updated but could not be reloaded.")
        return updated

    def delete_ticket(self, ticket_id: int) -> None:
        """Delete a ticket and related records (admin-only)."""
        user = self._auth.require_login()
        if not user.can_delete_tickets():
            raise TicketError("Access denied. Only admins can delete tickets.")

        ticket = self.get_ticket_by_id(ticket_id)
        if ticket is None:
            raise TicketError(f"Ticket #{ticket_id} not found.")

        try:
            self._db.execute(
                "DELETE FROM Comments WHERE TicketID = ?;",
                (ticket_id,),
            )
            self._db.execute(
                "DELETE FROM Assignments WHERE TicketID = ?;",
                (ticket_id,),
            )
            self._db.execute(
                "DELETE FROM Tickets WHERE TicketID = ?;",
                (ticket_id,),
                commit=True,
            )
        except DatabaseError as exc:
            raise TicketError(f"Failed to delete ticket: {exc}") from exc

    def search_tickets(self, keyword: str) -> List[Ticket]:
        """
        Search tickets by keyword in title or description.
        Respects role-based visibility.
        """
        user = self._auth.require_login()
        if not keyword or not keyword.strip():
            raise TicketError("Search keyword is required.")

        pattern = f"%{keyword.strip()}%"
        base_query = f"""
            {self.BASE_SELECT}
            WHERE (t.Title LIKE ? OR t.Description LIKE ?)
        """
        params: Tuple[Any, ...]

        if user.can_manage_all_tickets():
            query = base_query + " ORDER BY t.CreatedDate DESC;"
            params = (pattern, pattern)
        else:
            query = base_query + " AND t.CreatedBy = ? ORDER BY t.CreatedDate DESC;"
            params = (pattern, pattern, user.user_id)

        try:
            rows = self._db.fetch_all(query, params)
        except DatabaseError as exc:
            raise TicketError(f"Search failed: {exc}") from exc

        return [self._row_to_ticket(row) for row in rows]

    def filter_tickets(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> List[Ticket]:
        """
        Filter tickets by status, priority, category, and/or creator.
        Respects role-based visibility.
        """
        user = self._auth.require_login()

        if status is not None:
            self._validate_status(status)
        if priority is not None:
            self._validate_priority(priority)
        if category_id is not None:
            self._validate_category_id(category_id)

        conditions: List[str] = []
        params: List[Any] = []

        if status is not None:
            conditions.append("t.Status = ?")
            params.append(status)

        if priority is not None:
            conditions.append("t.Priority = ?")
            params.append(priority)

        if category_id is not None:
            conditions.append("t.CategoryID = ?")
            params.append(category_id)

        if created_by is not None:
            conditions.append("t.CreatedBy = ?")
            params.append(created_by)

        if not user.can_manage_all_tickets():
            conditions.append("t.CreatedBy = ?")
            params.append(user.user_id)

        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)

        query = f"{self.BASE_SELECT}{where_clause} ORDER BY t.CreatedDate DESC;"

        try:
            rows = self._db.fetch_all(query, tuple(params) if params else None)
        except DatabaseError as exc:
            raise TicketError(f"Filter failed: {exc}") from exc

        return [self._row_to_ticket(row) for row in rows]

    def get_ticket_count_by_status(self) -> Dict[str, int]:
        """Return ticket counts grouped by status (for dashboard/reports)."""
        try:
            rows = self._db.fetch_all(
                """
                SELECT Status, COUNT(*) AS TicketCount
                FROM Tickets
                GROUP BY Status;
                """
            )
        except DatabaseError as exc:
            raise TicketError(f"Unable to fetch ticket counts: {exc}") from exc

        counts = {status: 0 for status in TicketStatus.ALL}
        for row in rows:
            if row.Status in counts:
                counts[row.Status] = row.TicketCount
        return counts


# Shared ticket service instance
ticket_service = TicketService()
