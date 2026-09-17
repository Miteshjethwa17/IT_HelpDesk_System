from ticket import ticket_service
from assignment import assignment_service


class ReportService:
    """Generates simple reports for the Help Desk System."""

    def ticket_status_report(self):
        print("\n===== TICKET STATUS REPORT =====")

        try:
            counts = ticket_service.get_ticket_count_by_status()

            for status, count in counts.items():
                print(f"{status}: {count}")

        except Exception as exc:
            print(f"Report Error: {exc}")

    def assignment_report(self):
        print("\n===== ASSIGNMENT REPORT =====")

        try:
            total = assignment_service.get_assigned_ticket_count()
            print(f"Total Assigned Tickets: {total}")

        except Exception as exc:
            print(f"Report Error: {exc}")


report_service = ReportService()