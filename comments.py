from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from auth import AuthService, auth
from database import Database, DatabaseError, db


class CommentError(Exception):
    """Raised when comment operations fail."""
    pass


@dataclass
class Comment:
    comment_id: int
    ticket_id: int
    user_id: int
    comment_text: str
    created_date: Optional[datetime]
    user_name: Optional[str] = None

    def __str__(self) -> str:
        created = (
            self.created_date.strftime("%Y-%m-%d %H:%M")
            if self.created_date
            else "N/A"
        )
        return f"[{created}] {self.user_name}: {self.comment_text}"


class CommentService:

    BASE_SELECT = """
        SELECT
            c.CommentID,
            c.TicketID,
            c.UserID,
            c.CommentText,
            c.CreatedDate,
            u.FullName AS UserName
        FROM Comments c
        INNER JOIN Users u ON c.UserID = u.UserID
    """

    def __init__(
        self,
        database: Database = db,
        auth_service: AuthService = auth,
    ):
        self._db = database
        self._auth = auth_service

    def _row_to_comment(self, row):
        return Comment(
            comment_id=row.CommentID,
            ticket_id=row.TicketID,
            user_id=row.UserID,
            comment_text=row.CommentText,
            created_date=row.CreatedDate,
            user_name=row.UserName,
        )

    def add_comment(self, ticket_id: int, comment_text: str) -> Comment:

        user = self._auth.require_login()

        if not comment_text.strip():
            raise CommentError("Comment cannot be empty.")

        try:
            self._db.execute(
                """
                INSERT INTO Comments
                (TicketID, UserID, CommentText, CreatedDate)
                VALUES (?, ?, ?, GETDATE())
                """,
                (
                    ticket_id,
                    user.user_id,
                    comment_text.strip(),
                ),
                commit=True,
            )

            comment_id = self._db.get_last_insert_id()

            return self.get_comment_by_id(comment_id)

        except DatabaseError as exc:
            raise CommentError(f"Failed to add comment: {exc}") from exc

    def get_comment_by_id(self, comment_id: int):

        try:
            row = self._db.fetch_one(
                f"{self.BASE_SELECT} WHERE c.CommentID = ?",
                (comment_id,),
            )

            if row is None:
                return None

            return self._row_to_comment(row)

        except DatabaseError as exc:
            raise CommentError(f"Unable to fetch comment: {exc}") from exc

    def get_comments_by_ticket(self, ticket_id: int) -> List[Comment]:

        try:
            rows = self._db.fetch_all(
                f"{self.BASE_SELECT} WHERE c.TicketID = ? ORDER BY c.CreatedDate ASC",
                (ticket_id,),
            )

            return [self._row_to_comment(row) for row in rows]

        except DatabaseError as exc:
            raise CommentError(f"Unable to fetch comments: {exc}") from exc

    def delete_comment(self, comment_id: int):

        user = self._auth.require_login()

        if not user.is_admin():
            raise CommentError("Only admin can delete comments.")

        try:
            self._db.execute(
                "DELETE FROM Comments WHERE CommentID = ?",
                (comment_id,),
                commit=True,
            )

        except DatabaseError as exc:
            raise CommentError(f"Unable to delete comment: {exc}") from exc


comment_service = CommentService()