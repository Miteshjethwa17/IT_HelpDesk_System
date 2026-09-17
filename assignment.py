"""
Assignment management module for the IT Help Desk System.
Handles assigning, reassigning, and viewing ticket assignments.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from auth import AuthService, Role, User, auth
from database import Database, DatabaseError, db
from ticket import TicketStatus


class AssignmentError(Exception):
    """Raised when an assignment operation fails."""

    pass


@dataclass
class Assignment:
    """Represents a ticket assignment record."""

    assignment_id: int
    ticket_id: int
    assigned_to: int
    assigned_date: Optional[datetime]
    ticket_title: Optional[str] = None
    ticket_status: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_email: Optional[str] = None

    def __str__(self) -> str:
        assigned = (
            self.assigned_date.strftime("%Y-%m-%d %H:%M")
            if self.assigned_date
            else "N/A"
        )
        title = self.ticket_title or f"Ticket #{self.ticket_id}"
        assignee = self.assignee_name or f"User #{self.assigned_to}"
        return (
            f"[Assignment #{self.assignment_id}] {title} -> {assignee} "
            f"({assigned})"
        )


class AssignmentService:
    """Provides ticket assignment operations."""

    BASE_SELECT = """
        SELECT
            a.AssignmentID,
            a.TicketID,
            a.AssignedTo,
            a.AssignedDate,
            t.Title AS TicketTitle,
            t.Status AS TicketStatus,
            u.FullName AS AssigneeName,
            u.Email AS AssigneeEmail
        FROM Assignments a
        INNER JOIN Tickets t ON a.TicketID = t.TicketID
        INNER JOIN Users u ON a.AssignedTo = u.UserID
    """

    def __init__(
        self,
        database: Database = db,
        auth_service: AuthService = auth,
    ) -> None:
        self._db = database
        self._auth = auth_service

    def _row_to_assignment(self, row) -> Assignment:
        return Assignment(
            assignment_id=row.AssignmentID,
            ticket_id=row.TicketID,
            assigned_to=row.AssignedTo,
            assigned_date=row.AssignedDate,
            ticket_title=row.TicketTitle,
            ticket_status=row.TicketStatus,
            assignee_name=row.AssigneeName,
            assignee_email=row.AssigneeEmail,
        )

    def _require_assign_permission(self) -> User:
        user = self._auth.require_login()
        if not user.can_assign_tickets():
            raise AssignmentError(
                "Access denied. Only admins and support agents can manage assignments."
            )
        return user

    def _ticket_exists(self, ticket_id: int) -> bool:
        count = self._db.fetch_scalar(
            "SELECT COUNT(*) FROM Tickets WHERE TicketID = ?;",
            (ticket_id,),
        )
        return count > 0

    def _validate_assignee(self, user_id: int) -> User:
        assignee = self._auth.get_user_by_id(user_id)
        if assignee is None:
            raise AssignmentError(f"User ID {user_id} does not exist.")
        if assignee.role not in (Role.SUPPORT_AGENT, Role.ADMIN):
            raise AssignmentError(
                "Tickets can only be assigned to support agents or admins."
            )
        return assignee

    def _get_assignment_by_ticket(self, ticket_id: int) -> Optional[Assignment]:
        try:
            row = self._db.fetch_one(
                f"{self.BASE_SELECT} WHERE a.TicketID = ?;",
                (ticket_id,),
            )
        except DatabaseError as exc:
            raise AssignmentError(f"Unable to fetch assignment: {exc}") from exc

        if row is None:
            return None
        return self._row_to_assignment(row)

    def _update_ticket_status_assigned(self, ticket_id: int) -> None:
        self._db.execute(
            """
            UPDATE Tickets
            SET Status = ?
            WHERE TicketID = ? AND Status = ?;
            """,
            (TicketStatus.ASSIGNED, ticket_id, TicketStatus.OPEN),
        )

    def assign_ticket(self, ticket_id: int, assigned_to: int) -> Assignment:
        """
        Assign a ticket to a support agent or admin.

        Creates a new assignment and sets ticket status to Assigned if currently Open.

        Returns:
            The created Assignment object.

        Raises:
            AssignmentError: If ticket already assigned or validation fails.
        """
        self._require_assign_permission()

        if not self._ticket_exists(ticket_id):
            raise AssignmentError(f"Ticket #{ticket_id} not found.")

        self._validate_assignee(assigned_to)

        existing = self._get_assignment_by_ticket(ticket_id)
        if existing is not None:
            raise AssignmentError(
                f"Ticket #{ticket_id} is already assigned. Use reassign instead."
            )

        try:
            self._db.execute(
                """
                INSERT INTO Assignments (TicketID, AssignedTo, AssignedDate)
                VALUES (?, ?, GETDATE());
                """,
                (ticket_id, assigned_to),
            )
            self._update_ticket_status_assigned(ticket_id)
            self._db.commit()

            assignment_id = self._db.get_last_insert_id()
            if assignment_id is None:
                raise AssignmentError("Assignment created but ID could not be retrieved.")

            assignment = self.get_assignment_by_id(assignment_id)
            if assignment is None:
                raise AssignmentError("Assignment created but could not be loaded.")
            return assignment
        except DatabaseError as exc:
            self._db.rollback()
            raise AssignmentError(f"Failed to assign ticket: {exc}") from exc

    def reassign_ticket(self, ticket_id: int, new_assignee_id: int) -> Assignment:
        """
        Reassign an existing ticket to a different support agent or admin.

        Returns:
            The updated Assignment object.
        """
        self._require_assign_permission()

        if not self._ticket_exists(ticket_id):
            raise AssignmentError(f"Ticket #{ticket_id} not found.")

        self._validate_assignee(new_assignee_id)

        existing = self._get_assignment_by_ticket(ticket_id)
        if existing is None:
            raise AssignmentError(
                f"Ticket #{ticket_id} is not assigned. Use assign instead."
            )

        if existing.assigned_to == new_assignee_id:
            raise AssignmentError("Ticket is already assigned to this user.")

        try:
            self._db.execute(
                """
                UPDATE Assignments
                SET AssignedTo = ?, AssignedDate = GETDATE()
                WHERE TicketID = ?;
                """,
                (new_assignee_id, ticket_id),
                commit=True,
            )

            updated = self._get_assignment_by_ticket(ticket_id)
            if updated is None:
                raise AssignmentError("Ticket reassigned but could not be loaded.")
            return updated
        except DatabaseError as exc:
            raise AssignmentError(f"Failed to reassign ticket: {exc}") from exc

    def get_assignment_by_id(self, assignment_id: int) -> Optional[Assignment]:
        """Fetch a single assignment by ID."""
        try:
            row = self._db.fetch_one(
                f"{self.BASE_SELECT} WHERE a.AssignmentID = ?;",
                (assignment_id,),
            )
        except DatabaseError as exc:
            raise AssignmentError(f"Unable to fetch assignment: {exc}") from exc

        if row is None:
            return None
        return self._row_to_assignment(row)

    def view_assignments(self) -> List[Assignment]:
        """
        Return assignments visible to the current user.
        Admins see all; support agents see their own assignments.
        """
        user = self._auth.require_login()

        try:
            if user.is_admin():
                rows = self._db.fetch_all(
                    f"{self.BASE_SELECT} ORDER BY a.AssignedDate DESC;"
                )
            elif user.is_support_agent():
                rows = self._db.fetch_all(
                    f"{self.BASE_SELECT} WHERE a.AssignedTo = ? ORDER BY a.AssignedDate DESC;",
                    (user.user_id,),
                )
            else:
                raise AssignmentError(
                    "Access denied. Employees cannot view assignment records."
                )
        except DatabaseError as exc:
            raise AssignmentError(f"Unable to fetch assignments: {exc}") from exc

        return [self._row_to_assignment(row) for row in rows]

    def view_assignment_for_ticket(self, ticket_id: int) -> Optional[Assignment]:
        """Return the assignment for a specific ticket, with access control."""
        user = self._auth.require_login()

        if not user.can_manage_all_tickets():
            ticket_owner = self._db.fetch_scalar(
                "SELECT CreatedBy FROM Tickets WHERE TicketID = ?;",
                (ticket_id,),
            )
            if ticket_owner != user.user_id:
                raise AssignmentError("Access denied.")

        return self._get_assignment_by_ticket(ticket_id)

    def get_assignments_for_agent(self, agent_id: int) -> List[Assignment]:
        """Return all assignments for a given agent (admin-only)."""
        self._auth.require_role(Role.ADMIN)
        self._validate_assignee(agent_id)

        try:
            rows = self._db.fetch_all(
                f"{self.BASE_SELECT} WHERE a.AssignedTo = ? ORDER BY a.AssignedDate DESC;",
                (agent_id,),
            )
        except DatabaseError as exc:
            raise AssignmentError(f"Unable to fetch agent assignments: {exc}") from exc

        return [self._row_to_assignment(row) for row in rows]

    def get_assigned_ticket_count(self, agent_id: Optional[int] = None) -> int:
        """Return count of assigned tickets, optionally filtered by agent."""
        try:
            if agent_id is not None:
                return self._db.fetch_scalar(
                    "SELECT COUNT(*) FROM Assignments WHERE AssignedTo = ?;",
                    (agent_id,),
                )
            return self._db.fetch_scalar("SELECT COUNT(*) FROM Assignments;")
        except DatabaseError as exc:
            raise AssignmentError(f"Unable to count assignments: {exc}") from exc


# Shared assignment service instance
assignment_service = AssignmentService()
