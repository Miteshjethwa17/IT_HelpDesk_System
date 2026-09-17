from ticket import ticket_service, TicketStatus
from assignment import assignment_service


class DashboardService:
    """Dashboard summary service."""

    def get_dashboard_data(self):
        data = {}

        try:
            data["ticket_counts"] = ticket_service.get_ticket_count_by_status()
        except Exception:
            data["ticket_counts"] = {}

        try:
            data["assigned_tickets"] = (
                assignment_service.get_assigned_ticket_count()
            )
        except Exception:
            data["assigned_tickets"] = 0

        return data

    def print_dashboard(self):
        data = self.get_dashboard_data()

        print("\n" + "=" * 50)
        print("HELP DESK DASHBOARD")
        print("=" * 50)

        counts = data.get("ticket_counts", {})

        for status in TicketStatus.ALL:
            print(f"{status}: {counts.get(status, 0)}")

        print("-" * 50)
        print(f"Assigned Tickets: {data.get('assigned_tickets', 0)}")
        print("=" * 50)


dashboard_service = DashboardService()